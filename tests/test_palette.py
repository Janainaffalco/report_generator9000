from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from report_generator9000.palette import (
    ObservedPaint,
    Stylesheet,
    derive_palette,
    derive_palette_from_site,
    extract_declared_colors,
    extract_observed_colors,
    render_palette,
)
from test_lista_paginas import serve_fixture_site


FIXTURES = Path(__file__).parent / "fixtures" / "palette"


def test_elementor_declarations_are_reported_in_order_and_deduplicated() -> None:
    html = (FIXTURES / "elementor.html").read_text(encoding="utf-8")
    stylesheet = Stylesheet(
        url="https://cliente.example/elementor-kit-42.css",
        text=(FIXTURES / "elementor-kit-42.css").read_text(encoding="utf-8"),
    )

    colors = extract_declared_colors(html, (stylesheet,))

    assert [color.hex for color in colors] == [
        "#004127",
        "#7A7A7A",
        "#61CE70",
    ]
    assert [color.source for color in colors] == [stylesheet.url] * 3
    assert colors[0].evidence == "--e-global-color-primary: #004127"
    assert colors[1].evidence == "--e-global-color-secondary:#7A7A7A"
    assert colors[2].evidence == "--e-global-color-accent: #61CE70"


def test_elementor_factory_defaults_are_not_filtered() -> None:
    colors = extract_declared_colors(
        '<html class="elementor-kit-7"></html>',
        (
            Stylesheet(
                url="https://cliente.example/kit.css",
                text=":root { --e-global-color-primary: #6EC1E4; }",
            ),
        ),
    )

    assert [color.hex for color in colors] == ["#6EC1E4"]


@pytest.mark.parametrize(
    ("html", "url", "declaration", "expected"),
    [
        (
            "<html></html>",
            "https://cliente.example/global-styles.css",
            "--wp--preset--color--brand: #123456",
            "#123456",
        ),
        (
            "<html></html>",
            "https://cliente.example/astra.css",
            "--ast-global-color-0: #234567",
            "#234567",
        ),
        (
            "<html></html>",
            "https://cliente.example/kadence.css",
            "--global-palette1: #345678",
            "#345678",
        ),
        (
            '<body class="wp-theme-generatepress"></body>',
            "https://cliente.example/wp-content/themes/generatepress/style.css",
            "--accent: #456789",
            "#456789",
        ),
        (
            "<html></html>",
            "https://cliente.example/oceanwp.css",
            "--owp-primary-color: #56789A",
            "#56789A",
        ),
    ],
)
def test_supported_wordpress_theme_palette_declarations(
    html: str,
    url: str,
    declaration: str,
    expected: str,
) -> None:
    colors = extract_declared_colors(
        html,
        (Stylesheet(url=url, text=f":root {{ {declaration}; }}"),),
    )

    assert [color.hex for color in colors] == [expected]


def test_observed_colors_are_ranked_and_neutral_or_tiny_paints_are_absent() -> None:
    colors = extract_observed_colors(
        (
            ObservedPaint("rgb(255, 255, 255)", "body", "background-color", 5000),
            ObservedPaint("rgb(0, 0, 0)", "body", "color", 4000),
            ObservedPaint("rgb(128, 128, 128)", ".copy", "color", 3000),
            ObservedPaint("rgb(0, 122, 78)", ".hero", "background-color", 2400),
            ObservedPaint("#007A4E", ".button", "background-color", 1600),
            ObservedPaint("rgb(230, 80, 45)", "header", "background-color", 3000),
            ObservedPaint("rgb(30, 90, 210)", ".icon", "fill", 100),
        ),
        page_url="https://cliente.example/",
    )

    assert [color.hex for color in colors] == ["#007A4E", "#E6502D"]
    assert colors[0].source == "https://cliente.example/"
    assert colors[0].evidence == ".hero background-color: rgb(0, 122, 78)"
    assert colors[1].evidence == "header background-color: rgb(230, 80, 45)"


def test_translucent_paints_are_weighted_by_their_alpha() -> None:
    colors = extract_observed_colors(
        (
            ObservedPaint(
                "rgba(255, 0, 0, 0.01)",
                ".overlay",
                "background-color",
                10000,
            ),
            ObservedPaint("#007A4E", ".hero", "background-color", 5000),
            ObservedPaint("#E6502D", ".button", "background-color", 5000),
        ),
        page_url="https://cliente.example/",
    )

    assert [color.hex for color in colors] == ["#007A4E", "#E6502D"]


def test_element_opacity_reduces_the_effective_painted_area() -> None:
    colors = extract_observed_colors(
        (
            ObservedPaint(
                "#FF0000",
                ".overlay",
                "background-color",
                10000,
                opacity=0.01,
            ),
            ObservedPaint("#007A4E", ".hero", "background-color", 5000),
            ObservedPaint("#E6502D", ".button", "background-color", 5000),
        ),
        page_url="https://cliente.example/",
    )

    assert [color.hex for color in colors] == ["#007A4E", "#E6502D"]


def test_declared_stage_wins_when_observed_colors_are_also_usable() -> None:
    derivation = derive_palette(
        "<html></html>",
        (
            Stylesheet(
                "https://cliente.example/theme.css",
                ":root { --wp--preset--color--brand: #123456; }",
            ),
        ),
        (
            ObservedPaint("#007A4E", ".hero", "background-color", 5000),
            ObservedPaint("#E6502D", ".button", "background-color", 5000),
        ),
        page_url="https://cliente.example/",
    )

    assert derivation.stage == "declared"
    assert [color.hex for color in derivation.colors] == ["#123456"]


def test_fewer_than_two_surviving_observed_colors_falls_through() -> None:
    colors = extract_observed_colors(
        (
            ObservedPaint("#004127", ".hero", "background-color", 9000),
            ObservedPaint("#FFFFFF", "body", "background-color", 1000),
        ),
        page_url="https://cliente.example/",
    )

    assert colors == ()


def test_rendered_palette_has_only_the_title_and_hex_labels() -> None:
    content = render_palette(
        ("#004127", "#61CE70", "#E6502D"),
        width=900,
        height=300,
    )

    with Image.open(BytesIO(content)) as image:
        assert image.size == (900, 300)
        assert image.info["Description"] == "Cores\n#004127\n#61CE70\n#E6502D"


def test_live_collection_feeds_saved_page_declarations_to_the_stage_seam() -> None:
    with serve_fixture_site() as origin:
        derivation = derive_palette_from_site(origin)

    assert derivation.stage == "declared"
    assert [color.hex for color in derivation.colors] == [
        "#154360",
        "#23AA78",
    ]
    assert all(
        color.source == f"{origin}palette-tokens.css"
        for color in derivation.colors
    )
