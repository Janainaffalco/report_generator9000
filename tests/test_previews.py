import hashlib
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from report_generator9000.previews import (
    OfficePreviewRenderer,
    RenderFailed,
    RenderRejected,
    discover_soffice,
)
from tests.fixtures.docx_builder import (
    RelationshipSpec,
    build_docx,
    paragraph,
    png_bytes,
)


_SOFFICE_UNAVAILABLE = discover_soffice() is None


def _tiny_docx(tmp_path: Path, *, marker: str, image: bytes) -> Path:
    return build_docx(
        tmp_path / "report.docx",
        paragraphs=[
            paragraph("PÁGINA HOME", keep_next=True),
            paragraph(image="rIdImage", extent=(5_400_000, 2_700_000)),
            paragraph(marker),
        ],
        media={"media/capture.png": image},
        relationships=[
            RelationshipSpec(id="rIdImage", target="media/capture.png")
        ],
    )


@pytest.mark.skipif(
    _SOFFICE_UNAVAILABLE, reason="soffice/libreoffice not discoverable"
)
def test_office_renderer_produces_pdf_and_maps_evidence_to_pages(
    tmp_path: Path,
) -> None:
    marker = "[PENDÊNCIA: NÃO FORNECIDO — cnpj_doc]"
    image = png_bytes(100, 50, red=255, green=0, blue=0)
    document = _tiny_docx(tmp_path, marker=marker, image=image)

    preview = OfficePreviewRenderer().render(document, tmp_path / "previews")

    assert preview.pdf == document.with_suffix(".pdf")
    assert preview.pdf.is_file()
    pdf = pdfium.PdfDocument(str(preview.pdf))
    try:
        assert len(preview.pages) == len(pdf)
    finally:
        pdf.close()
    assert len(preview.pages) >= 1
    assert all(path.is_file() for path in preview.pages)

    digest = hashlib.sha256(image).hexdigest()
    assert preview.page_for_evidence(digest) == 1
    assert preview.page_for_evidence(marker) == 1


def test_missing_soffice_path_raises_render_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "REPORT_SOFFICE_PATH", str(tmp_path / "does-not-exist-soffice")
    )
    document = _tiny_docx(
        tmp_path, marker="[X]", image=png_bytes(10, 10)
    )

    with pytest.raises(RenderFailed):
        OfficePreviewRenderer().render(document, tmp_path / "previews")


def test_soffice_producing_no_pdf_raises_render_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import report_generator9000.previews as previews_module

    monkeypatch.setattr(
        previews_module, "discover_soffice", lambda: Path("fake-soffice")
    )

    class _FakeResult:
        returncode = 0
        stdout = b"convert ... but nothing written\n"
        stderr = b""

    monkeypatch.setattr(
        previews_module.subprocess,
        "run",
        lambda *args, **kwargs: _FakeResult(),
    )
    document = _tiny_docx(
        tmp_path, marker="[X]", image=png_bytes(10, 10)
    )

    with pytest.raises(RenderFailed, match="no PDF"):
        OfficePreviewRenderer().render(document, tmp_path / "previews")


def test_zero_page_pdf_raises_render_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import report_generator9000.previews as previews_module

    monkeypatch.setattr(
        previews_module, "discover_soffice", lambda: Path("fake-soffice")
    )
    pdf_path = tmp_path / "report.pdf"
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 300)
    pdf.save(str(pdf_path))
    pdf.close()
    monkeypatch.setattr(
        previews_module,
        "_convert_to_pdf",
        lambda document, soffice: pdf_path,
    )
    # Report zero pages even though the stub PDF has one -- the renderer
    # trusts this seam for the page count it validates against.
    monkeypatch.setattr(previews_module, "_pdf_page_count", lambda pdf: 0)
    document = _tiny_docx(
        tmp_path, marker="[X]", image=png_bytes(10, 10)
    )

    with pytest.raises(RenderRejected, match="zero pages"):
        OfficePreviewRenderer().render(document, tmp_path / "previews")


def test_raster_count_mismatch_raises_render_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import report_generator9000.previews as previews_module

    monkeypatch.setattr(
        previews_module, "discover_soffice", lambda: Path("fake-soffice")
    )
    pdf_path = tmp_path / "report.pdf"
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 300)
    pdf.new_page(200, 300)
    pdf.save(str(pdf_path))
    pdf.close()
    monkeypatch.setattr(
        previews_module,
        "_convert_to_pdf",
        lambda document, soffice: pdf_path,
    )
    output_folder = tmp_path / "previews"
    output_folder.mkdir()
    short_page = output_folder / "preview-001.png"
    short_page.write_bytes(png_bytes(4, 4))

    def _fake_rasterize(pdf, page_count, folder, dpi):
        # Real PDF has two pages, but only one PNG comes back -- a defect
        # this check exists to catch.
        return [short_page.resolve()], ["page one text"]

    monkeypatch.setattr(
        previews_module, "_rasterize_pages", _fake_rasterize
    )
    document = _tiny_docx(
        tmp_path, marker="[X]", image=png_bytes(10, 10)
    )

    with pytest.raises(RenderRejected, match="rasterized"):
        OfficePreviewRenderer().render(document, output_folder)
