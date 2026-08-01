"""Derive an auditable colour palette from a site's public presentation."""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from playwright.sync_api import Error as PlaywrightError

from .browser_session import browser_context
from .capture import NO_CACHE_HEADERS

OBSERVED_NEAR_BLACK_LIGHTNESS = 0.05
OBSERVED_NEAR_WHITE_LIGHTNESS = 0.95
OBSERVED_LOW_SATURATION = 0.15
OBSERVED_MINIMUM_PAINTED_SHARE = 0.02
OBSERVED_MAXIMUM_SWATCHES = 6

_DECLARED_COLOR = re.compile(
    r"(?P<declaration>"
    r"(?P<property>--(?:"
    r"e-global-color-[\w-]+|"
    r"wp--preset--color--[\w-]+|"
    r"ast-global-color-\d+|"
    r"global-palette\d+|"
    r"generate-(?:color|palette)-[\w-]+|"
    r"gp-color-[\w-]+|"
    r"owp-[\w-]*color[\w-]*|"
    r"contrast(?:-\d+)?|base(?:-\d+)?|accent"
    r"))\s*:\s*"
    r"(?P<hex>#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)"
    r")(?=\s*[;}])"
)
_RGB_COLOR = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})"
    r"(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?))?\s*\)",
    re.IGNORECASE,
)
_HEX_COLOR = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")
_CSS_IMPORT = re.compile(
    r"@import\s+(?:url\(\s*)?['\"]?(?P<url>[^'\"\s)]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Stylesheet:
    """Saved stylesheet input for declaration extraction."""

    url: str
    text: str


@dataclass(frozen=True)
class PaletteColor:
    """One colour and the exact public evidence that supports it."""

    hex: str
    source: str
    evidence: str


@dataclass(frozen=True)
class PaletteDerivation:
    """The first successful stage in the ordered palette chain."""

    stage: str
    colors: tuple[PaletteColor, ...]

    def __post_init__(self) -> None:
        if self.stage not in {"declared", "observed", "undeclared"}:
            raise ValueError(f"Unknown palette derivation stage: {self.stage}")
        if self.stage == "undeclared" and self.colors:
            raise ValueError("An undeclared palette cannot contain colours")
        if self.stage == "observed" and len(self.colors) < 2:
            raise ValueError("An observed palette needs at least two colours")


@dataclass(frozen=True)
class ObservedPaint:
    """One computed CSS paint and its approximate rendered area."""

    color: str
    selector: str
    property: str
    painted_area: float
    opacity: float = 1.0


class PaletteCollectionError(RuntimeError):
    """Live public palette evidence could not be collected reliably."""


class _InlineStyles(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_style = False
        self._chunks: list[str] = []
        self.styles: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() == "style":
            self._in_style = True
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "style" and self._in_style:
            self.styles.append("".join(self._chunks))
            self._in_style = False
            self._chunks = []


def _deduplication_key(hex_code: str) -> str:
    digits = hex_code[1:]
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    return digits.casefold()


def _rgb(color: str) -> tuple[int, int, int] | None:
    match = _HEX_COLOR.fullmatch(color.strip())
    if match is not None:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        return tuple(int(digits[index : index + 2], 16) for index in (0, 2, 4))
    match = _RGB_COLOR.fullmatch(color.strip())
    if match is None:
        return None
    channels = tuple(int(match.group(index)) for index in (1, 2, 3))
    if any(channel > 255 for channel in channels):
        return None
    alpha = match.group(4)
    if alpha is not None and float(alpha) == 0:
        return None
    return channels


def _alpha(color: str) -> float:
    match = _RGB_COLOR.fullmatch(color.strip())
    if match is None or match.group(4) is None:
        return 1.0
    return float(match.group(4))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = Path(__file__).with_name("assets") / "Montserrat-wght.ttf"
    try:
        return ImageFont.truetype(str(font_path), max(1, size))
    except OSError:
        return ImageFont.load_default()


def extract_declared_colors(
    html: str,
    stylesheets: tuple[Stylesheet, ...],
    *,
    page_url: str = "inline page stylesheet",
) -> tuple[PaletteColor, ...]:
    """Return supported palette declarations verbatim, in source order."""
    parser = _InlineStyles()
    parser.feed(html)
    sources = (
        *(Stylesheet(page_url, text) for text in parser.styles),
        *stylesheets,
    )
    generatepress_site = "generatepress" in html.casefold() or any(
        "generatepress" in stylesheet.url.casefold()
        for stylesheet in stylesheets
    )
    generatepress_properties = {
        "--accent",
        "--base",
        "--base-2",
        "--base-3",
        "--contrast",
        "--contrast-2",
        "--contrast-3",
    }
    colors: list[PaletteColor] = []
    seen: set[str] = set()
    for stylesheet in sources:
        for match in _DECLARED_COLOR.finditer(stylesheet.text):
            if (
                match.group("property") in generatepress_properties
                and not generatepress_site
            ):
                continue
            hex_code = match.group("hex")
            key = _deduplication_key(hex_code)
            if key in seen:
                continue
            seen.add(key)
            colors.append(
                PaletteColor(
                    hex=hex_code,
                    source=stylesheet.url,
                    evidence=match.group("declaration"),
                )
            )
    return tuple(colors)


def extract_observed_colors(
    paints: tuple[ObservedPaint, ...],
    *,
    page_url: str,
) -> tuple[PaletteColor, ...]:
    """Rank usable computed paints, returning nothing below two swatches.

    Painted area includes all parseable opaque CSS colours. A candidate is
    discarded at HSL lightness <= 5% or >= 95%, HSL saturation <= 15%, or a
    painted-area share below 2%. At most the six largest colours are returned.
    """
    parsed: list[tuple[ObservedPaint, tuple[int, int, int], float]] = []
    for paint in paints:
        rgb = _rgb(paint.color)
        if rgb is not None and paint.painted_area > 0:
            parsed.append(
                (
                    paint,
                    rgb,
                    paint.painted_area
                    * _alpha(paint.color)
                    * min(1.0, max(0.0, paint.opacity)),
                )
            )
    total_area = sum(area for _paint, _rgb_value, area in parsed)
    if total_area <= 0:
        return ()

    area_by_hex: dict[str, float] = {}
    evidence_by_hex: dict[str, ObservedPaint] = {}
    evidence_area_by_hex: dict[str, float] = {}
    order: dict[str, int] = {}
    rgb_by_hex: dict[str, tuple[int, int, int]] = {}
    for index, (paint, rgb, effective_area) in enumerate(parsed):
        hex_code = _hex(rgb)
        order.setdefault(hex_code, index)
        rgb_by_hex[hex_code] = rgb
        area_by_hex[hex_code] = area_by_hex.get(hex_code, 0) + effective_area
        if effective_area > evidence_area_by_hex.get(hex_code, -1):
            evidence_by_hex[hex_code] = paint
            evidence_area_by_hex[hex_code] = effective_area

    usable: list[str] = []
    for hex_code, area in area_by_hex.items():
        red, green, blue = (channel / 255 for channel in rgb_by_hex[hex_code])
        _hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
        if (
            lightness <= OBSERVED_NEAR_BLACK_LIGHTNESS
            or lightness >= OBSERVED_NEAR_WHITE_LIGHTNESS
            or saturation <= OBSERVED_LOW_SATURATION
            or area / total_area < OBSERVED_MINIMUM_PAINTED_SHARE
        ):
            continue
        usable.append(hex_code)
    usable.sort(key=lambda item: (-area_by_hex[item], order[item]))
    usable = usable[:OBSERVED_MAXIMUM_SWATCHES]
    if len(usable) < 2:
        return ()
    return tuple(
        PaletteColor(
            hex=hex_code,
            source=page_url,
            evidence=(
                f"{evidence_by_hex[hex_code].selector} "
                f"{evidence_by_hex[hex_code].property}: "
                f"{evidence_by_hex[hex_code].color}"
            ),
        )
        for hex_code in usable
    )


def derive_palette(
    html: str,
    stylesheets: tuple[Stylesheet, ...],
    paints: tuple[ObservedPaint, ...],
    *,
    page_url: str,
) -> PaletteDerivation:
    """Run declaration, observation, then honest absence in that order."""
    declared = extract_declared_colors(
        html,
        stylesheets,
        page_url=page_url,
    )
    if declared:
        return PaletteDerivation(stage="declared", colors=declared)
    observed = extract_observed_colors(paints, page_url=page_url)
    if observed:
        return PaletteDerivation(stage="observed", colors=observed)
    return PaletteDerivation(stage="undeclared", colors=())


def derive_palette_from_site(capture_origin: str) -> PaletteDerivation:
    """Collect public CSS evidence from one rendered page and derive its palette."""
    requested = urlsplit(capture_origin)
    if (
        requested.scheme not in {"http", "https"}
        or not requested.netloc
        or requested.username is not None
        or requested.password is not None
    ):
        raise PaletteCollectionError(
            "Palette Capture Origin must be unauthenticated HTTP(S)"
        )
    try:
        with browser_context(
            viewport={"width": 1440, "height": 900},
            extra_http_headers=NO_CACHE_HEADERS,
        ) as context:
            page = context.new_page()
            page.goto(
                capture_origin,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            final = urlsplit(page.url)
            if (
                final.netloc.casefold() != requested.netloc.casefold()
                or final.username is not None
                or final.password is not None
            ):
                raise PaletteCollectionError(
                    "Palette navigation left the declared page host"
                )
            page.evaluate(
                "() => window.scrollTo(0, Math.max("
                "document.body.scrollHeight, "
                "document.documentElement.scrollHeight))"
            )
            page.wait_for_timeout(300)
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(100)
            html = page.content()
            stylesheet_urls = page.eval_on_selector_all(
                'link[rel~="stylesheet"][href]',
                "(links) => links.map((link) => link.href)",
            )
            stylesheets: list[Stylesheet] = []
            fetched: set[str] = set()

            def fetch_stylesheet(url: str) -> None:
                if url in fetched:
                    return
                fetched.add(url)
                try:
                    response = context.request.get(url, timeout=15_000)
                except PlaywrightError:
                    return
                if not response.ok:
                    return
                text = response.text()
                for match in _CSS_IMPORT.finditer(text):
                    imported_url = urljoin(url, match.group("url"))
                    if urlsplit(imported_url).scheme in {"http", "https"}:
                        fetch_stylesheet(imported_url)
                stylesheets.append(Stylesheet(url=url, text=text))

            for url in dict.fromkeys(stylesheet_urls):
                fetch_stylesheet(url)
            paint_documents = page.evaluate("""
                    () => {
                      const selectorFor = (element) => {
                        if (element.id) {
                          return `#${CSS.escape(element.id)}`;
                        }
                        const classes = Array.from(element.classList)
                          .slice(0, 3)
                          .map((name) => `.${CSS.escape(name)}`)
                          .join("");
                        return element.tagName.toLowerCase() + classes;
                      };
                      const paints = [];
                      for (const element of document.querySelectorAll("*")) {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        if (
                          rect.width <= 0 ||
                          rect.height <= 0 ||
                          style.display === "none" ||
                          style.visibility === "hidden" ||
                          Number(style.opacity) === 0
                        ) {
                          continue;
                        }
                        const selector = selectorFor(element);
                        const area = rect.width * rect.height;
                        let effectiveOpacity = 1;
                        for (
                          let ancestor = element;
                          ancestor instanceof Element;
                          ancestor = ancestor.parentElement
                        ) {
                          effectiveOpacity *= Number(
                            getComputedStyle(ancestor).opacity
                          );
                        }
                        const add = (
                          property,
                          color,
                          paintedArea,
                          propertyOpacity = 1
                        ) => {
                          if (color && paintedArea > 0) {
                            paints.push({
                              color,
                              selector,
                              property,
                              painted_area: paintedArea,
                              opacity: effectiveOpacity * propertyOpacity,
                            });
                          }
                        };
                        add(
                          "background-color",
                          style.backgroundColor,
                          area
                        );
                        add("color", style.color, area * 0.08);
                        for (const side of ["Top", "Right", "Bottom", "Left"]) {
                          const width = Number.parseFloat(
                            style[`border${side}Width`]
                          ) || 0;
                          const length = ["Top", "Bottom"].includes(side)
                            ? rect.width
                            : rect.height;
                          add(
                            `border-${side.toLowerCase()}-color`,
                            style[`border${side}Color`],
                            width * length
                          );
                        }
                        if (element instanceof SVGElement) {
                          add(
                            "fill",
                            style.fill,
                            area,
                            Number(style.fillOpacity)
                          );
                          add(
                            "stroke",
                            style.stroke,
                            (rect.width + rect.height) *
                              2 *
                              (Number.parseFloat(style.strokeWidth) || 1),
                            Number(style.strokeOpacity)
                          );
                        }
                      }
                      return paints;
                    }
                    """)
            paints = tuple(
                ObservedPaint(
                    color=str(item["color"]),
                    selector=str(item["selector"]),
                    property=str(item["property"]),
                    painted_area=float(item["painted_area"]),
                    opacity=float(item["opacity"]),
                )
                for item in paint_documents
            )
            return derive_palette(
                html,
                tuple(stylesheets),
                paints,
                page_url=page.url,
            )
    except PaletteCollectionError:
        raise
    except (OSError, PlaywrightError, ValueError) as error:
        raise PaletteCollectionError(
            f"Palette evidence collection failed: {error}"
        ) from error


def render_palette(
    hex_codes: tuple[str, ...],
    *,
    width: int,
    height: int,
) -> bytes:
    """Render the ``Cores`` artifact with hex codes as its only labels."""
    if not hex_codes:
        raise ValueError("A palette needs at least one colour")
    if width <= 0 or height <= 0:
        raise ValueError("Palette dimensions must be positive")
    parsed = tuple(_rgb(hex_code) for hex_code in hex_codes)
    if any(rgb is None for rgb in parsed):
        raise ValueError(
            "Palette colours must be three- or six-digit hex codes"
        )

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_height = max(1, round(height * 0.24))
    title_font = _font(min(max(12, height // 9), max(12, width // 8)))
    title_box = draw.textbbox((0, 0), "Cores", font=title_font)
    draw.text(
        (
            (width - (title_box[2] - title_box[0])) / 2,
            (title_height - (title_box[3] - title_box[1])) / 2 - title_box[1],
        ),
        "Cores",
        fill="#242424",
        font=title_font,
    )

    swatch_top = title_height
    label_font = _font(
        min(max(8, height // 11), max(8, width // (len(hex_codes) * 9)))
    )
    for index, (hex_code, rgb) in enumerate(
        zip(hex_codes, parsed, strict=True)
    ):
        assert rgb is not None
        left = round(index * width / len(hex_codes))
        right = round((index + 1) * width / len(hex_codes))
        draw.rectangle((left, swatch_top, right, height), fill=rgb)
        label_box = draw.textbbox((0, 0), hex_code, font=label_font)
        red, green, blue = (channel / 255 for channel in rgb)
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        draw.text(
            (
                left + ((right - left) - (label_box[2] - label_box[0])) / 2,
                swatch_top
                + ((height - swatch_top) - (label_box[3] - label_box[1])) / 2
                - label_box[1],
            ),
            hex_code,
            fill="black" if luminance > 0.55 else "white",
            font=label_font,
        )

    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Description", "\n".join(("Cores", *hex_codes)))
    output = BytesIO()
    image.save(output, format="PNG", pnginfo=metadata, optimize=True)
    return output.getvalue()


__all__ = [
    "OBSERVED_LOW_SATURATION",
    "OBSERVED_MAXIMUM_SWATCHES",
    "OBSERVED_MINIMUM_PAINTED_SHARE",
    "OBSERVED_NEAR_BLACK_LIGHTNESS",
    "OBSERVED_NEAR_WHITE_LIGHTNESS",
    "ObservedPaint",
    "PaletteCollectionError",
    "PaletteColor",
    "PaletteDerivation",
    "Stylesheet",
    "derive_palette",
    "derive_palette_from_site",
    "extract_declared_colors",
    "extract_observed_colors",
    "render_palette",
]
