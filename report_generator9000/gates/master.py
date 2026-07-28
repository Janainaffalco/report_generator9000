"""Assertions that make a built Master safe to approve once for all reports."""

from __future__ import annotations

import re
from xml.etree import ElementTree

from ..docx_package import WORD_NS, DocxPackage
from .results import GateResult, result, violation


GATE = "master-build"

EXPECTED_TOKENS = frozenset(
    {
        "{{DEMANDA}}",
        "{{RAZAO_SOCIAL}}",
        "{{CNPJ}}",
        "{{ESPECIALISTA}}",
        "{{SOBRE_A_EMPRESA}}",
        "{{BRIEFING_INICIAL}}",
        "{{LISTA_DE_PAGINAS}}",
        "{{DATA_BACKUP}}",
        "{{PLANO_HOSPEDAGEM}}",
        "{{DOMINIO_PUBLICADO}}",
        "{{WP_ADMIN_URL}}",
        "{{EMAIL_CLIENTE}}",
        "{{LINK_CODIGO_FONTE}}",
        "{{LINK_GUIA_RAPIDO}}",
        "{{LINK_IDENTIDADE_VISUAL}}",
        "{{LINK_USUARIOS_SENHAS}}",
        "{{DATA_KICKOFF}}",
        "{{DATA_ENTREGA}}",
    }
)

BOILERPLATE_MEDIA = frozenset(
    {"word/media/image1.png", "word/media/image21.png"}
)

CANONICAL_HEADINGS = (
    (1, "BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO"),
    (2, "SOBRE A EMPRESA"),
    (2, "BRIEFING"),
    (1, "DESENVOLVIMENTO DE WEBSITE"),
    (2, "OBJETIVO"),
    (2, "ACESSOS E ENTREGAS"),
    (2, "HOSPEDAGEM E DADOS TÉCNICOS"),
    (2, "PLATAFORMA | WORDPRESS"),
    (2, "PLUGINS"),
    (2, "IDENTIDADE VISUAL"),
    (2, "PÁGINA HOME E SEÇÕES"),
    (2, "PAINEL DE CONFIGURAÇÃO WORDPRESS"),
    (2, "SEO"),
    (2, "ORIENTAÇÕES AO CLIENTE"),
    (1, "DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO"),
    (1, "TERMO DE CESSÃO DE DIREITOS"),
    (1, "REUNIÕES"),
)

MASTER_BLOCK_HEADINGS = (
    "PÁGINA HOME",
    "SEÇÃO PRODUTOS",
    "SEÇÃO VÍDEOS",
    "SEÇÃO CONTATO",
    "SEÇÃO SOBRE",
    "POLÍTICAS DE PRIVACIDADE",
    "CABEÇALHO",
    "RODAPÉ",
)

_TOKEN = re.compile(r"\{\{[^{}<>]{1,64}\}\}")
_CLIENT_MARKERS = (
    "argel",
    "64.525.744/0001-02",
    "christian albuquerque alonso",
    "010028/2025",
    "argelresistencia.com.br",
    "argelresistencias@hotmail.com",
    "ondviajar.com.br",
    "22/07/2026",
    "05/02/2026",
    "25/06/2026",
    "plano single",
)


def _is_boilerplate_link(target: str) -> bool:
    host = target.casefold().split("/", 3)[2] if "://" in target else ""
    return host in {
        "w3techs.com",
        "br.wordpress.org",
        "popularfx.com",
    }


def check_master_build(
    package: DocxPackage, source: DocxPackage | None = None
) -> GateResult:
    """Check token shape, residue, links, and media against an approved source."""
    violations = []
    seen: set[str] = set()

    for paragraph in package.paragraphs:
        for run in paragraph.runs:
            for token in _TOKEN.findall(run.text):
                seen.add(token)
                if run.text != token:
                    violations.append(
                        violation(
                            GATE,
                            "token-not-one-run",
                            f"{paragraph.source_part} p={paragraph.index}",
                            token,
                        )
                    )

    for token in sorted(EXPECTED_TOKENS - seen):
        violations.append(violation(GATE, "missing-token", "MASTER.docx", token))
    for token in sorted(seen - EXPECTED_TOKENS):
        violations.append(violation(GATE, "unexpected-token", "MASTER.docx", token))

    for part in package.parts:
        text = (part.text or "").casefold()
        for marker in _CLIENT_MARKERS:
            if marker in text:
                violations.append(
                    violation(GATE, "source-client-residue", part.name, marker)
                )

    for relationship in package.relationships:
        if relationship.external and not _is_boilerplate_link(relationship.target):
            violations.append(
                violation(
                    GATE,
                    "client-link-retained",
                    f"{relationship.source_part} {relationship.relationship_id}",
                    relationship.target,
                )
            )

    if source is not None:
        source_media = {item.part_name: item for item in source.media}
        for media in package.media:
            original = source_media.get(media.part_name)
            if (
                original is not None
                and media.part_name not in BOILERPLATE_MEDIA
                and media.sha256 == original.sha256
            ):
                violations.append(
                    violation(
                        GATE,
                        "source-client-media-retained",
                        media.part_name,
                        media.sha256,
                    )
                )

        for relationship in source.relationships:
            if relationship.external and not _is_boilerplate_link(relationship.target):
                if any(
                    item.external and item.target == relationship.target
                    for item in package.relationships
                ):
                    violations.append(
                        violation(
                            GATE,
                            "source-client-link-retained",
                            relationship.source_part,
                            relationship.target,
                        )
                    )

    part_text = {item.name: item.text for item in package.parts}
    required_xml = (
        "word/document.xml",
        "word/settings.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/fontTable.xml",
    )
    missing_xml = [name for name in required_xml if not part_text.get(name)]
    for name in missing_xml:
        violations.append(
            violation(GATE, "master-signoff-part-missing", name, "required")
        )
    if not missing_xml:
        w = f"{{{WORD_NS}}}"
        document = ElementTree.fromstring(part_text["word/document.xml"] or "")
        field_types = [
            item.get(f"{w}fldCharType")
            for item in document.iter(f"{w}fldChar")
        ]
        instructions = [
            item.text or "" for item in document.iter(f"{w}instrText")
        ]
        if field_types != ["begin", "separate", "end"] or instructions != [
            ' TOC \\o "1-2" \\h \\z \\u '
        ]:
            violations.append(
                violation(
                    GATE,
                    "invalid-toc-field",
                    "word/document.xml",
                    f"field-types={field_types!r}",
                )
            )
        headings = []
        for paragraph in document.iter(f"{w}p"):
            style = paragraph.find(f"{w}pPr/{w}pStyle")
            if style is None:
                continue
            style_id = style.get(f"{w}val")
            if style_id not in {"Heading1", "Heading2"}:
                continue
            text = "".join(
                node.text or "" for node in paragraph.iter(f"{w}t")
            )
            headings.append((int(style_id[-1]), text))
        if tuple(headings) != CANONICAL_HEADINGS:
            violations.append(
                violation(
                    GATE,
                    "noncanonical-heading-sequence",
                    "word/document.xml",
                    repr(headings),
                )
            )
        if tuple(headings) == CANONICAL_HEADINGS:
            stage_two_start = headings.index(
                (1, "DESENVOLVIMENTO DE WEBSITE")
            )
            stage_two_end = headings.index(
                (1, "DECLARAÇÃO DE RECEBIMENTO E FINALIZAÇÃO")
            )
            stage_two = headings[stage_two_start + 1 : stage_two_end]
            if len(stage_two) != 10 or stage_two[-1] != (
                2,
                "ORIENTAÇÕES AO CLIENTE",
            ):
                violations.append(
                    violation(
                        GATE,
                        "invalid-stage-two-numbering-range",
                        "word/document.xml",
                        "expected 2.1 through 2.10 ending "
                        "ORIENTAÇÕES AO CLIENTE",
                    )
                )
        body = document.find(f"{w}body")
        body_children = [] if body is None else list(body)
        page_area = next(
            (
                index
                for index, item in enumerate(body_children)
                if "".join(
                    node.text or "" for node in item.iter(f"{w}t")
                ).strip()
                == "PÁGINA HOME E SEÇÕES"
            ),
            None,
        )
        panel = next(
            (
                index
                for index, item in enumerate(body_children)
                if page_area is not None
                and index > page_area
                and "".join(
                    node.text or "" for node in item.iter(f"{w}t")
                ).strip()
                == "PAINEL DE CONFIGURAÇÃO WORDPRESS"
            ),
            None,
        )
        block_error = page_area is None or panel is None
        if not block_error:
            block_region = body_children[page_area + 1 : panel]
            block_error = len(block_region) != len(MASTER_BLOCK_HEADINGS) * 2
            if not block_error:
                for offset, expected in enumerate(MASTER_BLOCK_HEADINGS):
                    heading = block_region[offset * 2]
                    image = block_region[offset * 2 + 1]
                    text = "".join(
                        node.text or "" for node in heading.iter(f"{w}t")
                    ).strip()
                    properties = heading.find(f"{w}pPr")
                    keep = (
                        None
                        if properties is None
                        else properties.find(f"{w}keepNext")
                    )
                    spacing = (
                        None
                        if properties is None
                        else properties.find(f"{w}spacing")
                    )
                    style = (
                        None
                        if properties is None
                        else properties.find(f"{w}pStyle")
                    )
                    image_spacing = image.find(f"{w}pPr/{w}spacing")
                    block_error = block_error or any(
                        (
                            text != expected,
                            keep is None or keep.get(f"{w}val") != "true",
                            spacing is None
                            or spacing.get(f"{w}after") != "80",
                            style is not None
                            and style.get(f"{w}val")
                            in {"Heading1", "Heading2"},
                            image.find(f".//{w}drawing") is None,
                            image_spacing is None
                            or image_spacing.get(f"{w}before") != "0",
                        )
                    )
        stamp_count = sum(
            1
            for item in document.iter(f"{w}bookmarkStart")
            if item.get(f"{w}name") == "MASTER_BLOCK_STAMP"
        )
        if block_error or stamp_count != 1:
            violations.append(
                violation(
                    GATE,
                    "invalid-master-blocks",
                    "word/document.xml",
                    "expected eight two-paragraph bound Blocks and one stamp",
                )
            )

        settings = ElementTree.fromstring(part_text["word/settings.xml"] or "")
        update = settings.find(f"{w}updateFields")
        if update is None or update.get(f"{w}val") != "true":
            violations.append(
                violation(
                    GATE,
                    "field-update-disabled",
                    "word/settings.xml",
                    "updateFields must be true",
                )
            )
        styles = ElementTree.fromstring(part_text["word/styles.xml"] or "")
        for level in (1, 2):
            style = next(
                (
                    item
                    for item in styles.findall(f"{w}style")
                    if item.get(f"{w}styleId") == f"Heading{level}"
                ),
                None,
            )
            number_id = (
                None
                if style is None
                else style.find(f"{w}pPr/{w}numPr/{w}numId")
            )
            fonts = (
                None if style is None else style.find(f"{w}rPr/{w}rFonts")
            )
            if (
                number_id is None
                or number_id.get(f"{w}val") != "900"
                or fonts is None
                or fonts.get(f"{w}ascii") != "Montserrat"
            ):
                violations.append(
                    violation(
                        GATE,
                        "heading-style-not-linked",
                        f"word/styles.xml Heading{level}",
                        "Montserrat and numbering 900 required",
                    )
                )
        numbering = ElementTree.fromstring(
            part_text["word/numbering.xml"] or ""
        )
        abstract = next(
            (
                item
                for item in numbering.findall(f"{w}abstractNum")
                if item.get(f"{w}abstractNumId") == "900"
            ),
            None,
        )
        formats = (
            []
            if abstract is None
            else [
                item.find(f"{w}lvlText").get(f"{w}val")
                for item in abstract.findall(f"{w}lvl")
            ]
        )
        if formats != ["%1", "%1.%2"]:
            violations.append(
                violation(
                    GATE,
                    "invalid-heading-numbering",
                    "word/numbering.xml",
                    repr(formats),
                )
            )
        font_parts = [
            item.name
            for item in package.parts
            if item.name.startswith("word/fonts/montserrat-")
        ]
        if len(font_parts) != 5:
            violations.append(
                violation(
                    GATE,
                    "embedded-font-set-incomplete",
                    "word/fonts",
                    repr(font_parts),
                )
            )
        provenance = part_text.get(
            "customXml/montserrat-provenance.xml", ""
        ) or ""
        if 'origin="Boilerplate"' not in provenance:
            violations.append(
                violation(
                    GATE,
                    "font-provenance-missing",
                    "customXml/montserrat-provenance.xml",
                    "Boilerplate",
                )
            )

    return result(GATE, violations)
