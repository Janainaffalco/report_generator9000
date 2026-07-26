from __future__ import annotations

from pathlib import Path

from report_generator9000.docx_package import open_docx_package

from fixtures.docx_builder import (
    RelationshipSpec,
    build_docx,
    paragraph,
    png_bytes,
)


def _document_part(package):
    return next(
        part for part in package.parts if part.name == "word/document.xml"
    )


def _media_part(package):
    return next(
        part for part in package.parts if part.name.startswith("word/media/")
    )


def test_part_text_populated_for_xml_and_none_for_media(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Synthetic body text")],
        media={"media/image1.png": png_bytes(2, 2)},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )

    package = open_docx_package(docx_path)

    document_part = _document_part(package)
    assert document_part.text is not None
    assert "Synthetic body text" in document_part.text

    media_part = _media_part(package)
    assert media_part.text is None


def test_keep_next_true_for_bound_heading(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("SEÇÃO Exemplo", keep_next=True),
            paragraph(
                image="rIdImage1",
                extent=(999999, 888888),
            ),
        ],
        media={"media/image1.png": png_bytes(2, 2)},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )

    package = open_docx_package(docx_path)
    heading = package.paragraphs[0]

    assert heading.keep_next is True


def test_keep_next_false_for_plain_paragraph(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Just a plain paragraph")],
    )

    package = open_docx_package(docx_path)

    assert package.paragraphs[0].keep_next is False


def test_keep_next_false_when_val_is_false(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Disabled keepNext")],
    )
    # ParagraphSpec has no way to emit w:val="false" directly, so patch the
    # generated document.xml in place to cover that explicit form.
    import zipfile

    with zipfile.ZipFile(docx_path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}

    document_xml = contents["word/document.xml"].decode("utf-8")
    document_xml = document_xml.replace(
        "<w:p><w:r><w:t>Disabled keepNext</w:t></w:r></w:p>",
        (
            "<w:p><w:pPr><w:keepNext w:val=\"false\"/></w:pPr>"
            "<w:r><w:t>Disabled keepNext</w:t></w:r></w:p>"
        ),
    )
    contents["word/document.xml"] = document_xml.encode("utf-8")

    with zipfile.ZipFile(docx_path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)

    package = open_docx_package(docx_path)

    assert package.paragraphs[0].keep_next is False


def test_has_image_true_only_for_image_paragraph(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("SEÇÃO Exemplo", keep_next=True),
            paragraph(image="rIdImage1"),
        ],
        media={"media/image1.png": png_bytes(2, 2)},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )

    package = open_docx_package(docx_path)

    assert package.paragraphs[0].has_image is False
    assert package.paragraphs[1].has_image is True


def test_relationship_ids_includes_hyperlink_on_wrapping_element(
    tmp_path: Path,
) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("Link de exemplo", hyperlink="rIdExternal"),
        ],
        relationships=[
            RelationshipSpec(
                id="rIdExternal",
                target="https://example.invalid/",
                kind="hyperlink",
                external=True,
            )
        ],
    )

    package = open_docx_package(docx_path)
    link_paragraph = package.paragraphs[0]

    assert "rIdExternal" in link_paragraph.relationship_ids
    assert all(
        "rIdExternal" not in run.relationship_ids
        for run in link_paragraph.runs
    )


def test_paragraph_text_joins_runs(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Primeira parte ", "segunda parte")],
    )

    package = open_docx_package(docx_path)

    assert package.paragraphs[0].text == "Primeira parte segunda parte"
