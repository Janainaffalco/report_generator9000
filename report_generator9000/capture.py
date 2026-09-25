"""Capture one run's Lista de Páginas with a real browser."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont, ImageOps
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    Response,
)

from .browser_session import browser_context
from .docx_package import block_embedding_box_emu
from .events import notice
from .lista_paginas import ELEMENTO_TRANSVERSAL, Pagina
from .run_context import Artifact, Pendencia

if TYPE_CHECKING:
    from .prose import ExtractedPageText

DECLINE_SELECTORS = (
    "#cmplz-deny",
    ".cmplz-deny",
    "[data-cky-tag='reject-button']",
    ".cky-btn-reject",
    "#cookie_action_close_header_reject",
    "#cn-refuse-cookie",
    "#onetrust-reject-all-handler",
    "button[data-testid='uc-deny-all-button']",
    "button:has-text('Recusar')",
    "button:has-text('Rejeitar')",
    "button:has-text('Reject all')",
    "button:has-text('Decline')",
)
CONSENT_BANNER_SELECTORS = (
    "#cmplz-cookiebanner-container",
    ".cky-consent-container",
    "#cookie-law-info-bar",
    "#onetrust-banner-sdk",
    "[role='dialog'][aria-label*='cookie' i]",
    "[class*='cookie'][class*='banner']",
)
NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
"""Ask every intermediary to revalidate rather than serve a stored copy.

A Capture must depict the site as it is at Run time. Hosting stacks in front
of these sites (Hostinger's `hcdn`, LiteSpeed Cache, WordPress page caches)
will otherwise keep serving a maintenance page for some time after the owner
has taken the site out of maintenance, and the Run captures the stale copy.
Nothing in this application caches -- each Run launches a fresh browser
profile -- so revalidation is the only lever we hold. Honouring the request
header is at the intermediary's discretion, so this narrows the window rather
than closing it; `FRESHNESS_HEADERS` records what was actually served.
"""

FRESHNESS_HEADERS = (
    "x-hcdn-cache-status",
    "cf-cache-status",
    "x-litespeed-cache",
    "x-cache",
    "age",
)
"""Response headers naming the layer that answered, recorded per page."""

_SAFE_STEM = re.compile(r"[^a-z0-9]+")
_MANAGED_CAPTURE = re.compile(r"^\d{2}-[a-z0-9-]+\.png$")
PARTIAL_CAPTURE_BADGE_TEXT = "captura parcial da página"


class CaptureError(ValueError):
    """The requested Capture cannot be produced safely."""


@dataclass(frozen=True)
class CaptureConfig:
    """Browser and raster settings fixed for repeatable print captures."""

    viewport_width: int = 1600
    viewport_height: int = 900
    mobile_viewport_width: int = 390
    mobile_viewport_height: int = 844
    device_scale_factor: float = 2
    navigation_timeout_ms: int = 30_000
    network_idle_timeout_ms: int = 10_000
    lazy_settle_ms: int = 500
    embedding_max_width: int = 1600
    embedding_slot_width_emu: int | None = None
    embedding_max_height_emu: int | None = None
    minimum_color_count: int = 128

    def __post_init__(self) -> None:
        positive = (
            self.viewport_width,
            self.viewport_height,
            self.mobile_viewport_width,
            self.mobile_viewport_height,
            self.device_scale_factor,
            self.navigation_timeout_ms,
            self.network_idle_timeout_ms,
            self.embedding_max_width,
            self.minimum_color_count,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("CaptureConfig values must be positive")
        if self.lazy_settle_ms < 0:
            raise ValueError("lazy_settle_ms cannot be negative")
        height_box = (
            self.embedding_slot_width_emu,
            self.embedding_max_height_emu,
        )
        if (height_box[0] is None) != (height_box[1] is None):
            raise ValueError(
                "embedding Slot width and height cap must be supplied together"
            )
        if any(value is not None and value <= 0 for value in height_box):
            raise ValueError("embedding Slot dimensions must be positive")


@dataclass(frozen=True)
class EmbeddingDerivative:
    """Observable result of building a Word embedding derivative."""

    width: int
    height: int
    cropped: bool
    cropped_from_width: int | None = None
    cropped_from_height: int | None = None


@dataclass(frozen=True)
class Capture:
    """A native Capture plus its aspect-preserving embedding derivative."""

    pagina: Pagina
    raw_path: Path
    embedding_path: Path
    raw_digest: str
    embedding_digest: str
    raw_width: int
    raw_height: int
    embedding_width: int
    embedding_height: int
    cropped: bool
    cropped_from_width: int | None
    cropped_from_height: int | None
    color_count: int
    consent_warning: bool = False

    @property
    def artifact(self) -> Artifact:
        return Artifact(
            digest=self.embedding_digest,
            origin="capture",
            label=self.pagina.titulo_bloco,
            source=str(self.embedding_path.resolve()),
        )


@dataclass(frozen=True)
class CaptureFailure:
    """A Capture that automation could not safely supply."""

    pagina: Pagina
    reason: str
    raw_path: Path | None = None
    evidence: str = "capture-unavailable"

    @property
    def pendencia(self) -> Pendencia:
        return Pendencia(
            slot=f"capture:{self.pagina.titulo_bloco}",
            classification="TOOL_BLOCKED",
            reason=self.reason,
            evidence=self.evidence,
            name=self.pagina.titulo_bloco,
            page=self.pagina.titulo_bloco,
            required_action="Investigar a automação e refazer esta Capture",
        )


@dataclass(frozen=True)
class CaptureRun:
    """All successful, warned, and failed Captures from one fresh run."""

    folder: Path
    captures: tuple[Capture, ...]
    failures: tuple[CaptureFailure, ...]

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        return tuple(capture.artifact for capture in self.captures)

    @property
    def pendencias(self) -> tuple[Pendencia, ...]:
        failures = tuple(failure.pendencia for failure in self.failures)
        warnings = tuple(
            Pendencia(
                slot=f"capture:{capture.pagina.titulo_bloco}",
                classification="TOOL_BLOCKED",
                reason=(
                    "banner de consentimento sem opção de recusa permaneceu "
                    "visível na Capture"
                ),
                evidence=capture.embedding_digest,
                name=capture.pagina.titulo_bloco,
                page=capture.pagina.titulo_bloco,
                required_action=(
                    "Revisar o banner e, se possível, habilitar uma opção "
                    "de recusa antes de refazer a Capture"
                ),
            )
            for capture in self.captures
            if capture.consent_warning
        )
        return (*failures, *warnings)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_stem(label: str) -> str:
    folded = unicodedata.normalize("NFKD", label)
    ascii_label = (
        "".join(
            character
            for character in folded
            if not unicodedata.combining(character)
        )
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return _SAFE_STEM.sub("-", ascii_label.casefold()).strip("-") or "pagina"


def image_color_count(path: str | Path) -> int:
    """Count colors on a bounded sample used to reject blank Captures."""
    with Image.open(path) as source:
        sample = ImageOps.exif_transpose(source).convert("RGB")
        sample.thumbnail((256, 256), Image.Resampling.LANCZOS)
        return len(set(sample.get_flattened_data()))


def fitted_emu_dimensions(
    slot_width_emu: int, image_width: int, image_height: int
) -> tuple[int, int]:
    """Hold the Word Slot width and derive height from the real ratio."""
    if min(slot_width_emu, image_width, image_height) <= 0:
        raise ValueError("Slot and image dimensions must be positive")
    return slot_width_emu, round(slot_width_emu * image_height / image_width)


def _burn_partial_capture_badge(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    font_path = Path(__file__).parent / "assets" / "Montserrat-Regular.ttf"
    font_size = max(8, round(image.width * 0.016))
    margin = max(3, round(image.width * 0.008))
    padding_x = max(4, round(image.width * 0.006))
    padding_y = max(2, round(image.width * 0.003))
    while True:
        font = ImageFont.truetype(str(font_path), font_size)
        text_box = draw.textbbox((0, 0), PARTIAL_CAPTURE_BADGE_TEXT, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        if text_width + 2 * padding_x <= image.width - 2 * margin:
            break
        if font_size == 8:
            break
        font_size -= 1
    rectangle_width = min(image.width - margin, text_width + 2 * padding_x)
    rectangle_height = min(
        image.height - margin,
        text_height + 2 * padding_y,
    )
    left = margin
    top = max(0, image.height - margin - rectangle_height)
    right = left + rectangle_width
    bottom = image.height - margin
    draw.rectangle(
        (left, top, right, bottom),
        fill=(28, 28, 28),
        outline="white",
        width=1,
    )
    draw.text(
        (left + padding_x, top + padding_y - text_box[1]),
        PARTIAL_CAPTURE_BADGE_TEXT,
        fill="white",
        font=font,
    )


def build_embedding_derivative(
    raw_path: str | Path,
    embedding_path: str | Path,
    *,
    max_width: int,
    slot_width_emu: int | None = None,
    max_height_emu: int | None = None,
) -> EmbeddingDerivative:
    """Downscale, top-crop if required, and badge the embedding copy."""
    raw_path = Path(raw_path)
    embedding_path = Path(embedding_path)
    if max_width <= 0:
        raise ValueError("max_width must be positive")
    if (slot_width_emu is None) != (max_height_emu is None):
        raise ValueError("Slot width and height cap must be supplied together")
    with Image.open(raw_path) as source:
        raw_width, raw_height = source.size
        image = ImageOps.exif_transpose(source).convert("RGB")
        if image.width > max_width:
            height = max(1, round(image.height * max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        cropped = False
        if slot_width_emu is not None and max_height_emu is not None:
            max_pixel_height = max(
                1,
                int(image.width * max_height_emu / slot_width_emu),
            )
            if image.height > max_pixel_height:
                image = image.crop((0, 0, image.width, max_pixel_height))
                cropped = True
                _burn_partial_capture_badge(image)
        embedding_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(embedding_path, format="PNG", optimize=True)
        return EmbeddingDerivative(
            width=image.width,
            height=image.height,
            cropped=cropped,
            cropped_from_width=raw_width if cropped else None,
            cropped_from_height=raw_height if cropped else None,
        )


def capture_config_from_master(
    master: str | Path,
    base: CaptureConfig | None = None,
) -> CaptureConfig:
    """Bind Capture height to the Master's real Block and page geometry."""
    master_path = Path(master)
    try:
        with ZipFile(master_path) as archive:
            document = ElementTree.fromstring(
                archive.read("word/document.xml")
            )
            styles = (
                ElementTree.fromstring(archive.read("word/styles.xml"))
                if "word/styles.xml" in archive.namelist()
                else None
            )
    except (
        BadZipFile,
        KeyError,
        OSError,
        ElementTree.ParseError,
    ) as error:
        raise CaptureError(
            f"{master_path}: cannot read Capture geometry: {error}"
        ) from error
    try:
        slot_width_emu, max_height_emu = block_embedding_box_emu(
            document,
            styles,
        )
    except ValueError as error:
        raise CaptureError(
            f"{master_path}: cannot derive Capture geometry: {error}"
        ) from error
    return replace(
        CaptureConfig() if base is None else base,
        embedding_slot_width_emu=slot_width_emu,
        embedding_max_height_emu=max_height_emu,
    )


def _first_visible(page: Page, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() and locator.first.is_visible():
                return selector
        except PlaywrightError:
            continue
    return None


def _dismiss_consent(page: Page) -> bool:
    """Decline non-essential cookies; return True if a banner remains."""
    banner_before = _first_visible(page, CONSENT_BANNER_SELECTORS)
    for selector in DECLINE_SELECTORS:
        locator = page.locator(selector)
        try:
            if not locator.count() or not locator.first.is_visible():
                continue
            locator.first.click(timeout=2_000)
            page.wait_for_timeout(250)
            break
        except PlaywrightError:
            continue
    banner_after = _first_visible(page, CONSENT_BANNER_SELECTORS)
    return banner_after is not None and (
        banner_before is not None or banner_after is not None
    )


def _force_lazy_rendering(page: Page, config: CaptureConfig) -> None:
    page.evaluate(
        "() => window.scrollTo(0, Math.max("
        "document.body.scrollHeight, document.documentElement.scrollHeight))"
    )
    page.wait_for_timeout(config.lazy_settle_ms)
    try:
        page.wait_for_load_state(
            "networkidle", timeout=config.network_idle_timeout_ms
        )
    except PlaywrightError:
        # Network quiet is a hint that lazy content has settled, never a
        # precondition for a usable page. Site builders (Wix, Hostinger) keep
        # analytics beacons and chat sockets open for the life of the tab, so
        # they never reach networkidle at all -- waiting for it discarded
        # pages that had finished rendering seconds earlier. Whatever has
        # painted by now is what we capture.
        pass
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(config.lazy_settle_ms)


def _record_freshness(pagina: Pagina, response: Response | None) -> None:
    """Record which layer answered, so a stale Capture is evidence, not a guess.

    This is diagnostics, never Provenance: the Run log is not a source of
    truth for the report -- see docs/adr/0002.
    """
    if response is None:
        return
    observed: dict[str, str] = {}
    for header in FRESHNESS_HEADERS:
        value = response.header_value(header)
        if value is not None:
            observed[header.replace("-", "_")] = value
    notice(
        "capture_page_response",
        url=pagina.url,
        status=response.status,
        **observed,
    )


def _capture_page(
    page: Page,
    pagina: Pagina,
    raw_path: Path,
    config: CaptureConfig,
) -> bool:
    parsed = urlsplit(pagina.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CaptureError("Capture URL must be HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise CaptureError("Capture URL must not contain credentials")

    response = page.goto(
        pagina.url,
        wait_until="domcontentloaded",
        timeout=config.navigation_timeout_ms,
    )
    _record_freshness(pagina, response)
    # An error page renders plenty of colour, so the blank-Capture check cannot
    # catch it: a 404 or 503 photographed under a Block heading would present
    # the site's failure as evidence of the page. It is a failed Capture.
    if response is not None and response.status >= 400:
        raise CaptureError(f"Capture page answered HTTP {response.status}")
    final_url = urlsplit(page.url)
    if (
        final_url.netloc.casefold() != parsed.netloc.casefold()
        or final_url.username is not None
        or final_url.password is not None
    ):
        raise CaptureError("Capture navigation left the declared page host")
    _dismiss_consent(page)
    _force_lazy_rendering(page, config)
    consent_warning = _dismiss_consent(page)
    if pagina.tipo == ELEMENTO_TRANSVERSAL:
        selector = (
            "header"
            if pagina.rotulo.casefold() == "cabeçalho".casefold()
            else "footer"
        )
        landmark = page.locator(selector).first
        if not landmark.count() or not landmark.is_visible():
            raise CaptureError(f"site has no visible {selector} element")
        if consent_warning:
            landmark.scroll_into_view_if_needed()
            page.screenshot(
                path=str(raw_path),
                full_page=False,
                animations="disabled",
                scale="device",
            )
        else:
            landmark.screenshot(
                path=str(raw_path),
                animations="disabled",
                scale="device",
            )
    else:
        page.screenshot(
            path=str(raw_path),
            full_page=True,
            animations="disabled",
            scale="device",
        )
    return consent_warning


def _browser_failure(
    pages: tuple[Pagina, ...], reason: str
) -> tuple[CaptureFailure, ...]:
    return tuple(
        CaptureFailure(pagina=pagina, reason=reason) for pagina in pages
    )


def _clear_managed_captures(folder: Path) -> None:
    """Remove only files this module could have left from an earlier run."""
    for location in (folder, folder / "embutir"):
        if not location.exists():
            continue
        for path in location.iterdir():
            if path.is_file() and _MANAGED_CAPTURE.fullmatch(path.name):
                path.unlink()


def capture_site(
    pages: tuple[Pagina, ...],
    output_folder: str | Path,
    *,
    config: CaptureConfig | None = None,
) -> CaptureRun:
    """Capture *pages* freshly; browser automation is intentionally not injected."""
    settings = CaptureConfig() if config is None else config
    folder = Path(output_folder)
    embedding_folder = folder / "embutir"
    folder.mkdir(parents=True, exist_ok=True)
    embedding_folder.mkdir(parents=True, exist_ok=True)
    _clear_managed_captures(folder)
    captures: list[Capture] = []
    failures: list[CaptureFailure] = []
    processed_count = 0

    try:
        with ExitStack() as stack:
            desktop_context = stack.enter_context(
                browser_context(
                    viewport={
                        "width": settings.viewport_width,
                        "height": settings.viewport_height,
                    },
                    device_scale_factor=settings.device_scale_factor,
                    extra_http_headers=NO_CACHE_HEADERS,
                )
            )
            mobile_context = stack.enter_context(
                browser_context(
                    viewport={
                        "width": settings.mobile_viewport_width,
                        "height": settings.mobile_viewport_height,
                    },
                    device_scale_factor=settings.device_scale_factor,
                    extra_http_headers=NO_CACHE_HEADERS,
                )
            )
            desktop_page = desktop_context.new_page()
            mobile_page = mobile_context.new_page()
            for index, pagina in enumerate(pages, start=1):
                page = (
                    mobile_page
                    if pagina.visualizacao == "mobile"
                    else desktop_page
                )
                stem = f"{index:02d}-{_safe_stem(pagina.titulo_bloco)}"
                raw_path = folder / f"{stem}.png"
                embedding_path = embedding_folder / f"{stem}.png"
                raw_path.unlink(missing_ok=True)
                embedding_path.unlink(missing_ok=True)
                try:
                    warning = _capture_page(page, pagina, raw_path, settings)
                    colors = image_color_count(raw_path)
                    raw_digest = _digest(raw_path)
                    if colors < settings.minimum_color_count:
                        failures.append(
                            CaptureFailure(
                                pagina=pagina,
                                reason=(
                                    "Capture em branco ou sem conteúdo "
                                    f"renderizado ({colors} cores)"
                                ),
                                raw_path=raw_path,
                                evidence=raw_digest,
                            )
                        )
                        continue
                    with Image.open(raw_path) as raw:
                        raw_width, raw_height = raw.size
                    derivative = build_embedding_derivative(
                        raw_path,
                        embedding_path,
                        max_width=settings.embedding_max_width,
                        slot_width_emu=settings.embedding_slot_width_emu,
                        max_height_emu=settings.embedding_max_height_emu,
                    )
                    captures.append(
                        Capture(
                            pagina=pagina,
                            raw_path=raw_path,
                            embedding_path=embedding_path,
                            raw_digest=raw_digest,
                            embedding_digest=_digest(embedding_path),
                            raw_width=raw_width,
                            raw_height=raw_height,
                            embedding_width=derivative.width,
                            embedding_height=derivative.height,
                            cropped=derivative.cropped,
                            cropped_from_width=(derivative.cropped_from_width),
                            cropped_from_height=(
                                derivative.cropped_from_height
                            ),
                            color_count=colors,
                            consent_warning=warning,
                        )
                    )
                except (
                    CaptureError,
                    OSError,
                    PlaywrightError,
                    ValueError,
                ) as error:
                    failures.append(
                        CaptureFailure(
                            pagina=pagina,
                            reason=f"Capture falhou: {error}",
                            raw_path=(raw_path if raw_path.exists() else None),
                            evidence=(
                                _digest(raw_path)
                                if raw_path.exists()
                                else "capture-unavailable"
                            ),
                        )
                    )
                finally:
                    processed_count += 1
    except PlaywrightError as error:
        failures.extend(
            _browser_failure(
                pages[processed_count:],
                f"browser de Capture indisponível: {error}",
            )
        )

    return CaptureRun(
        folder=folder.resolve(),
        captures=tuple(captures),
        failures=tuple(failures),
    )


def _page_text(page: Page, pagina: Pagina, settings: CaptureConfig) -> str:
    """Navigate to *pagina* and return its rendered body text."""
    parsed = urlsplit(pagina.url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CaptureError(
            "prose extraction URL must be unauthenticated HTTP(S)"
        )
    page.goto(
        pagina.url,
        wait_until="domcontentloaded",
        timeout=settings.navigation_timeout_ms,
    )
    final_url = urlsplit(page.url)
    if (
        final_url.netloc.casefold() != parsed.netloc.casefold()
        or final_url.username is not None
        or final_url.password is not None
    ):
        raise CaptureError("prose extraction left the declared page host")
    _dismiss_consent(page)
    _force_lazy_rendering(page, settings)
    return page.locator("body").inner_text().strip()


def extract_site_text(
    pages: tuple[Pagina, ...],
    *,
    config: CaptureConfig | None = None,
) -> tuple[ExtractedPageText, ...]:
    """Extract rendered body text without exposing markup to prose providers."""
    from .prose import ExtractedPageText

    settings = CaptureConfig() if config is None else config
    extracted: list[ExtractedPageText] = []
    seen: set[str] = set()
    skipped = 0
    with browser_context(
        viewport={
            "width": settings.viewport_width,
            "height": settings.viewport_height,
        },
        device_scale_factor=settings.device_scale_factor,
        extra_http_headers=NO_CACHE_HEADERS,
    ) as context:
        page = context.new_page()
        for pagina in pages:
            if not pagina.entra_no_briefing or pagina.url in seen:
                continue
            seen.add(pagina.url)
            # Prose is a best-effort enrichment -- `assembly` already
            # generates a report from no site text at all under `no_llm`.
            # So one page that times out, redirects off-host, or refuses
            # to load costs its own text and nothing more; letting it
            # escape would fail the whole engagement over an optional
            # input. This mirrors the per-page tolerance in `capture_site`.
            try:
                text = _page_text(page, pagina, settings)
            except (CaptureError, PlaywrightError):
                skipped += 1
                # A failed navigation leaves the tab on a pending
                # `chrome-error://` navigation that interrupts the *next*
                # page's `goto`. Without recycling the tab, one dead page
                # would still take down the page after it -- the very
                # cascade this per-page tolerance exists to stop.
                page.close()
                page = context.new_page()
                continue
            if text:
                extracted.append(
                    ExtractedPageText(
                        capture_origin=page.url,
                        text=text,
                    )
                )
    if skipped:
        notice(
            "extract_site_text_pages_skipped",
            severity="warning",
            skipped=skipped,
            extracted=len(extracted),
        )
    return tuple(extracted)


__all__ = [
    "CONSENT_BANNER_SELECTORS",
    "DECLINE_SELECTORS",
    "Capture",
    "CaptureConfig",
    "CaptureError",
    "CaptureFailure",
    "CaptureRun",
    "EmbeddingDerivative",
    "PARTIAL_CAPTURE_BADGE_TEXT",
    "build_embedding_derivative",
    "capture_config_from_master",
    "capture_site",
    "extract_site_text",
    "fitted_emu_dimensions",
    "image_color_count",
]
