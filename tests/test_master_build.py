from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

import pytest

from fixtures.docx_builder import RelationshipSpec, build_docx, paragraph, png_bytes

from report_generator9000.docx_package import open_docx_package
from report_generator9000.master import EXPECTED_TOKENS, build_master


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


def approved_source(path: Path) -> Path:
    return build_docx(
        path,
        paragraphs=[
            paragraph("SUMÁRIO"),
            paragraph("summary entry"),
            paragraph("ETAPA 1"),
            paragraph("BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO"),
            paragraph("SOBRE A EMPRESA"),
            paragraph("BRIEFING"),
            paragraph("DESENVOLVIMENTO DE WEBSITE"),
            paragraph("OBJETIVO"),
            paragraph("ACESSOS E ENTREGAS"),
            paragraph("IDENTIDADE VISUAL"),
            paragraph("HOSPEDAGEM E DADOS TÉCNICOS"),
            paragraph("PLATAFORMA | WORDPRESS"),
            paragraph("PLUGINS"),
            paragraph("IDENTIDADE VISUAL"),
            paragraph("PÁGINA HOME E SEÇÕES"),
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
        ],
        media={
            "media/image1.png": png_bytes(8, 8, blue=0xFF),
            "media/image2.png": png_bytes(16, 9, green=0xC0),
        },
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png"),
            RelationshipSpec(id="rIdImage2", target="media/image2.png"),
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
        ],
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
    assert "2.10 Indicadores14" in first.diff.read_text(encoding="utf-8")
    assert "A portal web" in first.diff.read_text(encoding="utf-8")


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
    assert settings.find(f"{W}updateFields").get(f"{W}val") == "true"
    assert fonts and all(
        any(item.get("Id") == f"rIdMontserrat{index}" for item in font_relationships)
        for index in range(5)
    )
    headings = {
        style.get(f"{W}styleId"): style.find(f"{W}name").get(f"{W}val")
        for style in styles.findall(f"{W}style")
        if style.get(f"{W}styleId") in {"Heading1", "Heading2"}
    }
    assert headings == {"Heading1": "Título 1", "Heading2": "Título 2"}
    assert heading_sequence(document) == EXPECTED_HEADINGS
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
        "setting",
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
