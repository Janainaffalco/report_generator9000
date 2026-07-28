from pathlib import Path

import pytest
from PIL import Image, ImageChops

from report_generator9000.previews import DocumentPreviewRenderer
from tests.fixtures.docx_builder import (
    RelationshipSpec,
    build_docx,
    paragraph,
    png_bytes,
)


def _red_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    red, green, blue = image.convert("RGB").split()
    red_mask = red.point(lambda value: 255 if value > 240 else 0)
    green_mask = green.point(lambda value: 255 if value < 10 else 0)
    blue_mask = blue.point(lambda value: 255 if value < 10 else 0)
    return ImageChops.multiply(
        ImageChops.multiply(red_mask, green_mask),
        blue_mask,
    ).getbbox()


@pytest.mark.parametrize(
    ("pixel_size", "extent", "expected_size"),
    [
        ((100, 150), (5_400_000, 8_100_000), (886, 1329)),
        ((100, 50), (5_400_000, 2_700_000), (886, 443)),
    ],
)
def test_preview_uses_embedded_docx_extent_for_cropped_and_uncropped_blocks(
    tmp_path: Path,
    pixel_size: tuple[int, int],
    extent: tuple[int, int],
    expected_size: tuple[int, int],
) -> None:
    document = build_docx(
        tmp_path / "report.docx",
        paragraphs=[paragraph(image="rIdImage", extent=extent)],
        media={
            "media/capture.png": png_bytes(
                *pixel_size,
                red=255,
                green=0,
                blue=0,
            )
        },
        relationships=[
            RelationshipSpec(id="rIdImage", target="media/capture.png")
        ],
    )

    preview = DocumentPreviewRenderer().render(
        document,
        tmp_path / "previews",
    )[0]

    with Image.open(preview) as rendered:
        red_bbox = _red_bbox(rendered)
    assert red_bbox is not None
    left, top, right, bottom = red_bbox
    assert (right - left, bottom - top) == expected_size


def test_preview_keeps_a_block_heading_with_its_tall_image(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "report.docx",
        paragraphs=[
            paragraph(image="rIdEarlier", extent=(5_400_000, 3_000_000)),
            paragraph("PÁGINA HOME", keep_next=True),
            paragraph(image="rIdCapture", extent=(5_400_000, 8_100_000)),
        ],
        media={
            "media/earlier.png": png_bytes(
                100,
                60,
                red=0,
                green=0,
                blue=255,
            ),
            "media/capture.png": png_bytes(
                100,
                150,
                red=255,
                green=0,
                blue=0,
            ),
        },
        relationships=[
            RelationshipSpec(id="rIdEarlier", target="media/earlier.png"),
            RelationshipSpec(id="rIdCapture", target="media/capture.png"),
        ],
    )

    previews = DocumentPreviewRenderer().render(
        document,
        tmp_path / "previews",
    )

    assert len(previews) == 2
    with Image.open(previews[1]) as second_page:
        red_bbox = _red_bbox(second_page)
    assert red_bbox is not None
    _left, top, _right, _bottom = red_bbox
    assert top == DocumentPreviewRenderer.margin + 57
