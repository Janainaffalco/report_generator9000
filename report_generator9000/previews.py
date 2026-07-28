"""Generate visual DOCX QA previews without requiring an office renderer."""

from __future__ import annotations

import re
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Protocol
from zipfile import ZipFile
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .docx_package import Slot, open_docx_package, page_geometry_emu


_MANAGED_PREVIEW = re.compile(r"^preview-\d{3}\.png$")


class PreviewRenderer(Protocol):
    """Optional QA renderer; delivery never depends on headless office."""

    def render(
        self,
        document: Path,
        output_folder: Path,
    ) -> tuple[Path, ...]: ...


class DocumentPreviewRenderer:
    """Render text and embedded images into approximate A4-like PNG pages."""

    page_size = (1240, 1754)
    margin = 80
    footer_height = 60

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(
            str(
                Path(__file__).parent
                / "assets"
                / "Montserrat-wght.ttf"
            ),
            size,
        )

    def render(
        self,
        document: Path,
        output_folder: Path,
    ) -> tuple[Path, ...]:
        output_folder.mkdir(parents=True, exist_ok=True)
        for path in output_folder.iterdir():
            if path.is_file() and _MANAGED_PREVIEW.fullmatch(path.name):
                path.unlink()

        package = open_docx_package(document)
        slots_by_paragraph = defaultdict(list)
        for slot in package.slots:
            if (
                slot.source_part == "word/document.xml"
                and slot.media_part is not None
            ):
                slots_by_paragraph[slot.paragraph_index].append(slot)
        body = [
            paragraph
            for paragraph in package.paragraphs
            if paragraph.source_part == "word/document.xml"
        ]
        media_sizes = {
            item.part_name: (item.width, item.height)
            for item in package.media
        }
        with ZipFile(document) as archive:
            geometry = page_geometry_emu(
                ElementTree.fromstring(archive.read("word/document.xml"))
            )
        emu_to_preview_pixels = (
            self.page_size[0] / geometry.page_width_emu
        )

        def rendered_slot_size(slot: Slot) -> tuple[int, int]:
            if slot.media_part is None:
                raise ValueError("preview image Slot has no media part")
            width, height = media_sizes[slot.media_part]
            width_emu = slot.width_emu
            height_emu = slot.height_emu
            rendered_width = max(
                1,
                (
                    round(width_emu * emu_to_preview_pixels)
                    if width_emu is not None
                    else min(
                        self.page_size[0] - 2 * self.margin,
                        width,
                    )
                ),
            )
            rendered_height = max(
                1,
                (
                    round(height_emu * emu_to_preview_pixels)
                    if height_emu is not None
                    else round(rendered_width * height / width)
                ),
            )
            return rendered_width, rendered_height

        page = Image.new("RGB", self.page_size, "white")
        draw = ImageDraw.Draw(page)
        body_font = self._font(24)
        heading_font = self._font(27)
        note_font = self._font(18)
        y = self.margin
        rendered: list[Path] = []

        def finish_page() -> None:
            nonlocal page, draw, y
            page_number = len(rendered) + 1
            draw.line(
                (
                    self.margin,
                    self.page_size[1] - self.footer_height,
                    self.page_size[0] - self.margin,
                    self.page_size[1] - self.footer_height,
                ),
                fill=(190, 190, 190),
                width=1,
            )
            draw.text(
                (
                    self.margin,
                    self.page_size[1] - self.footer_height + 14,
                ),
                (
                    "QA PREVIEW aproximado — confirme paginação e "
                    f"sumário no Word · {page_number}"
                ),
                fill=(90, 90, 90),
                font=note_font,
            )
            path = output_folder / f"preview-{page_number:03d}.png"
            page.save(path, format="PNG", optimize=True)
            rendered.append(path.resolve())
            page = Image.new("RGB", self.page_size, "white")
            draw = ImageDraw.Draw(page)
            y = self.margin

        def ensure_space(height: int) -> None:
            if (
                y + height
                > self.page_size[1] - self.footer_height - self.margin
            ):
                finish_page()

        with ZipFile(document) as archive:
            for position, paragraph in enumerate(body):
                text = paragraph.text.strip()
                if text:
                    font = heading_font if paragraph.keep_next else body_font
                    lines = textwrap.wrap(text, width=76) or [text]
                    line_height = 39 if paragraph.keep_next else 34
                    text_height = len(lines) * line_height + 18
                    bound_image_height = 0
                    if paragraph.keep_next and position + 1 < len(body):
                        bound_image_height = sum(
                            rendered_slot_size(slot)[1] + 24
                            for slot in slots_by_paragraph.get(
                                body[position + 1].index,
                                (),
                            )
                            if slot.media_part in media_sizes
                        )
                    ensure_space(text_height + bound_image_height)
                    for line in lines:
                        draw.text(
                            (self.margin, y),
                            line,
                            fill=(25, 25, 25),
                            font=font,
                        )
                        y += line_height
                    y += 18
                for slot in slots_by_paragraph.get(paragraph.index, ()):
                    if slot.media_part not in media_sizes:
                        continue
                    rendered_width, rendered_height = rendered_slot_size(
                        slot
                    )
                    ensure_space(rendered_height + 24)
                    with archive.open(slot.media_part) as source:
                        with Image.open(source) as embedded:
                            visual = ImageOps.exif_transpose(
                                embedded
                            ).convert("RGB")
                            visual = visual.resize(
                                (rendered_width, rendered_height),
                                Image.Resampling.LANCZOS,
                            )
                            x = (self.page_size[0] - visual.width) // 2
                            page.paste(visual, (x, y))
                            y += visual.height + 24
        if y > self.margin or not rendered:
            finish_page()
        return tuple(rendered)


__all__ = [
    "DocumentPreviewRenderer",
    "PreviewRenderer",
]
