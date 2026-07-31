from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from report_generator9000.docx_package import (
    CM_TO_EMU,
    block_embedding_box_emu,
    open_docx_package,
    page_geometry_emu,
)
from report_generator9000.master import build_master

from fixtures.docx_builder import (
    RelationshipSpec,
    build_docx,
    paragraph,
    png_bytes,
)
from test_master_build import approved_source


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


def _block_fixture(
    path: Path,
    *,
    with_caption: bool,
) -> Path:
    """Build a minimal docx exhibiting one Block, optionally with a caption
    paragraph inserted between the heading and the image."""
    blocks = [
        paragraph(
            "SEÇÃO PRODUTOS",
            bookmark=(1, "MASTER_BLOCK_STAMP"),
            keep_next=True,
        ),
    ]
    if with_caption:
        blocks.append(
            paragraph("Uma legenda descrevendo a captura abaixo desta linha")
        )
    blocks.append(paragraph(image="rId1"))
    built = build_docx(
        path,
        paragraphs=blocks,
        media={"media/image1.png": png_bytes(10, 10)},
        relationships=[RelationshipSpec(id="rId1", target="media/image1.png")],
    )
    # Push the top margin in well under the 22.5 cm ceiling so the
    # caption's extra reservation is what moves the result, not the
    # ceiling clamp.
    with ZipFile(built) as archive:
        parts = {
            item.filename: archive.read(item.filename)
            for item in archive.infolist()
        }
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b'w:top="1701"', b'w:top="10000"'
    )
    with ZipFile(built, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return built


def _block_box(path: Path) -> tuple[int, int]:
    with ZipFile(path) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    return block_embedding_box_emu(document, styles=None)


def test_block_embedding_box_on_the_master_never_exceeds_the_measured_ceiling(
    tmp_path: Path,
) -> None:
    """22.5 cm is the ceiling the reporter measured on the rendered Master.

    The reservation computed from the Master's real geometry (heading only,
    on the approved Master) still leaves more than that -- the ceiling, not
    the geometry, must be what binds.
    """
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    with ZipFile(master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        styles = ElementTree.fromstring(archive.read("word/styles.xml"))

    _slot_width_emu, max_height_emu = block_embedding_box_emu(document, styles)

    assert max_height_emu <= int(22.5 * CM_TO_EMU)


def test_block_embedding_box_reserves_more_height_for_a_caption_paragraph(
    tmp_path: Path,
) -> None:
    """A caption paragraph between heading and image narrows the Capture cap.

    Before the fix, ``block_embedding_box_emu`` assumed the image paragraph
    always sits immediately after the heading, so it treated the caption
    paragraph itself as the image and raised (no image extent) instead of
    reserving its height.
    """
    no_caption = _block_fixture(
        tmp_path / "no-caption.docx", with_caption=False
    )
    with_caption = _block_fixture(
        tmp_path / "with-caption.docx", with_caption=True
    )

    _slot_width_emu, no_caption_height_emu = _block_box(no_caption)
    _slot_width_emu, captioned_height_emu = _block_box(with_caption)

    assert captioned_height_emu < no_caption_height_emu


def test_block_embedding_box_never_bleeds_past_the_bottom_margin(
    tmp_path: Path,
) -> None:
    """The returned box, stacked below the Block's own reserved space, must
    land at or above the bottom margin -- never past it."""
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    with ZipFile(master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        styles = ElementTree.fromstring(archive.read("word/styles.xml"))

    geometry = page_geometry_emu(document)
    _slot_width_emu, max_height_emu = block_embedding_box_emu(document, styles)

    assert max_height_emu <= geometry.usable_height_emu
    assert (
        geometry.top_margin_emu + max_height_emu
        <= geometry.page_height_emu - geometry.bottom_margin_emu
    )
