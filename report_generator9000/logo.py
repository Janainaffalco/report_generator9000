"""Resolve and acquire the client's declared logo without heuristics."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .run_context import Artifact, Pendencia


CLIENT_LOGO_PART = "word/media/image2.png"
CLIENT_LOGO_PIXEL_SIZE = (1200, 600)
_LOGO_FILENAME = "client-logo.png"
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@dataclass(frozen=True)
class DeclaredLogo:
    """A logo URL selected from an explicit site declaration."""

    url: str
    declaration: str
    intrinsic_width: int | None = None
    intrinsic_height: int | None = None


@dataclass(frozen=True)
class LogoCapture:
    """A declared logo raster acquired from this run's Capture Origin."""

    declared: DeclaredLogo
    path: Path
    digest: str
    acquisition: str

    @property
    def artifact(self) -> Artifact:
        return Artifact(
            digest=self.digest,
            origin="capture",
            label="logo_cliente",
            source=str(self.path.resolve()),
        )


@dataclass(frozen=True)
class LogoFailure:
    """A logo Slot that could not honestly be filled."""

    classification: str
    reason: str
    required_action: str

    @property
    def pendencia(self) -> Pendencia:
        return Pendencia(
            slot="logo_cliente",
            classification=self.classification,
            reason=self.reason,
            evidence=f"logo-{self.classification.casefold()}",
            name="logo do cliente",
            page="BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO",
            required_action=self.required_action,
        )


@dataclass(frozen=True)
class _ElementContext:
    tag: str
    in_custom_logo: bool
    in_elementor_site_logo: bool


class _DeclarationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[str] = []
        self.custom_logo_sources: list[str] = []
        self.elementor_logo_sources: list[str] = []
        self._script_parts: list[str] | None = None
        self._context: list[_ElementContext] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = {name.casefold(): value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").casefold().split())
        normalized_tag = tag.casefold()
        parent_custom = (
            self._context[-1].in_custom_logo
            if self._context
            else False
        )
        parent_elementor = (
            self._context[-1].in_elementor_site_logo
            if self._context
            else False
        )
        custom = parent_custom or bool(
            {"custom-logo", "custom-logo-link"} & classes
        )
        elementor = parent_elementor or (
            "elementor-widget-theme-site-logo" in classes
            or attributes.get("data-widget_type", "")
            .casefold()
            .startswith("theme-site-logo")
        )
        if (
            normalized_tag == "script"
            and attributes.get("type", "").casefold()
            == "application/ld+json"
        ):
            self._script_parts = []
        if normalized_tag != "img":
            if normalized_tag not in _VOID_ELEMENTS:
                self._context.append(
                    _ElementContext(
                        normalized_tag,
                        custom,
                        elementor,
                    )
                )
            return
        source = attributes.get("src") or attributes.get("data-src")
        if not source:
            return
        if custom:
            self.custom_logo_sources.append(source)
        if elementor:
            self.elementor_logo_sources.append(source)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == "script" and self._script_parts is not None:
            self.json_ld.append("".join(self._script_parts))
            self._script_parts = None
        for index in range(len(self._context) - 1, -1, -1):
            if self._context[index].tag == normalized_tag:
                del self._context[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _organization_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [
            node
            for item in value
            for node in _organization_nodes(item)
        ]
    if not isinstance(value, dict):
        return []
    nodes = [value]
    graph = value.get("@graph")
    if graph is not None:
        nodes.extend(_organization_nodes(graph))
    return nodes


def _is_organization(node: dict[str, Any]) -> bool:
    node_type = node.get("@type")
    values = node_type if isinstance(node_type, list) else [node_type]
    return any(
        isinstance(value, str)
        and value.rsplit("/", 1)[-1].casefold() == "organization"
        for value in values
    )


def _json_ld_logo(
    documents: list[str], page_url: str
) -> DeclaredLogo | None:
    for document in documents:
        try:
            value = json.loads(document)
        except (json.JSONDecodeError, TypeError):
            continue
        nodes = _organization_nodes(value)
        nodes_by_id = {
            node_id: node
            for node in nodes
            if isinstance((node_id := node.get("@id")), str)
        }
        for node in nodes:
            if not _is_organization(node) or "logo" not in node:
                continue
            resolved = _resolve_json_ld_logo_value(
                node["logo"],
                nodes_by_id,
                page_url,
            )
            if resolved is not None:
                url, width, height = resolved
                return DeclaredLogo(
                    url,
                    "json-ld:Organization.logo",
                    width,
                    height,
                )
    return None


def _resolve_json_ld_logo_value(
    value: object,
    nodes_by_id: dict[str, dict[str, Any]],
    page_url: str,
    visited_ids: frozenset[str] = frozenset(),
) -> tuple[str, int | None, int | None] | None:
    if isinstance(value, list):
        for item in value:
            resolved = _resolve_json_ld_logo_value(
                item,
                nodes_by_id,
                page_url,
                visited_ids,
            )
            if resolved is not None:
                return resolved
        return None
    if isinstance(value, str):
        url = _declared_http_url(value, page_url)
        return None if url is None else (url, None, None)
    if not isinstance(value, dict):
        return None
    source = value.get("url") or value.get("contentUrl")
    url = _declared_http_url(source, page_url)
    if url is not None:
        return (
            url,
            _positive_int(value.get("width")),
            _positive_int(value.get("height")),
        )
    reference = value.get("@id")
    if (
        not isinstance(reference, str)
        or reference in visited_ids
        or reference not in nodes_by_id
    ):
        return None
    return _resolve_json_ld_logo_value(
        nodes_by_id[reference],
        nodes_by_id,
        page_url,
        visited_ids | {reference},
    )


def _is_safe_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def _declared_http_url(source: object, page_url: str) -> str | None:
    if not isinstance(source, str) or not source.strip():
        return None
    resolved = urljoin(page_url, source.strip())
    if not _is_safe_http_url(resolved):
        return None
    return resolved


def resolve_declared_logo(
    html: str, page_url: str
) -> DeclaredLogo | None:
    """Resolve the first supported logo declaration in strict priority order."""
    parser = _DeclarationParser()
    parser.feed(html)
    json_ld = _json_ld_logo(parser.json_ld, page_url)
    if json_ld is not None:
        return json_ld
    for source, declaration in (
        (parser.custom_logo_sources, "wordpress:custom_logo"),
        (parser.elementor_logo_sources, "elementor:site-logo"),
    ):
        for candidate in source:
            resolved = _declared_http_url(candidate, page_url)
            if resolved is not None:
                return DeclaredLogo(resolved, declaration)
    return None


def _matching_rendered_image(page: Page, declared_url: str):
    target = declared_url.split("#", 1)[0]
    images = page.locator("img")
    for index in range(images.count()):
        image = images.nth(index)
        try:
            source = image.evaluate(
                "(img) => new URL(img.currentSrc || img.src, document.baseURI)"
                ".href.split('#')[0]"
            )
            if (
                source == target
                and image.is_visible()
                and image.evaluate(
                    "(img) => img.complete && img.naturalWidth > 0 "
                    "&& img.naturalHeight > 0"
                )
            ):
                return image
        except PlaywrightError:
            continue
    return None


def _fit_to_slot(content: bytes, size: tuple[int, int]) -> bytes:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "white")
        left = (size[0] - image.width) // 2
        top = (size[1] - image.height) // 2
        canvas.paste(image, (left, top), image)
        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()


def _download_rasterized(
    page: Page,
    declared: DeclaredLogo,
) -> bytes:
    response = page.request.get(declared.url, timeout=30_000)
    if not response.ok:
        raise PlaywrightError(
            f"declared logo download returned HTTP {response.status}"
        )
    content = response.body()
    content_type = response.headers.get(
        "content-type", "application/octet-stream"
    ).split(";", 1)[0]
    encoded = base64.b64encode(content).decode("ascii")
    raster_page = page.context.new_page()
    try:
        raster_page.set_content(
            "<style>html,body{margin:0;background:white}"
            "img{display:block;max-width:1200px;max-height:1200px}</style>"
            f'<img id="logo" src="data:{content_type};base64,{encoded}">'
        )
        logo = raster_page.locator("#logo")
        logo.wait_for(state="visible")
        raster_page.wait_for_function(
            "() => { const i=document.querySelector('#logo'); "
            "return i.complete && i.naturalWidth > 0 && i.naturalHeight > 0; }"
        )
        return logo.screenshot(animations="disabled", scale="device")
    finally:
        raster_page.close()


def _failure(
    classification: str, reason: str
) -> LogoFailure:
    return LogoFailure(
        classification=classification,
        reason=reason,
        required_action=(
            "Anexar o logo do cliente"
            if classification == "UNDECLARED"
            else "Investigar a automação e refazer a Capture do logo"
        ),
    )


def capture_client_logo(
    capture_origin: str,
    output_folder: str | Path,
    *,
    slot_pixel_size: tuple[int, int] = CLIENT_LOGO_PIXEL_SIZE,
) -> LogoCapture | LogoFailure:
    """Acquire the declared logo as a Slot-sized PNG for this run."""
    if not _is_safe_http_url(capture_origin):
        return _failure("TOOL_BLOCKED", "Capture Origin inválida para o logo")
    parsed = urlsplit(capture_origin)
    if min(slot_pixel_size) <= 0:
        raise ValueError("logo Slot dimensions must be positive")
    folder = Path(output_folder)
    output = folder / _LOGO_FILENAME
    output.unlink(missing_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1600, "height": 900},
                    device_scale_factor=2,
                )
                page = context.new_page()
                page.goto(
                    capture_origin,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                final_url = urlsplit(page.url)
                if (
                    final_url.netloc.casefold()
                    != parsed.netloc.casefold()
                    or final_url.username is not None
                    or final_url.password is not None
                ):
                    return _failure(
                        "TOOL_BLOCKED",
                        "Capture do logo deixou o host do Capture Origin",
                    )
                try:
                    page.wait_for_load_state(
                        "networkidle", timeout=10_000
                    )
                except PlaywrightTimeoutError:
                    pass
                declared = resolve_declared_logo(page.content(), page.url)
                if declared is None:
                    return _failure(
                        "UNDECLARED",
                        "site não declara logo em nenhuma fonte suportada",
                    )
                rendered = _matching_rendered_image(page, declared.url)
                if rendered is not None:
                    content = rendered.screenshot(
                        animations="disabled", scale="device"
                    )
                    acquisition = "rendered-element"
                else:
                    content = _download_rasterized(page, declared)
                    acquisition = "download-rasterized"
                fitted = _fit_to_slot(content, slot_pixel_size)
            finally:
                browser.close()
    except (OSError, PlaywrightError, ValueError) as error:
        return _failure(
            "TOOL_BLOCKED",
            f"logo declarado não pôde ser capturado: {error}",
        )
    folder.mkdir(parents=True, exist_ok=True)
    output.write_bytes(fitted)
    return LogoCapture(
        declared=declared,
        path=output.resolve(),
        digest=hashlib.sha256(fitted).hexdigest(),
        acquisition=acquisition,
    )


__all__ = [
    "CLIENT_LOGO_PART",
    "CLIENT_LOGO_PIXEL_SIZE",
    "DeclaredLogo",
    "LogoCapture",
    "LogoFailure",
    "capture_client_logo",
    "resolve_declared_logo",
]
