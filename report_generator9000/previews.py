"""Render certified review pages: DOCX -> PDF (LibreOffice) -> PNG (pypdfium2).

The PDF and the review pages come from the same certified document, so what a
consultant reviews on screen is exactly what the PDF download contains -- not
an approximate QA drawing of it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, overload

import pypdfium2 as pdfium
from PIL import Image

from .docx_package import open_docx_package
from .generate import GateRejected


_MANAGED_PREVIEW = re.compile(r"^preview-\d{3}\.png$")
_TEXT_MARKER = re.compile(r"\[[^\[\]\r\n]+\]")

_RENDER_DPI = 150
_POINTS_PER_INCH = 72
_SOFFICE_TIMEOUT_SECONDS = 300
_WINDOWS_DEFAULT_SOFFICE = Path(
    r"C:\Program Files\LibreOffice\program\soffice.exe"
)
_TAIL_BYTES = 2000


class RenderFailed(Exception):
    """Office conversion or rasterization broke before certifying anything.

    Always means the pipeline itself is broken -- soffice missing, a crash, a
    timeout, or an unreadable PDF -- never that a produced document was
    inspected and found defective. A Run that hits this can never be marked
    finished.
    """


class RenderRejected(GateRejected):
    """Visual validation inspected the render and found it defective.

    Distinct from ``RenderFailed``: something was produced, but it failed an
    honest check (zero pages, a page count mismatch, an undecodable page).
    """


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class PreviewRender:
    """Rendered pages, the PDF they came from, and exact evidence-to-page joins."""

    pages: tuple[Path, ...]
    pdf: Path
    media_pages: dict[str, int]
    text_pages: dict[str, int]

    def __len__(self) -> int:
        return len(self.pages)

    def __iter__(self) -> Iterator[Path]:
        return iter(self.pages)

    @overload
    def __getitem__(self, index: int) -> Path: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Path, ...]: ...

    def __getitem__(self, index: int | slice) -> Path | tuple[Path, ...]:
        return self.pages[index]

    def page_for_evidence(self, evidence: str) -> int | None:
        return self.media_pages.get(evidence.lower()) or self.text_pages.get(
            evidence
        )


class PreviewRenderer(Protocol):
    """Renders a certified DOCX into a PDF plus the review pages of that PDF."""

    def render(
        self,
        document: Path,
        output_folder: Path,
    ) -> PreviewRender: ...


def discover_soffice() -> Path | None:
    """Find the LibreOffice headless executable, or ``None`` if it cannot be found.

    ``REPORT_SOFFICE_PATH`` is an explicit operator override and always wins,
    even when the path it names does not currently exist -- the caller finds
    out honestly when the conversion itself fails to launch, rather than this
    silently falling back to a different soffice.
    """
    override = os.environ.get("REPORT_SOFFICE_PATH")
    if override:
        return Path(override)
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return Path(found)
    if _WINDOWS_DEFAULT_SOFFICE.is_file():
        return _WINDOWS_DEFAULT_SOFFICE
    return None


def _clean_stale_previews(output_folder: Path) -> None:
    output_folder.mkdir(parents=True, exist_ok=True)
    for path in output_folder.iterdir():
        if path.is_file() and _MANAGED_PREVIEW.fullmatch(path.name):
            path.unlink()


def _convert_to_pdf(document: Path, soffice: Path) -> Path:
    pdf_path = document.with_suffix(".pdf")
    pdf_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="soffice-profile-") as profile_dir:
        profile_uri = Path(profile_dir).resolve().as_uri()
        command = [
            str(soffice),
            "--headless",
            "--norestore",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(document.parent),
            str(document),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=_SOFFICE_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as error:
            raise RenderFailed(
                f"soffice executable not found at {soffice}"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise RenderFailed(
                f"soffice timed out converting {document.name} to PDF after "
                f"{_SOFFICE_TIMEOUT_SECONDS}s"
            ) from error
    combined = (result.stdout or b"") + (result.stderr or b"")
    stderr_tail = (result.stderr or b"").decode("utf-8", errors="replace")[
        -_TAIL_BYTES:
    ]
    stdout_tail = (result.stdout or b"").decode("utf-8", errors="replace")[
        -_TAIL_BYTES:
    ]
    if result.returncode != 0 or b"could not be loaded" in combined:
        raise RenderFailed(
            f"soffice failed to convert {document.name} to PDF "
            f"(exit {result.returncode}): {stderr_tail or stdout_tail}"
        )
    if not pdf_path.is_file():
        raise RenderFailed(
            f"soffice reported success converting {document.name} but wrote "
            f"no PDF at {pdf_path}: {stdout_tail or stderr_tail}"
        )
    return pdf_path


def _pdf_page_count(pdf: pdfium.PdfDocument) -> int:
    return len(pdf)


def _rasterize_pages(
    pdf: pdfium.PdfDocument,
    page_count: int,
    output_folder: Path,
    dpi: int,
) -> tuple[list[Path], list[str]]:
    """Rasterize every page of *pdf* to a numbered PNG, and read its text."""
    rendered: list[Path] = []
    page_texts: list[str] = []
    scale = dpi / _POINTS_PER_INCH
    for index in range(page_count):
        page = pdf[index]
        bitmap = page.render(scale=scale)
        try:
            pil_image = bitmap.to_pil()
        finally:
            bitmap.close()
        if pil_image.width <= 0 or pil_image.height <= 0:
            raise RenderRejected(
                "STOP CONDITION: page "
                f"{index + 1} rasterized to an empty image"
            )
        path = output_folder / f"preview-{index + 1:03d}.png"
        pil_image.save(path, format="PNG", optimize=True)
        rendered.append(path.resolve())
        text_page = page.get_textpage()
        try:
            page_texts.append(text_page.get_text_bounded())
        finally:
            text_page.close()
    return rendered, page_texts


class OfficePreviewRenderer:
    """DOCX -> PDF via LibreOffice headless, PDF -> PNG pages via pypdfium2."""

    dpi = _RENDER_DPI

    def render(
        self,
        document: Path,
        output_folder: Path,
    ) -> PreviewRender:
        document = Path(document).resolve()
        output_folder = Path(output_folder)
        _clean_stale_previews(output_folder)

        soffice = discover_soffice()
        if soffice is None:
            raise RenderFailed(
                "LibreOffice (soffice) was not found -- set "
                "REPORT_SOFFICE_PATH, put soffice/libreoffice on PATH, or "
                "install LibreOffice at its default Windows location"
            )

        pdf_path = _convert_to_pdf(document, soffice)

        try:
            pdf = pdfium.PdfDocument(str(pdf_path))
        except Exception as error:
            raise RenderFailed(
                f"pypdfium2 could not open {pdf_path}: {error}"
            ) from error

        try:
            page_count = _pdf_page_count(pdf)
            if page_count == 0:
                raise RenderRejected(
                    "STOP CONDITION: the rendered PDF "
                    f"{pdf_path.name} has zero pages"
                )

            try:
                rendered, page_texts = _rasterize_pages(
                    pdf, page_count, output_folder, self.dpi
                )
            except RenderRejected:
                raise
            except Exception as error:
                raise RenderFailed(
                    f"pypdfium2 could not rasterize {pdf_path.name}: {error}"
                ) from error
        finally:
            pdf.close()

        for path in rendered:
            try:
                with Image.open(path) as check:
                    check.load()
            except Exception as error:
                raise RenderRejected(
                    "STOP CONDITION: rasterized page "
                    f"{path.name} is undecodable: {error}"
                ) from error

        if len(rendered) != page_count:
            raise RenderRejected(
                "STOP CONDITION: rasterized "
                f"{len(rendered)} pages but the PDF {pdf_path.name} has "
                f"{page_count}"
            )

        media_pages, text_pages = _evidence_page_map(document, page_texts)
        return PreviewRender(
            pages=tuple(rendered),
            pdf=pdf_path,
            media_pages=media_pages,
            text_pages=text_pages,
        )


def _evidence_page_map(
    document: Path, page_texts: list[str]
) -> tuple[dict[str, int], dict[str, int]]:
    """Map Pendência evidence (a media digest or a bracketed marker) to a page."""
    package = open_docx_package(document)
    body = [
        paragraph
        for paragraph in package.paragraphs
        if paragraph.source_part == "word/document.xml"
    ]
    slots_by_paragraph: dict[int, list] = defaultdict(list)
    for slot in package.slots:
        if slot.source_part == "word/document.xml" and slot.media_part is not None:
            slots_by_paragraph[slot.paragraph_index].append(slot)
    digest_by_part = {item.part_name: item.sha256.lower() for item in package.media}

    media_headings: dict[str, str] = {}
    for position, paragraph in enumerate(body):
        if not paragraph.keep_next or position + 1 >= len(body):
            continue
        heading_text = _normalize_whitespace(paragraph.text)
        if not heading_text:
            continue
        next_paragraph = body[position + 1]
        for slot in slots_by_paragraph.get(next_paragraph.index, ()):
            digest = digest_by_part.get(slot.media_part or "")
            if digest is not None:
                media_headings[digest] = heading_text

    normalized_pages = [_normalize_whitespace(text) for text in page_texts]
    media_pages: dict[str, int] = {}
    for digest, heading in media_headings.items():
        last_match: int | None = None
        for page_index, page_text in enumerate(normalized_pages, start=1):
            if heading in page_text:
                last_match = page_index
        if last_match is not None:
            media_pages[digest] = last_match

    markers: list[str] = []
    for paragraph in body:
        markers.extend(_TEXT_MARKER.findall(paragraph.text))
    text_pages: dict[str, int] = {}
    for marker in dict.fromkeys(markers):
        normalized_marker = _normalize_whitespace(marker)
        for page_index, page_text in enumerate(normalized_pages, start=1):
            if normalized_marker in page_text:
                text_pages[marker] = page_index
                break

    return media_pages, text_pages


__all__ = [
    "OfficePreviewRenderer",
    "PreviewRender",
    "PreviewRenderer",
    "RenderFailed",
    "RenderRejected",
    "discover_soffice",
]
