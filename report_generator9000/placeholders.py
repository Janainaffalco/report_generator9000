"""Render honest, dimension-preserving images for missing report inputs."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


_FONT = Path(__file__).with_name("assets") / "Montserrat-wght.ttf"
_BACKGROUND = "#F2F2F2"
_ACCENT = "#C00000"
_TEXT = "#242424"
_EMU_PER_INCH = 914_400
SLOT_RENDER_DPI = 150


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(_FONT), size=max(1, size))
    except OSError:
        return ImageFont.load_default()


def slot_pixel_dimensions(
    width_emu: int, height_emu: int
) -> tuple[int, int]:
    """Convert a Word Slot's physical dimensions to a print-ready raster."""
    return (
        max(1, round(width_emu / _EMU_PER_INCH * SLOT_RENDER_DPI)),
        max(1, round(height_emu / _EMU_PER_INCH * SLOT_RENDER_DPI)),
    )


def _fitted_caption(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    classification: str,
    name: str,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    available_width = max(1, width * 4 // 5)
    available_height = max(1, height * 3 // 5)
    size = max(1, min(width // 7, height // 3, 72))
    while size > 1:
        font = _font(size)
        characters_per_line = max(1, int(available_width / (size * 0.6)))
        caption = "\n".join(
            (classification, *wrap(name, width=characters_per_line))
        )
        box = draw.multiline_textbbox(
            (0, 0), caption, font=font, spacing=max(1, size // 3), align="center"
        )
        if (
            box[2] - box[0] <= available_width
            and box[3] - box[1] <= available_height
        ):
            return caption, font
        size -= 1
    return classification, _font(1)


def render_placeholder(
    original: bytes,
    classification: str,
    name: str,
    width: int,
    height: int,
) -> bytes:
    """Return a visibly captioned raster sized to the Word Slot."""
    with Image.open(BytesIO(original)) as source:
        image_format = source.format or "PNG"

    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    border = max(1, min(width, height) // 80)
    draw.rectangle(
        (0, 0, max(0, width - 1), max(0, height - 1)),
        outline=_ACCENT,
        width=border,
    )
    caption, font = _fitted_caption(
        draw, width, height, classification, name
    )
    box = draw.multiline_textbbox(
        (0, 0),
        caption,
        font=font,
        spacing=max(1, height // 80),
        align="center",
    )
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]
    draw.multiline_text(
        ((width - text_width) / 2, (height - text_height) / 2),
        caption,
        fill=_TEXT,
        font=font,
        spacing=max(1, height // 80),
        align="center",
    )

    output = BytesIO()
    if image_format == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Description", caption)
        image.save(output, format="PNG", pnginfo=metadata)
    elif image_format == "JPEG":
        exif = image.getexif()
        exif[270] = caption
        image.save(output, format="JPEG", quality=90, exif=exif)
    else:
        image.save(output, format=image_format)
    return output.getvalue()


__all__ = ["SLOT_RENDER_DPI", "render_placeholder", "slot_pixel_dimensions"]
