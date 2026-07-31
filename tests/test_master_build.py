from __future__ import annotations

import dataclasses
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

import pytest

from fixtures.docx_builder import RelationshipSpec, build_docx, paragraph, png_bytes

from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates.blocks import check_block_integrity
from report_generator9000.gates.master import MASTER_BLOCK_HEADINGS, check_master_build
from report_generator9000.master import (
    CLIENT_LOGO_PART,
    EXPECTED_TOKENS,
    build_master,
    clone_block_stamp,
)
from report_generator9000.run_context import RunContext
from report_generator9000.runs import PACKAGED_MASTER_PATH


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

EXPECTED_HEADINGS = [
    ("Heading1", "BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO"),
    ("Heading2", "SOBRE A EMPRESA"),
    ("Heading2", "BRIEFING"),
    ("Heading1", "DESENVOLVIMENTO DE WEBSITE"),
    ("Heading2", "OBJETIVO"),
    ("Heading2", "ACESSOS E ENTREGAS"),
    ("Heading2", "HOSPEDAGEM E DADOS TÉCNICOS"),
    ("Heading2", "PLATAFORMA | WORDPRESS"),
    ("Heading2", "PLUGINS"),
    ("Heading2", "IDENTIDADE VISUAL"),
    ("Heading2", "PÁGINA HOME E SEÇÕES"),
    ("Heading2", "PAINEL DE CONFIGURAÇÃO WORDPRESS"),
    ("Heading2", "SEO"),
    ("Heading2", "ORIENTAÇÕES AO CLIENTE"),
    ("Heading1", "DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO"),
    ("Heading1", "TERMO DE CESSÃO DE DIREITOS"),
    ("Heading1", "REUNIÕES"),
]


def heading_sequence(document: ElementTree.Element) -> list[tuple[str, str]]:
    sequence = []
    for paragraph in document.iter(f"{W}p"):
        style = paragraph.find(f"{W}pPr/{W}pStyle")
        if style is None or style.get(f"{W}val") not in {"Heading1", "Heading2"}:
            continue
        text = "".join(item.text or "" for item in paragraph.iter(f"{W}t"))
        sequence.append((style.get(f"{W}val"), text))
    return sequence


def numbered_headings(
    headings: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    section = 0
    subsection = 0
    numbered = []
    for style, title in headings:
        if style == "Heading1":
            section += 1
            subsection = 0
            numbered.append((str(section), title))
        else:
            subsection += 1
            numbered.append((f"{section}.{subsection}", title))
    return numbered


def _base_paragraphs() -> list:
    return [
            paragraph(image="rIdImage1", bookmark=(9000, "ExistingBookmark")),
            paragraph("SUMÁRIO"),
            paragraph("summary entry"),
            paragraph("ETAPA 1"),
            paragraph("BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO"),
            paragraph("SOBRE A EMPRESA", font="Montserrat Medium"),
            paragraph("BRIEFING", font="Montserrat"),
            paragraph("DESENVOLVIMENTO DE WEBSITE"),
            paragraph("OBJETIVO"),
            paragraph("ACESSOS E ENTREGAS"),
            paragraph("IDENTIDADE VISUAL"),
            paragraph("HOSPEDAGEM E DADOS TÉCNICOS"),
            paragraph("PLATAFORMA | WORDPRESS"),
            paragraph("PLUGINS"),
            paragraph("IDENTIDADE VISUAL"),
            paragraph("LOGO"),
            paragraph(
                image="rIdImage2",
                extent=(1_271_270, 1_362_075),
            ),
            paragraph("PALETA DE CORES"),
            paragraph(
                image="rIdImage3",
                extent=(4_653_280, 953_135),
            ),
            paragraph("PÁGINA HOME E SEÇÕES"),
            paragraph(),
            paragraph("PÁGINA HOME"),
            paragraph(),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("SEÇÃO PRODUTOS"),
            paragraph(),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("SEÇÃO VÍDEOS"),
            paragraph(),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("SEÇÃO CONTATO"),
            paragraph(image="rIdImage4"),
            paragraph("SEÇÃO SOBRE"),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("POLÍTICAS DE PRIVACIDADE"),
            paragraph(),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("CABEÇALHO"),
            paragraph(),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("RODAPÉ"),
            paragraph(),
            paragraph(image="rIdImage4"),
            paragraph(),
            paragraph("PAINEL DE CONFIGURAÇÃO WORDPRESS"),
            paragraph("PAINEL DE CONFIGURAÇÃO WORDPRESS"),
            paragraph("SEO"),
            paragraph("ORIENTAÇÕES AO CLIENTE"),
            paragraph("DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO"),
            paragraph("TERMO DE CESSÃO DE DIREITOS"),
            paragraph("REUNIÕES"),
            paragraph("demanda 010028/2025"),
            paragraph("ARGEL RESISTENCIAS ELETRICAS LTDA"),
            paragraph("64.525.744/0001-02"),
            paragraph("Christian Albuquerque Alonso"),
            paragraph(
                "A ARGEL Resistências Elétricas LTDA é especializada na "
                "fabricação e comercialização de resistências elétricas."
            ),
            paragraph("O responsável pela ARGEL preparou o site."),
            paragraph("A estrutura do site contempla as páginas Home."),
            paragraph("Backup do código fonte – última versão (data 22/07/2026)"),
            paragraph("Assinatura: PLANO SINGLE"),
            paragraph("Domínio: argelresistencia.com.br"),
            paragraph("https://onhttps://argelresistencia.com.br/wp-admin/", hyperlink="rId25"),
            paragraph("Disponibilizamos links para download.", hyperlink="rId2"),
            paragraph("Ressaltamos a importância de alterar as senhas após entrega, Além de realizar o download no e-mail argelresistencias@hotmail.com."),
            paragraph("O código fonte do website desenvolvido para o cliente ARGEL RESISTENCIAS ELETRICAS LTDA| CNPJ: 64.525.744/0001-02 foi cedido por meio do link: https://drive.google.com/drive/folders/source"),
            paragraph("Guia Rápido -https://drive.google.com/drive/folders/guide"),
            paragraph("ID Visual - https://drive.google.com/drive/folders/visual"),
            paragraph("Usuários e Senhas - https://drive.google.com/drive/folders/users"),
            paragraph("KickOff em 05/02/2026"),
            paragraph("Entrega em 25/06/2026"),
            paragraph("SMTP Mailer – Protocolo de envoi de e-mail"),
            paragraph("Por segurança, o tempo de bloqueia aumenta para 24 horas."),
            paragraph("opções, referentes as ferramentas do WordPress."),
            paragraph("funcionalidades que foge do objetivo do presente documento."),
            paragraph('No menu "Plugins", verifique as atualizações disponíveis. ".'),
            paragraph("2.10 Indicadores14"),
            paragraph("A portal web é o principal canal e funcionam como um hub."),
    ]


def _base_media() -> dict:
    return {
        "media/image1.png": png_bytes(8, 8, blue=0xFF),
        "media/image2.png": png_bytes(158, 166, green=0xC0),
        "media/image3.png": png_bytes(978, 179, red=0x80, green=0xC0),
        "media/image4.png": png_bytes(16, 9, green=0xC0),
    }


def _base_relationships() -> list:
    return [
        RelationshipSpec(id="rIdImage1", target="media/image1.png"),
        RelationshipSpec(id="rIdImage2", target="media/image2.png"),
        RelationshipSpec(id="rIdImage3", target="media/image3.png"),
        RelationshipSpec(id="rIdImage4", target="media/image4.png"),
        RelationshipSpec(
            id="rId25",
            target="https://ondviajar.com.br/wp-admin/",
            kind="hyperlink",
            external=True,
        ),
        RelationshipSpec(
            id="rId2",
            target="https://drive.google.com/drive/folders/downloads",
            kind="hyperlink",
            external=True,
        ),
    ]


def approved_source(path: Path) -> Path:
    return build_docx(
        path,
        paragraphs=_base_paragraphs(),
        media=_base_media(),
        relationships=_base_relationships(),
    )


def approved_source_with_defects(path: Path) -> Path:
    """A variant carrying the specific source defects C1, C4, E1 and E2 fix."""
    paragraphs = _base_paragraphs()
    for index, spec in enumerate(paragraphs):
        if spec.runs == ("SOBRE A EMPRESA",):
            paragraphs[index] = dataclasses.replace(
                spec, direct_numbering=(1, 3), dot_leader_tab=True
            )
            break
    else:
        raise AssertionError("SOBRE A EMPRESA paragraph not found")

    heading_index = next(
        index for index, spec in enumerate(paragraphs) if spec.runs == ("CABEÇALHO",)
    )
    image_index = next(
        index
        for index, spec in enumerate(paragraphs[heading_index:], heading_index)
        if spec.image is not None
    )
    paragraphs[image_index] = dataclasses.replace(
        paragraphs[image_index], extent=(6483096, 548640)
    )

    paragraphs.append(paragraph("Ficha Técnica SEBRAETEC 4.0 – Pág. 3"))

    return build_docx(
        path,
        paragraphs=paragraphs,
        media=_base_media(),
        relationships=_base_relationships(),
    )


def replace_document_xml(
    source: Path, target: Path, document: ElementTree.Element
) -> None:
    with ZipFile(source) as archive:
        parts = [(item, archive.read(item.filename)) for item in archive.infolist()]
    replacement = ElementTree.tostring(
        document, encoding="utf-8", xml_declaration=True
    )
    with ZipFile(target, "w") as archive:
        for item, content in parts:
            archive.writestr(
                item,
                replacement if item.filename == "word/document.xml" else content,
            )


def test_master_build_is_reproducible_and_auditable(tmp_path: Path) -> None:
    source = approved_source(tmp_path / "approved.docx")
    first = build_master(source, tmp_path / "one")
    second = build_master(source, tmp_path / "two")

    assert first.master.read_bytes() == second.master.read_bytes()
    package = open_docx_package(first.master)
    assert EXPECTED_TOKENS <= {run.text for item in package.paragraphs for run in item.runs}
    assert all(
        run.text == token
        for item in package.paragraphs
        for run in item.runs
        for token in EXPECTED_TOKENS
        if token in run.text
    )
    assert all("argel" not in (part.text or "").casefold() for part in package.parts)
    assert all("ondviajar" not in relation.target for relation in package.relationships)
    assert "word/media/image2.png" in first.diff.read_text(encoding="utf-8")
    assert "rId2: Disponibilizamos links para download." in first.diff.read_text(encoding="utf-8")
    audit = first.diff.read_text(encoding="utf-8")
    assert "orphaned hand-typed `2.10 Indicadores14` entry was deliberately" in audit
    assert "2.10 ORIENTAÇÕES AO CLIENTE" in audit
    assert "A portal web" in first.diff.read_text(encoding="utf-8")


def test_versioned_master_is_present_and_passes_its_standalone_gate() -> None:
    package = open_docx_package(PACKAGED_MASTER_PATH)

    assert check_master_build(package).passed


def test_master_contains_a_two_level_toc_embedded_font_and_named_headings(
    tmp_path: Path,
) -> None:
    built = build_master(approved_source(tmp_path / "approved.docx"), tmp_path / "out")

    with ZipFile(built.master) as package:
        document = ElementTree.fromstring(package.read("word/document.xml"))
        settings = ElementTree.fromstring(package.read("word/settings.xml"))
        styles = ElementTree.fromstring(package.read("word/styles.xml"))
        numbering = ElementTree.fromstring(package.read("word/numbering.xml"))
        fonts = package.read("word/fonts/montserrat-0.odttf")
        font_relationships = ElementTree.fromstring(
            package.read("word/_rels/fontTable.xml.rels")
        )
        document_relationships = ElementTree.fromstring(
            package.read("word/_rels/document.xml.rels")
        )
        content_types = package.read("[Content_Types].xml").decode("utf-8")
        license_text = package.read("customXml/Montserrat-OFL.txt").decode("utf-8")
        provenance = package.read(
            "customXml/montserrat-provenance.xml"
        ).decode("utf-8")

    field_types = [
        item.get(f"{W}fldCharType") for item in document.iter(f"{W}fldChar")
    ]
    instructions = [
        item.text or "" for item in document.iter(f"{W}instrText")
    ]
    assert field_types == ["begin", "separate", "end"]
    assert instructions == [' TOC \\o "1-2" \\h \\z \\u ']
    begin_field = next(
        item for item in document.iter(f"{W}fldChar")
        if item.get(f"{W}fldCharType") == "begin"
    )
    assert begin_field.get(f"{W}dirty") == "true"
    assert settings.find(f"{W}updateFields") is None
    assert fonts and all(
        any(item.get("Id") == f"rIdMontserrat{index}" for item in font_relationships)
        for index in range(2)
    )
    headings = {
        style.get(f"{W}styleId"): style.find(f"{W}name").get(f"{W}val")
        for style in styles.findall(f"{W}style")
        if style.get(f"{W}styleId") in {"Heading1", "Heading2"}
    }
    assert headings == {"Heading1": "Título 1", "Heading2": "Título 2"}
    assert heading_sequence(document) == EXPECTED_HEADINGS
    numbers = numbered_headings(heading_sequence(document))
    assert ("2.10", "ORIENTAÇÕES AO CLIENTE") in numbers
    assert not any(number == "2.11" for number, _title in numbers)
    for level in (0, 1):
        style = next(
            item
            for item in styles.findall(f"{W}style")
            if item.get(f"{W}styleId") == f"Heading{level + 1}"
        )
        assert style.find(f"{W}pPr/{W}numPr/{W}ilvl").get(f"{W}val") == str(level)
        assert style.find(f"{W}pPr/{W}numPr/{W}numId").get(f"{W}val") == "900"
    abstract = next(
        item
        for item in numbering.findall(f"{W}abstractNum")
        if item.get(f"{W}abstractNumId") == "900"
    )
    assert [
        item.find(f"{W}lvlText").get(f"{W}val")
        for item in abstract.findall(f"{W}lvl")
    ] == ["%1", "%1.%2"]
    relation_targets = {
        item.get("Target") for item in document_relationships.findall(f"{REL}Relationship")
    }
    assert {
        "settings.xml",
        "styles.xml",
        "numbering.xml",
        "fontTable.xml",
        "../customXml/montserrat-provenance.xml",
    } <= relation_targets
    assert all(
        f'/word/{part}.xml' in content_types
        for part in ("settings", "styles", "numbering", "fontTable")
    )
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    assert 'origin="Boilerplate"' in provenance
    assert built.validation.passed
    audit = built.diff.read_text(encoding="utf-8")
    for record in (
        "TOC field added",
        "heading assigned",
        "numbering",
        "style updated",
        "Boilerplate font embedded",
        "Boilerplate provenance added",
    ):
        assert record in audit


def test_real_source_uses_the_exact_canonical_heading_sequence(
    tmp_path: Path,
) -> None:
    sources = list(Path(__file__).resolve().parent.parent.glob("*ARGEL*.docx"))
    if not sources:
        pytest.skip("approved source binary is intentionally not tracked")
    built = build_master(sources[0], tmp_path / "real")
    with ZipFile(built.master) as package:
        document = ElementTree.fromstring(package.read("word/document.xml"))
    assert heading_sequence(document) == EXPECTED_HEADINGS
    assert built.validation.passed


def test_master_blocks_are_two_paragraph_bound_and_cloneable(
    tmp_path: Path,
) -> None:
    built = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "out"
    )
    package = open_docx_package(built.master)
    assert check_block_integrity(
        package, RunContext(blocks=MASTER_BLOCK_HEADINGS)
    ).passed

    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    children = list(body)
    start = next(
        index
        for index, item in enumerate(children)
        if "".join(node.text or "" for node in item.iter(f"{W}t")).strip()
        == "PÁGINA HOME E SEÇÕES"
    )
    end = next(
        index
        for index, item in enumerate(children[start + 1 :], start + 1)
        if "".join(node.text or "" for node in item.iter(f"{W}t")).strip()
        == "PAINEL DE CONFIGURAÇÃO WORDPRESS"
    )
    region = children[start + 1 : end]
    assert len(region) == len(MASTER_BLOCK_HEADINGS) * 2
    for offset, expected in enumerate(MASTER_BLOCK_HEADINGS):
        heading, image = region[offset * 2 : offset * 2 + 2]
        assert (
            "".join(node.text or "" for node in heading.iter(f"{W}t")).strip()
            == expected
        )
        assert heading.find(f"{W}pPr/{W}keepNext").get(f"{W}val") == "true"
        assert heading.find(f"{W}pPr/{W}spacing").get(f"{W}after") == "80"
        assert image.find(f"{W}pPr/{W}spacing").get(f"{W}before") == "0"
        assert image.find(f".//{W}drawing") is not None
        style = heading.find(f"{W}pPr/{W}pStyle")
        assert style is None or style.get(f"{W}val") not in {
            "Heading1",
            "Heading2",
        }


def test_declaration_closes_with_a_signature_line_and_one_page_break(
    tmp_path: Path,
) -> None:
    """The typed blank paragraphs that used to pad the declaration onto the
    next page are what produced the stray blank page; a signature line plus a
    single page break says the same thing and cannot grow one."""
    built = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "out"
    )
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    children = list(body)

    def text_of(paragraph: ElementTree.Element) -> str:
        return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))

    start = next(
        index
        for index, item in enumerate(children)
        if text_of(item).strip() == "DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO"
    )
    end = next(
        index
        for index, item in enumerate(children[start + 1 :], start + 1)
        if text_of(item).strip() == "TERMO DE CESSÃO DE DIREITOS"
    )
    section = children[start + 1 : end]

    assert [
        item
        for item in section
        if not text_of(item).strip()
        and item.find(f".//{W}br") is None
        and item.find(f"{W}pPr/{W}pBdr") is None
    ] == []
    rule, caption, page_break = section[-3:]
    assert (
        rule.find(f"{W}pPr/{W}pBdr/{W}bottom").get(f"{W}val") == "single"
    )
    assert not text_of(rule)
    assert rule.find(f"{W}pPr/{W}jc").get(f"{W}val") == "center"
    assert [run.findtext(f"{W}t") for run in caption.findall(f"{W}r")] == [
        "{{RAZAO_SOCIAL}}",
        "Assinatura do representante legal",
    ]
    first_run, second_run = caption.findall(f"{W}r")
    assert first_run.find(f"{W}br") is None
    assert second_run.find(f"{W}br") is not None
    assert caption.find(f"{W}pPr/{W}keepLines") is not None
    assert (
        page_break.find(f".//{W}br").get(f"{W}type") == "page"
    )
    assert (
        len([item for item in section if item.find(f".//{W}br[@{W}type='page']") is not None])
        == 1
    )
    assert built.validation.passed
    assert "signature line added" in built.diff.read_text(encoding="utf-8")


def test_typed_spacers_before_an_existing_page_break_are_replaced(
    tmp_path: Path,
) -> None:
    """The approved source pads the declaration with seven empty paragraphs
    ahead of its page break; the signature line takes their place and the
    source's own break is kept rather than doubled."""
    paragraphs = _base_paragraphs()
    index = next(
        position
        for position, spec in enumerate(paragraphs)
        if spec.runs == ("DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO",)
    )
    paragraphs[index + 1 : index + 1] = [
        paragraph("O representante legal declara ter recebido o projeto."),
        *(paragraph() for _ in range(7)),
        paragraph(page_break=True),
    ]
    source = build_docx(
        tmp_path / "padded.docx",
        paragraphs=paragraphs,
        media=_base_media(),
        relationships=_base_relationships(),
    )

    built = build_master(source, tmp_path / "out")

    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    children = list(body)

    def text_of(item: ElementTree.Element) -> str:
        return "".join(node.text or "" for node in item.iter(f"{W}t"))

    start = next(
        position
        for position, item in enumerate(children)
        if text_of(item).strip() == "DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO"
    )
    end = next(
        position
        for position, item in enumerate(children[start + 1 :], start + 1)
        if text_of(item).strip() == "TERMO DE CESSÃO DE DIREITOS"
    )
    section = children[start + 1 : end]

    assert [text_of(item) for item in section] == [
        "O representante legal declara ter recebido o projeto.",
        "",
        "{{RAZAO_SOCIAL}}Assinatura do representante legal",
        "",
    ]
    assert (
        len(
            [
                item
                for item in section
                if item.find(f".//{W}br[@{W}type='page']") is not None
            ]
        )
        == 1
    )
    assert built.validation.passed


def test_palette_image_is_followed_by_a_single_page_break_and_no_spacers(
    tmp_path: Path,
) -> None:
    """Issue #37 item 3: the colour palette image must be followed by exactly
    one page break and no typed spacer paragraphs, the same treatment given
    to the declaration's closing page and for the same reason — any reflow
    above a run of blank paragraphs can spill them onto a page carrying
    nothing but the running header."""
    built = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "out"
    )
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    children = list(body)

    def text_of(item: ElementTree.Element) -> str:
        return "".join(node.text or "" for node in item.iter(f"{W}t"))

    heading = next(
        index
        for index, item in enumerate(children)
        if text_of(item).strip() == "PALETA DE CORES"
    )
    image = next(
        index
        for index, item in enumerate(children[heading + 1 :], heading + 1)
        if item.find(f".//{W}drawing") is not None
    )
    next_heading = next(
        index
        for index, item in enumerate(children[image + 1 :], image + 1)
        if item.find(f"{W}pPr/{W}pStyle") is not None
        and item.find(f"{W}pPr/{W}pStyle").get(f"{W}val")
        in {"Heading1", "Heading2"}
    )
    section = children[image + 1 : next_heading]

    assert [
        item
        for item in section
        if not text_of(item).strip() and item.find(f".//{W}br") is None
    ] == []
    page_breaks = [
        item
        for item in section
        if item.find(f".//{W}br[@{W}type='page']") is not None
    ]
    assert len(page_breaks) == 1
    assert built.validation.passed


def test_palette_spacers_before_the_next_section_are_replaced(
    tmp_path: Path,
) -> None:
    """The approved source pads the palette with seven empty paragraphs and
    no explicit break at all; master-build must not merely delete them but
    must leave exactly one page break behind, or the next section reflows
    onto whatever page the palette image lands on."""
    paragraphs = _base_paragraphs()
    index = next(
        position
        for position, spec in enumerate(paragraphs)
        if spec.image is not None and spec.extent == (4_653_280, 953_135)
    )
    paragraphs[index + 1 : index + 1] = [paragraph() for _ in range(7)]
    source = build_docx(
        tmp_path / "padded.docx",
        paragraphs=paragraphs,
        media=_base_media(),
        relationships=_base_relationships(),
    )

    built = build_master(source, tmp_path / "out")

    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    children = list(body)

    def text_of(item: ElementTree.Element) -> str:
        return "".join(node.text or "" for node in item.iter(f"{W}t"))

    heading = next(
        position
        for position, item in enumerate(children)
        if text_of(item).strip() == "PALETA DE CORES"
    )
    image = next(
        position
        for position, item in enumerate(children[heading + 1 :], heading + 1)
        if item.find(f".//{W}drawing") is not None
    )
    next_heading = next(
        position
        for position, item in enumerate(children[image + 1 :], image + 1)
        if item.find(f"{W}pPr/{W}pStyle") is not None
        and item.find(f"{W}pPr/{W}pStyle").get(f"{W}val")
        in {"Heading1", "Heading2"}
    )
    section = children[image + 1 : next_heading]

    assert [
        item
        for item in section
        if not text_of(item).strip() and item.find(f".//{W}br") is None
    ] == []
    page_breaks = [
        item
        for item in section
        if item.find(f".//{W}br[@{W}type='page']") is not None
    ]
    assert len(page_breaks) == 1
    assert built.validation.passed


def test_shipped_master_declaration_and_palette_carry_no_header_only_pages() -> None:
    """The signed-off Master is a versioned runtime asset (ADR 0003) that the
    pipeline clones directly — the pipeline never runs master-build again, so
    a stale committed asset silently ships whatever spacer/page-break shape
    it happened to have when it was last regenerated, even if every other
    master-build test (which builds a fresh candidate from a fixture source)
    is green. This is the regression guard for issue #37 items 2 and 3: it
    opens the exact asset the app ships and re-checks, directly against
    word/document.xml, the two known mechanisms that produced a page with
    nothing on it but the running header — the declaration's closing spacers
    and the palette's trailing spacers. It does not attempt to prove no page
    anywhere in the document is header-only in general; that would require
    layout, which this repo deliberately keeps out of gates that only see
    XML."""
    with ZipFile(PACKAGED_MASTER_PATH) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    children = list(body)

    def text_of(item: ElementTree.Element) -> str:
        return "".join(node.text or "" for node in item.iter(f"{W}t"))

    def is_blank_spacer(item: ElementTree.Element) -> bool:
        # Mirrors master._is_blank_spacer, including its pBdr exclusion: the
        # signature rule paragraph has no text of its own either, but it is
        # a deliberate ruled line, not a typed spacer.
        return (
            item.tag == f"{W}p"
            and not text_of(item).strip()
            and item.find(f".//{W}drawing") is None
            and item.find(f".//{W}br") is None
            and item.find(f"{W}pPr/{W}sectPr") is None
            and item.find(f"{W}pPr/{W}pBdr") is None
        )

    # Declaration: a signature line, no spacers, exactly one page break
    # before TERMO DE CESSÃO DE DIREITOS.
    declaration = next(
        index
        for index, item in enumerate(children)
        if text_of(item).strip() == "DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO"
    )
    termo = next(
        index
        for index, item in enumerate(children[declaration + 1 :], declaration + 1)
        if text_of(item).strip() == "TERMO DE CESSÃO DE DIREITOS"
    )
    declaration_section = children[declaration + 1 : termo]
    assert not any(is_blank_spacer(item) for item in declaration_section)
    assert "Assinatura do representante legal" in "".join(
        text_of(item) for item in declaration_section
    )
    assert (
        len(
            [
                item
                for item in declaration_section
                if item.find(f".//{W}br[@{W}type='page']") is not None
            ]
        )
        == 1
    )

    # Palette: no spacers, exactly one page break before the next section.
    palette_heading = next(
        index
        for index, item in enumerate(children)
        if text_of(item).strip() == "PALETA DE CORES"
    )
    palette_image = next(
        index
        for index, item in enumerate(
            children[palette_heading + 1 :], palette_heading + 1
        )
        if item.find(f".//{W}drawing") is not None
    )
    next_heading = next(
        index
        for index, item in enumerate(
            children[palette_image + 1 :], palette_image + 1
        )
        if item.find(f"{W}pPr/{W}pStyle") is not None
        and item.find(f"{W}pPr/{W}pStyle").get(f"{W}val")
        in {"Heading1", "Heading2"}
    )
    palette_section = children[palette_image + 1 : next_heading]
    assert not any(is_blank_spacer(item) for item in palette_section)
    assert (
        len(
            [
                item
                for item in palette_section
                if item.find(f".//{W}br[@{W}type='page']") is not None
            ]
        )
        == 1
    )


def test_master_reuses_the_dedicated_logo_section_without_a_briefing_box(
    tmp_path: Path,
) -> None:
    built = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "out"
    )
    package = open_docx_package(built.master)
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(
            archive.read("word/document.xml")
        )
    slots = [
        slot for slot in package.slots if slot.media_part == CLIENT_LOGO_PART
    ]

    assert len(slots) == 1
    logo_slot = slots[0]
    preceding = [
        paragraph.text.strip()
        for paragraph in package.paragraphs
        if paragraph.source_part == logo_slot.source_part
        and paragraph.index < logo_slot.paragraph_index
        and paragraph.text.strip()
    ]
    assert preceding[-1] == "LOGO"
    assert logo_slot.width_emu == 1_271_270
    assert logo_slot.height_emu == 1_362_075
    briefing = next(
        paragraph
        for paragraph in package.paragraphs
        if paragraph.text.strip()
        == "BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO"
    )
    assert not any(
        slot.paragraph_index == briefing.index + 1
        for slot in package.slots
    )
    assert "word/media/client-logo.png" not in {
        media.part_name for media in package.media
    }
    assert built.validation.passed

    cloned_heading, cloned_image = clone_block_stamp(
        document, "SEÇÃO CLONADA", "rIdClone"
    )
    assert "".join(
        node.text or "" for node in cloned_heading.iter(f"{W}t")
    ) == "SEÇÃO CLONADA"
    assert cloned_heading.find(f"{W}pPr/{W}keepNext") is not None
    assert cloned_image.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    ).get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    ) == "rIdClone"
    assert not list(cloned_heading.iter(f"{W}bookmarkStart"))
    assert not list(cloned_image.iter(f"{W}bookmarkEnd"))
    second_heading, second_image = clone_block_stamp(
        document, "SEÇÃO CLONADA 2", "rIdClone2"
    )
    assert "".join(
        node.text or "" for node in second_heading.iter(f"{W}t")
    ) == "SEÇÃO CLONADA 2"
    assert second_image.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    ).get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    ) == "rIdClone2"
    doc_ids = [
        item.get("id")
        for item in document.iter(
            "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
        )
    ]
    picture_ids = [
        item.get("id")
        for item in document.iter(
            "{http://schemas.openxmlformats.org/drawingml/2006/picture}cNvPr"
        )
    ]
    assert len(doc_ids) == len(set(doc_ids))
    assert len(picture_ids) == len(set(picture_ids))
    for local_name in ("anchorId", "editId"):
        values = [
            value
            for item in document.iter()
            for attribute, value in item.attrib.items()
            if attribute.rsplit("}", 1)[-1] == local_name
        ]
        assert len(values) == len(set(values))
    assert cloned_image is not second_image
    stamp = next(
        item
        for item in document.iter(f"{W}bookmarkStart")
        if item.get(f"{W}name") == "MASTER_BLOCK_STAMP"
    )
    assert stamp.get(f"{W}id") == "9001"


def test_master_gate_rejects_a_stamp_without_its_matching_end(
    tmp_path: Path,
) -> None:
    built = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "out"
    )
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    stamp = next(
        item
        for item in document.iter(f"{W}bookmarkStart")
        if item.get(f"{W}name") == "MASTER_BLOCK_STAMP"
    )
    stamp_id = stamp.get(f"{W}id")
    for parent in document.iter():
        matching_end = next(
            (
                child
                for child in list(parent)
                if child.tag == f"{W}bookmarkEnd"
                and child.get(f"{W}id") == stamp_id
            ),
            None,
        )
        if matching_end is not None:
            parent.remove(matching_end)
            break
    malformed = tmp_path / "malformed-stamp.docx"
    replace_document_xml(built.master, malformed, document)

    result = check_master_build(open_docx_package(malformed))

    assert any(
        item.rule == "invalid-master-blocks" for item in result.violations
    )


def test_direct_heading_numbering_and_dot_leader_tabs_are_stripped(
    tmp_path: Path,
) -> None:
    """C1/C4: a direct numPr and a leftover dot-leader tab never survive onto
    a canonical Heading1/Heading2 paragraph, so numId 900 actually applies."""
    built = build_master(
        approved_source_with_defects(tmp_path / "approved.docx"), tmp_path / "out"
    )
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    heading = next(
        paragraph
        for paragraph in document.iter(f"{W}p")
        if "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
        == "SOBRE A EMPRESA"
    )
    style = heading.find(f"{W}pPr/{W}pStyle")
    assert style is not None and style.get(f"{W}val") == "Heading2"
    assert heading.find(f"{W}pPr/{W}numPr") is None
    assert not [
        tab
        for tab in heading.findall(f"{W}pPr/{W}tabs/{W}tab")
        if tab.get(f"{W}leader")
    ]
    assert built.validation.passed


def test_oversized_block_image_is_scaled_to_the_text_column(
    tmp_path: Path,
) -> None:
    """E2: a Block image wider than the section's text column is scaled down,
    preserving aspect ratio, on both wp:extent and the sibling a:ext."""
    built = build_master(
        approved_source_with_defects(tmp_path / "approved.docx"), tmp_path / "out"
    )
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = list(document.iter(f"{W}p"))
    heading_index = next(
        index
        for index, paragraph in enumerate(paragraphs)
        if "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
        == "CABEÇALHO"
    )
    image = paragraphs[heading_index + 1]
    extent = image.find(f".//{{{'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}}}extent")
    section_properties = document.find(f"{W}body/{W}sectPr")
    page_width = int(section_properties.find(f"{W}pgSz").get(f"{W}w"))
    margins = section_properties.find(f"{W}pgMar")
    column_width_emu = (
        page_width
        - int(margins.get(f"{W}left"))
        - int(margins.get(f"{W}right"))
    ) * 635
    original_cx, original_cy = 6483096, 548640
    expected_cx = column_width_emu
    expected_cy = round(original_cy * (column_width_emu / original_cx))
    assert int(extent.get("cx")) == expected_cx
    assert int(extent.get("cy")) == expected_cy
    assert int(extent.get("cx")) <= column_width_emu
    drawing_ns_ext = image.find(
        f".//{{{'http://schemas.openxmlformats.org/drawingml/2006/main'}}}ext"
    )
    assert int(drawing_ns_ext.get("cx")) == expected_cx
    assert int(drawing_ns_ext.get("cy")) == expected_cy
    assert built.validation.passed


def test_ficha_tecnica_citation_is_restyled_not_removed(tmp_path: Path) -> None:
    """E1: the Ficha Técnica citation is kept (it cites the SEBRAETEC spec, not
    this document's pagination) but restyled so it cannot be misread as a
    page counter, per owner ruling."""
    built = build_master(
        approved_source_with_defects(tmp_path / "approved.docx"), tmp_path / "out"
    )
    with ZipFile(built.master) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    citation = next(
        paragraph
        for paragraph in document.iter(f"{W}p")
        if "".join(node.text or "" for node in paragraph.iter(f"{W}t")).strip()
        == "Fonte: Ficha Técnica SEBRAETEC 4.0, p. 3"
    )
    assert "– Pág. 3" not in "".join(
        node.text or "" for node in citation.iter(f"{W}t")
    )
    run_properties = citation.find(f"{W}r/{W}rPr")
    assert run_properties.find(f"{W}i") is not None
    size = run_properties.find(f"{W}sz")
    assert size is not None and int(size.get(f"{W}val")) < 22
    assert built.validation.passed


def test_gate_rejects_an_unresolvable_ignorable_prefix(tmp_path: Path) -> None:
    """A0: an mc:Ignorable token whose prefix has no matching xmlns declaration
    is the exact defect that made LibreOffice and Word refuse the Master."""
    relationships_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{W[1:-1]}" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'mc:Ignorable="w15"><w:body><w:p/></w:body></w:document>'
    ).encode("utf-8")
    broken = tmp_path / "broken.docx"
    with ZipFile(broken, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr(
            "word/_rels/document.xml.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{relationships_ns}"/>',
        )
        archive.writestr(
            "_rels/.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{relationships_ns}"/>',
        )
        archive.writestr(
            "[Content_Types].xml",
            f'<?xml version="1.0"?><Types xmlns="{content_types_ns}"/>',
        )

    result = check_master_build(open_docx_package(broken))

    assert any(
        item.rule == "unresolvable-ignorable-prefix" for item in result.violations
    )
