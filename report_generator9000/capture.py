"""Capture one run's Lista de Páginas with a real browser."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    sync_playwright,
)

from .lista_paginas import ELEMENTO_TRANSVERSAL, Pagina
from .run_context import Artifact, Pendencia


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
_SAFE_STEM = re.compile(r"[^a-z0-9]+")
_MANAGED_CAPTURE = re.compile(r"^\d{2}-[a-z0-9-]+\.png$")


class CaptureError(ValueError):
    """The requested Capture cannot be produced safely."""


@dataclass(frozen=True)
class CaptureConfig:
    """Browser and raster settings fixed for repeatable print captures."""

    viewport_width: int = 1600
    viewport_height: int = 900
    device_scale_factor: float = 2
    navigation_timeout_ms: int = 30_000
    network_idle_timeout_ms: int = 10_000
    lazy_settle_ms: int = 500
    embedding_max_width: int = 1600
    minimum_color_count: int = 128

    def __post_init__(self) -> None:
        positive = (
            self.viewport_width,
            self.viewport_height,
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
    ascii_label = "".join(
        character
        for character in folded
        if not unicodedata.combining(character)
    ).encode("ascii", "ignore").decode("ascii")
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
    return slot_width_emu, round(
        slot_width_emu * image_height / image_width
    )


def _embedding_image(
    raw_path: Path, embedding_path: Path, max_width: int
) -> tuple[int, int]:
    with Image.open(raw_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if image.width > max_width:
            height = max(1, round(image.height * max_width / image.width))
            image = image.resize(
                (max_width, height), Image.Resampling.LANCZOS
            )
        image.save(embedding_path, format="PNG", optimize=True)
        return image.size


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
    page.wait_for_load_state(
        "networkidle", timeout=config.network_idle_timeout_ms
    )
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(config.lazy_settle_ms)


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

    page.goto(
        pagina.url,
        wait_until="domcontentloaded",
        timeout=config.navigation_timeout_ms,
    )
    final_url = urlsplit(page.url)
    if (
        final_url.netloc.casefold() != parsed.netloc.casefold()
        or final_url.username is not None
        or final_url.password is not None
    ):
        raise CaptureError(
            "Capture navigation left the declared page host"
        )
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
    return tuple(CaptureFailure(pagina=pagina, reason=reason) for pagina in pages)


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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={
                        "width": settings.viewport_width,
                        "height": settings.viewport_height,
                    },
                    device_scale_factor=settings.device_scale_factor,
                )
                page = context.new_page()
                for index, pagina in enumerate(pages, start=1):
                    stem = f"{index:02d}-{_safe_stem(pagina.titulo_bloco)}"
                    raw_path = folder / f"{stem}.png"
                    embedding_path = embedding_folder / f"{stem}.png"
                    raw_path.unlink(missing_ok=True)
                    embedding_path.unlink(missing_ok=True)
                    try:
                        warning = _capture_page(
                            page, pagina, raw_path, settings
                        )
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
                        embedded_width, embedded_height = _embedding_image(
                            raw_path,
                            embedding_path,
                            settings.embedding_max_width,
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
                                embedding_width=embedded_width,
                                embedding_height=embedded_height,
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
                                raw_path=(
                                    raw_path if raw_path.exists() else None
                                ),
                                evidence=(
                                    _digest(raw_path)
                                    if raw_path.exists()
                                    else "capture-unavailable"
                                ),
                            )
                        )
                    finally:
                        processed_count += 1
            finally:
                browser.close()
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


__all__ = [
    "CONSENT_BANNER_SELECTORS",
    "DECLINE_SELECTORS",
    "Capture",
    "CaptureConfig",
    "CaptureError",
    "CaptureFailure",
    "CaptureRun",
    "capture_site",
    "fitted_emu_dimensions",
    "image_color_count",
]
