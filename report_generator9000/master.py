"""Build the client-neutral Master from the approved filled source DOCX."""

from __future__ import annotations

import base64
import binascii
import hashlib
import posixpath
import re
import struct
import uuid
import zlib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .docx_package import (
    OFFICE_REL_NS,
    WORD_NS,
    DocxPackage,
    open_docx_package,
)
from .gates.master import (
    BOILERPLATE_MEDIA,
    CANONICAL_HEADINGS,
    EXPECTED_TOKENS,
    check_master_build,
)
from .gates.results import GateResult


RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
W = f"{{{WORD_NS}}}"
R = f"{{{OFFICE_REL_NS}}}"
XML = "{http://www.w3.org/XML/1998/namespace}"
_TOKEN = re.compile(r"(\{\{[^{}<>]{1,64}\}\})")
_FONT_KEY = "6D5E55E7-46BF-4B17-9DCE-422D31C5A72D"

for _prefix, _namespace in (("w", WORD_NS), ("r", OFFICE_REL_NS)):
    ElementTree.register_namespace(_prefix, _namespace)


@dataclass(frozen=True)
class MasterBuild:
    master: Path
    diff: Path
    validation: GateResult


class MasterBuildError(ValueError):
    """The source could not be transformed into a safe Master."""


@dataclass(frozen=True)
class _Change:
    category: str
    artifact: str
    before: str
    after: str


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(item.text or "" for item in paragraph.iter(f"{W}t"))


def _segments(text: str) -> tuple[str, ...]:
    return tuple(item for item in _TOKEN.split(text) if item)


def _run_with_text(template: ElementTree.Element, text: str) -> ElementTree.Element:
    run = deepcopy(template)
    for child in list(run):
        if child.tag != f"{W}rPr":
            run.remove(child)
    node = ElementTree.SubElement(run, f"{W}t")
    if text[:1].isspace() or text[-1:].isspace():
        node.set(f"{XML}space", "preserve")
    node.text = text
    return run


def _replace_paragraph(
    paragraph: ElementTree.Element, replacement: str
) -> None:
    template = paragraph.find(f".//{W}r")
    if template is None:
        template = ElementTree.Element(f"{W}r")
    index = 1 if paragraph.find(f"{W}pPr") is not None else 0
    for child in list(paragraph):
        if child.tag in {f"{W}r", f"{W}hyperlink"}:
            paragraph.remove(child)
    for offset, segment in enumerate(_segments(replacement)):
        paragraph.insert(index + offset, _run_with_text(template, segment))


def _source_replacement(text: str) -> str | None:
    exact = {
        "demanda 010028/2025": "demanda {{DEMANDA}}",
        "ARGEL RESISTENCIAS ELETRICAS LTDA": "{{RAZAO_SOCIAL}}",
        "64.525.744/0001-02": "{{CNPJ}}",
        "Christian Albuquerque Alonso": "{{ESPECIALISTA}}",
        "Backup do código fonte – última versão (data 22/07/2026)": (
            "Backup do código fonte – última versão (data {{DATA_BACKUP}})"
        ),
        "Assinatura: PLANO SINGLE": "Assinatura: {{PLANO_HOSPEDAGEM}}",
        "Domínio: argelresistencia.com.br": "Domínio: {{DOMINIO_PUBLICADO}}",
        "KickOff em 05/02/2026": "KickOff em {{DATA_KICKOFF}}",
        "Entrega em 25/06/2026": "Entrega em {{DATA_ENTREGA}}",
    }
    if text in exact:
        return exact[text]
    if text.startswith("Backup do código fonte") and "22/07/2026" in text:
        return text.replace("22/07/2026", "{{DATA_BACKUP}}")
    if text.startswith("A ARGEL ") and "especializada" in text:
        return "{{SOBRE_A_EMPRESA}}"
    if text.startswith("O responsável pela ARGEL "):
        return "{{BRIEFING_INICIAL}}"
    if text.startswith("A estrutura do site contempla"):
        return "{{LISTA_DE_PAGINAS}}"
    if "wp-admin/" in text and "argelresistencia" in text:
        return "{{WP_ADMIN_URL}}"
    if text.startswith("Ressaltamos a importância de alterar as senhas"):
        return (
            "Ressaltamos a importância de alterar as senhas de acesso às "
            "plataformas após a entrega. Além de realizar o download do "
            "conteúdo disponibilizado em nuvem com link compartilhado no "
            "e-mail {{EMAIL_CLIENTE}}."
        )
    if text.startswith("O código fonte do website desenvolvido para o cliente"):
        return (
            "O código fonte do website desenvolvido para o cliente "
            "{{RAZAO_SOCIAL}}| CNPJ: {{CNPJ}} foi cedido por meio do link: "
            "{{LINK_CODIGO_FONTE}}"
        )
    if text.startswith("Guia Rápido -https://drive.google.com/"):
        return "Guia Rápido -{{LINK_GUIA_RAPIDO}}"
    if text.startswith("ID Visual - https://drive.google.com/"):
        return "ID Visual - {{LINK_IDENTIDADE_VISUAL}}"
    if text.startswith("Usuários e Senhas - https://drive.google.com/"):
        return "Usuários e Senhas - {{LINK_USUARIOS_SENHAS}}"

    defects = (
        ("Protocolo de envoi de e-mail", "Protocolo de envio de e-mail"),
        ("tempo de bloqueia aumenta", "tempo de bloqueio aumenta"),
        ("referentes as ferramentas", "referentes às ferramentas"),
        ("funcionalidades que foge do objetivo", "funcionalidades que fogem do objetivo"),
        ('atualizações disponíveis. ".', "atualizações disponíveis."),
    )
    for before, after in defects:
        if before in text:
            return text.replace(before, after)
    return None


def _is_client_relationship(target: str) -> bool:
    lowered = target.casefold()
    return any(
        marker in lowered
        for marker in ("drive.google.com", "ondviajar.com.br", "argelresistencia.com.br")
    )


def _png_stamp(width: int, height: int) -> bytes:
    width = max(1, width)
    height = max(1, height)
    grey = bytes((242, 242, 242))
    red = bytes((192, 0, 0))
    rows = []
    for row in range(height):
        edge = row in {0, height - 1}
        pixels = red * width if edge else red + grey * max(0, width - 2) + red
        rows.append(b"\x00" + pixels)
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        data = kind + payload
        return struct.pack(">I", len(payload)) + data + struct.pack(">I", binascii.crc32(data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=9))
        + chunk(b"IEND", b"")
    )


_NEUTRAL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/Aaf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/Aaf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Ap//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IX//2gAMAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z"
)


def _neutral_media(width: int, height: int, image_format: str) -> bytes:
    if image_format == "JPEG":
        return _NEUTRAL_JPEG
    return _png_stamp(width, height)


def _deterministic_zip(path: Path, parts: dict[str, bytes]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(parts):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, parts[name], compress_type=ZIP_DEFLATED, compresslevel=9)


def _paragraph_properties(paragraph: ElementTree.Element) -> ElementTree.Element:
    properties = paragraph.find(f"{W}pPr")
    if properties is None:
        properties = ElementTree.Element(f"{W}pPr")
        paragraph.insert(0, properties)
    return properties


def _set_heading(paragraph: ElementTree.Element, style_id: str) -> None:
    properties = _paragraph_properties(paragraph)
    style = properties.find(f"{W}pStyle")
    if style is None:
        style = ElementTree.SubElement(properties, f"{W}pStyle")
    style.set(f"{W}val", style_id)


def _toc_paragraph() -> ElementTree.Element:
    paragraph = ElementTree.Element(f"{W}p")
    begin_run = ElementTree.SubElement(paragraph, f"{W}r")
    ElementTree.SubElement(
        begin_run, f"{W}fldChar", {f"{W}fldCharType": "begin"}
    )
    instruction_run = ElementTree.SubElement(paragraph, f"{W}r")
    instruction = ElementTree.SubElement(instruction_run, f"{W}instrText")
    instruction.set(f"{XML}space", "preserve")
    instruction.text = ' TOC \\o "1-2" \\h \\z \\u '
    separate_run = ElementTree.SubElement(paragraph, f"{W}r")
    ElementTree.SubElement(
        separate_run, f"{W}fldChar", {f"{W}fldCharType": "separate"}
    )
    result_run = ElementTree.SubElement(paragraph, f"{W}r")
    ElementTree.SubElement(result_run, f"{W}t").text = (
        "Atualize o sumário no Word."
    )
    end_run = ElementTree.SubElement(paragraph, f"{W}r")
    ElementTree.SubElement(
        end_run, f"{W}fldChar", {f"{W}fldCharType": "end"}
    )
    return paragraph


def _canonical_heading_paragraphs(
    body: ElementTree.Element,
) -> tuple[tuple[int, str, ElementTree.Element], ...]:
    paragraphs = list(body.iter(f"{W}p"))
    selected = []
    cursor = 0
    for level, expected in CANONICAL_HEADINGS:
        match = next(
            (
                (index, paragraph)
                for index, paragraph in enumerate(paragraphs[cursor:], cursor)
                if _paragraph_text(paragraph).strip().casefold()
                == expected.casefold()
            ),
            None,
        )
        if match is None:
            raise MasterBuildError(f"canonical heading missing or out of order: {expected}")
        index, paragraph = match
        selected.append((level, expected, paragraph))
        cursor = index + 1
    return tuple(selected)


def _ensure_numbering(parts: dict[str, bytes], changes: list[_Change]) -> None:
    numbering = ElementTree.fromstring(
        parts.get("word/numbering.xml", f'<w:numbering xmlns:w="{WORD_NS}"/>'.encode())
    )
    for item in list(numbering):
        if item.tag == f"{W}abstractNum" and item.get(f"{W}abstractNumId") == "900":
            numbering.remove(item)
        if item.tag == f"{W}num" and item.get(f"{W}numId") == "900":
            numbering.remove(item)
    abstract = ElementTree.SubElement(
        numbering, f"{W}abstractNum", {f"{W}abstractNumId": "900"}
    )
    ElementTree.SubElement(
        abstract, f"{W}multiLevelType", {f"{W}val": "multilevel"}
    )
    for level, text in ((0, "%1"), (1, "%1.%2")):
        item = ElementTree.SubElement(
            abstract, f"{W}lvl", {f"{W}ilvl": str(level)}
        )
        ElementTree.SubElement(item, f"{W}start", {f"{W}val": "1"})
        ElementTree.SubElement(item, f"{W}numFmt", {f"{W}val": "decimal"})
        ElementTree.SubElement(item, f"{W}lvlText", {f"{W}val": text})
        ElementTree.SubElement(
            item, f"{W}pStyle", {f"{W}val": f"Heading{level + 1}"}
        )
    number = ElementTree.SubElement(numbering, f"{W}num", {f"{W}numId": "900"})
    ElementTree.SubElement(number, f"{W}abstractNumId", {f"{W}val": "900"})
    parts["word/numbering.xml"] = ElementTree.tostring(
        numbering, encoding="utf-8", xml_declaration=True
    )
    changes.append(
        _Change(
            "numbering",
            "word/numbering.xml",
            "source numbering",
            "Heading1 %1; Heading2 %1.%2 through 2.10/2.11",
        )
    )


def _ensure_discoverable_parts(
    parts: dict[str, bytes], changes: list[_Change]
) -> None:
    relations = ElementTree.fromstring(parts["word/_rels/document.xml.rels"])
    specifications = (
        ("settings", "settings.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"),
        ("styles", "styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("numbering", "numbering.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"),
        ("fontTable", "fontTable.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"),
    )
    content_types = ElementTree.fromstring(parts["[Content_Types].xml"])
    for kind, target, content_type in specifications:
        relationship_type = f"{OFFICE_REL_NS}/{kind}"
        if not any(
            item.get("Type") == relationship_type and item.get("Target") == target
            for item in relations
        ):
            relation_id = f"rIdMaster{kind}"
            ElementTree.SubElement(
                relations,
                f"{{{RELATIONSHIPS_NS}}}Relationship",
                {"Id": relation_id, "Type": relationship_type, "Target": target},
            )
            changes.append(
                _Change(
                    "relationship added",
                    "word/_rels/document.xml.rels",
                    "(none)",
                    f"{relation_id} -> {target}",
                )
            )
        part_name = f"/word/{target}"
        if not any(item.get("PartName") == part_name for item in content_types):
            ElementTree.SubElement(
                content_types,
                f"{{{CONTENT_TYPES_NS}}}Override",
                {"PartName": part_name, "ContentType": content_type},
            )
            changes.append(
                _Change(
                    "content type added",
                    "[Content_Types].xml",
                    "(none)",
                    part_name,
                )
            )
    parts["word/_rels/document.xml.rels"] = ElementTree.tostring(
        relations, encoding="utf-8", xml_declaration=True
    )
    parts["[Content_Types].xml"] = ElementTree.tostring(
        content_types, encoding="utf-8", xml_declaration=True
    )


def _add_signoff_structure(
    parts: dict[str, bytes], changes: list[_Change]
) -> None:
    document = ElementTree.fromstring(parts["word/document.xml"])
    body = document.find(f"{W}body")
    if body is not None:
        children = list(body)
        summary = next((item for item in children if item.tag == f"{W}p" and _paragraph_text(item) == "SUMÁRIO"), None)
        first_body = next((item for item in children if item.tag == f"{W}p" and _paragraph_text(item) == "ETAPA 1"), None)
        if summary is not None and first_body is not None:
            start, end = children.index(summary), children.index(first_body)
            for item in children[start + 1 : end]:
                changes.append(
                    _Change(
                        "summary paragraph removed",
                        "word/document.xml",
                        _paragraph_text(item),
                        "(replaced by live TOC)",
                    )
                )
                body.remove(item)
            body.insert(start + 1, _toc_paragraph())
            changes.append(
                _Change(
                    "TOC field added",
                    "word/document.xml",
                    "hand-typed summary",
                    'complex TOC field \\o "1-2"',
                )
            )
        for paragraph in body.iter(f"{W}p"):
            style = paragraph.find(f"{W}pPr/{W}pStyle")
            if style is not None and style.get(f"{W}val") in {"Heading1", "Heading2"}:
                style.set(f"{W}val", "Normal")
        for level, title, paragraph in _canonical_heading_paragraphs(body):
            _set_heading(paragraph, f"Heading{level}")
            changes.append(
                _Change(
                    "heading assigned",
                    "word/document.xml",
                    title,
                    f"Heading{level}",
                )
            )
        parts["word/document.xml"] = ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)

    settings = ElementTree.fromstring(parts.get("word/settings.xml", f'<w:settings xmlns:w="{WORD_NS}"/>'.encode()))
    update = settings.find(f"{W}updateFields")
    if update is None:
        update = ElementTree.SubElement(settings, f"{W}updateFields")
    update.set(f"{W}val", "true")
    parts["word/settings.xml"] = ElementTree.tostring(settings, encoding="utf-8", xml_declaration=True)
    changes.append(
        _Change(
            "setting",
            "word/settings.xml",
            "source field-update behavior",
            "updateFields=true",
        )
    )

    styles = ElementTree.fromstring(parts.get("word/styles.xml", f'<w:styles xmlns:w="{WORD_NS}"/>'.encode()))
    for level, name in ((1, "Título 1"), (2, "Título 2")):
        style_id = f"Heading{level}"
        style = next((item for item in styles.findall(f"{W}style") if item.get(f"{W}styleId") == style_id), None)
        if style is None:
            style = ElementTree.SubElement(styles, f"{W}style", {f"{W}type": "paragraph", f"{W}styleId": style_id})
        named = style.find(f"{W}name")
        if named is None:
            named = ElementTree.SubElement(style, f"{W}name")
        named.set(f"{W}val", name)
        properties = style.find(f"{W}pPr")
        if properties is None:
            properties = ElementTree.SubElement(style, f"{W}pPr")
        outline = properties.find(f"{W}outlineLvl")
        if outline is None:
            outline = ElementTree.SubElement(properties, f"{W}outlineLvl")
        outline.set(f"{W}val", str(level - 1))
        run = style.find(f"{W}rPr")
        if run is None:
            run = ElementTree.SubElement(style, f"{W}rPr")
        fonts = run.find(f"{W}rFonts")
        if fonts is None:
            fonts = ElementTree.SubElement(run, f"{W}rFonts")
        for attribute in ("ascii", "hAnsi", "cs", "eastAsia"):
            fonts.set(f"{W}{attribute}", "Montserrat")
        number_properties = properties.find(f"{W}numPr")
        if number_properties is None:
            number_properties = ElementTree.SubElement(properties, f"{W}numPr")
        level_element = number_properties.find(f"{W}ilvl")
        if level_element is None:
            level_element = ElementTree.SubElement(number_properties, f"{W}ilvl")
        level_element.set(f"{W}val", str(level - 1))
        number_id = number_properties.find(f"{W}numId")
        if number_id is None:
            number_id = ElementTree.SubElement(number_properties, f"{W}numId")
        number_id.set(f"{W}val", "900")
        changes.append(
            _Change(
                "style updated",
                "word/styles.xml",
                style_id,
                f"{name}; Montserrat; numbering 900 level {level - 1}",
            )
        )
    parts["word/styles.xml"] = ElementTree.tostring(styles, encoding="utf-8", xml_declaration=True)
    _ensure_numbering(parts, changes)
    _ensure_discoverable_parts(parts, changes)


def _embed_montserrat(
    parts: dict[str, bytes], changes: list[_Change]
) -> None:
    font_path = Path(__file__).with_name("assets") / "Montserrat-wght.ttf"
    asset_folder = font_path.parent
    font = font_path.read_bytes()
    key = uuid.UUID(_FONT_KEY).bytes[::-1]
    obfuscated = bytearray(font)
    for index in range(min(32, len(obfuscated))):
        obfuscated[index] ^= key[index % len(key)]
    faces = ("Montserrat", "Montserrat Medium", "Montserrat Light", "Montserrat ExtraLight", "Montserrat Black")
    font_table = ElementTree.fromstring(parts.get("word/fontTable.xml", f'<w:fonts xmlns:w="{WORD_NS}" xmlns:r="{OFFICE_REL_NS}"/>'.encode()))
    for index, face in enumerate(faces):
        relation_id = f"rIdMontserrat{index}"
        target = f"fonts/montserrat-{index}.odttf"
        parts[f"word/{target}"] = bytes(obfuscated)
        changes.append(
            _Change(
                "Boilerplate font embedded",
                f"word/{target}",
                "(none)",
                f"{face}; source sha256={hashlib.sha256(font).hexdigest()}",
            )
        )
        entry = next((item for item in font_table.findall(f"{W}font") if item.get(f"{W}name") == face), None)
        if entry is None:
            entry = ElementTree.SubElement(font_table, f"{W}font", {f"{W}name": face})
        embed = entry.find(f"{W}embedRegular")
        if embed is None:
            embed = ElementTree.SubElement(entry, f"{W}embedRegular")
        embed.set(f"{R}id", relation_id)
        embed.set(f"{W}fontKey", f"{{{_FONT_KEY}}}")
    parts["word/fontTable.xml"] = ElementTree.tostring(font_table, encoding="utf-8", xml_declaration=True)
    rels = ElementTree.fromstring(parts.get("word/_rels/fontTable.xml.rels", f'<Relationships xmlns="{RELATIONSHIPS_NS}"/>'.encode()))
    for index, _face in enumerate(faces):
        relation_id = f"rIdMontserrat{index}"
        relation = next((item for item in rels if item.get("Id") == relation_id), None)
        if relation is None:
            relation = ElementTree.SubElement(rels, f"{{{RELATIONSHIPS_NS}}}Relationship")
        relation.attrib.update({"Id": relation_id, "Type": f"{OFFICE_REL_NS}/font", "Target": f"fonts/montserrat-{index}.odttf"})
        changes.append(
            _Change(
                "font relationship added",
                "word/_rels/fontTable.xml.rels",
                "(none)",
                f"{relation_id} -> fonts/montserrat-{index}.odttf",
            )
        )
    parts["word/_rels/fontTable.xml.rels"] = ElementTree.tostring(rels, encoding="utf-8", xml_declaration=True)
    types = ElementTree.fromstring(parts["[Content_Types].xml"])
    for index, _face in enumerate(faces):
        part_name = f"/word/fonts/montserrat-{index}.odttf"
        override = next((item for item in types if item.get("PartName") == part_name), None)
        if override is None:
            override = ElementTree.SubElement(types, f"{{{CONTENT_TYPES_NS}}}Override")
        override.attrib.update({"PartName": part_name, "ContentType": "application/vnd.openxmlformats-officedocument.obfuscatedFont"})
        changes.append(
            _Change(
                "font content type added",
                "[Content_Types].xml",
                "(none)",
                part_name,
            )
        )

    license_text = (asset_folder / "OFL.txt").read_bytes()
    source_text = (asset_folder / "FONT-SOURCE.md").read_bytes()
    metadata = (asset_folder / "METADATA.pb").read_bytes()
    parts["customXml/Montserrat-OFL.txt"] = license_text
    parts["customXml/Montserrat-SOURCE.md"] = source_text
    parts["customXml/Montserrat-METADATA.pb"] = metadata
    for artifact, detail in (
        ("customXml/Montserrat-OFL.txt", "SIL Open Font License 1.1"),
        (
            "customXml/Montserrat-SOURCE.md",
            "upstream URL, revision, source filename, and SHA-256",
        ),
        ("customXml/Montserrat-METADATA.pb", "exact upstream metadata"),
    ):
        changes.append(
            _Change(
                "Boilerplate font record added",
                artifact,
                "(none)",
                detail,
            )
        )
    provenance = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<provenance origin="Boilerplate" family="Montserrat" '
        'sha256="0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7" '
        'upstreamRevision="76fca9fd0bb4ea46583f92e978660f3984ab9442">'
        '<license part="/customXml/Montserrat-OFL.txt">SIL Open Font License 1.1</license>'
        '<source part="/customXml/Montserrat-SOURCE.md"/>'
        '<metadata part="/customXml/Montserrat-METADATA.pb"/>'
        "</provenance>"
    ).encode("utf-8")
    parts["customXml/montserrat-provenance.xml"] = provenance
    changes.append(
        _Change(
            "Boilerplate provenance added",
            "customXml/montserrat-provenance.xml",
            "(none)",
            "Montserrat upstream revision, SHA-256, SIL OFL, source metadata",
        )
    )

    document_relations = ElementTree.fromstring(
        parts["word/_rels/document.xml.rels"]
    )
    if not any(
        item.get("Id") == "rIdMontserratProvenance"
        for item in document_relations
    ):
        ElementTree.SubElement(
            document_relations,
            f"{{{RELATIONSHIPS_NS}}}Relationship",
            {
                "Id": "rIdMontserratProvenance",
                "Type": f"{OFFICE_REL_NS}/customXml",
                "Target": "../customXml/montserrat-provenance.xml",
            },
        )
    parts["word/_rels/document.xml.rels"] = ElementTree.tostring(
        document_relations, encoding="utf-8", xml_declaration=True
    )
    changes.append(
        _Change(
            "provenance relationship added",
            "word/_rels/document.xml.rels",
            "(none)",
            "rIdMontserratProvenance -> customXml/montserrat-provenance.xml",
        )
    )
    for part_name, content_type in (
        ("/customXml/montserrat-provenance.xml", "application/xml"),
        ("/customXml/Montserrat-OFL.txt", "text/plain"),
        ("/customXml/Montserrat-SOURCE.md", "text/markdown"),
        ("/customXml/Montserrat-METADATA.pb", "text/plain"),
    ):
        if not any(item.get("PartName") == part_name for item in types):
            ElementTree.SubElement(
                types,
                f"{{{CONTENT_TYPES_NS}}}Override",
                {"PartName": part_name, "ContentType": content_type},
            )
            changes.append(
                _Change(
                    "provenance content type added",
                    "[Content_Types].xml",
                    "(none)",
                    part_name,
                )
            )
    parts["[Content_Types].xml"] = ElementTree.tostring(types, encoding="utf-8", xml_declaration=True)


def _format_diff(
    source: Path, master: Path, changes: list[_Change]
) -> str:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    lines = [
        "# MASTER-DIFF",
        "",
        "This is the complete, reviewable transformation from the approved "
        "filled source to the client-neutral Master.",
        "",
        f"- Source: `{source.name}` (SHA-256 `{hashlib.sha256(source.read_bytes()).hexdigest()}`)",
        f"- Master: `{master.name}` (SHA-256 `{hashlib.sha256(master.read_bytes()).hexdigest()}`)",
        f"- Enumerated changes: {len(changes)}",
        "",
        "| Kind | Artifact | Before | After |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {cell(change.category)} | {cell(change.artifact)} | {cell(change.before)} | {cell(change.after)} |"
        for change in changes
    )
    lines.extend(
        (
            "",
            "## Sign-off rulings",
            "",
            "- The orphaned hand-typed `2.10 Indicadores14` entry was deliberately "
            "removed with the literal summary by owner decision: it has no body "
            "section. The live Heading 2 range ends at `2.10 ORIENTAÇÕES AO CLIENTE`.",
            "- The Ficha Técnica passage beginning `A portal web` remains verbatim; "
            "its grammar may be normative source text.",
            "",
        )
    )
    return "\n".join(lines)


def build_master(source: str | Path, destination: str | Path) -> MasterBuild:
    """Transform approved *source* into ``MASTER.docx`` and ``MASTER-DIFF.md``.

    ``destination`` may be an output directory or the explicit Master DOCX path.
    The result is byte-reproducible for identical source bytes.
    """
    source_path = Path(source)
    target = Path(destination)
    master_path = target if target.suffix.casefold() == ".docx" else target / "MASTER.docx"
    diff_path = master_path.with_name("MASTER-DIFF.md")
    source_package = open_docx_package(source_path)
    with ZipFile(source_path) as archive:
        parts = {entry.filename: archive.read(entry.filename) for entry in archive.infolist() if not entry.is_dir()}

    document_name = "word/document.xml"
    relationship_name = "word/_rels/document.xml.rels"
    if document_name not in parts or relationship_name not in parts:
        raise MasterBuildError("approved source lacks the main Word document or relationships")

    document = ElementTree.fromstring(parts[document_name])
    relationships = ElementTree.fromstring(parts[relationship_name])
    removed_ids = {
        relation.attrib["Id"]
        for relation in relationships.findall(f"{{{RELATIONSHIPS_NS}}}Relationship")
        if relation.attrib.get("TargetMode") == "External"
        and _is_client_relationship(relation.attrib.get("Target", ""))
    }
    changes: list[_Change] = []

    for paragraph_index, paragraph in enumerate(document.iter(f"{W}p")):
        before = _paragraph_text(paragraph)
        replacement = _source_replacement(before)
        client_hyperlinks = [
            hyperlink
            for hyperlink in paragraph.findall(f"{W}hyperlink")
            if hyperlink.get(f"{R}id") in removed_ids
        ]
        if replacement is not None and replacement != before:
            for hyperlink in client_hyperlinks:
                changes.append(
                    _Change(
                        "hyperlink removed",
                        f"word/document.xml p={paragraph_index}",
                        f"{hyperlink.get(f'{R}id')}: {_paragraph_text(hyperlink)}",
                        "plain Token or text run",
                    )
                )
            _replace_paragraph(paragraph, replacement)
            changes.append(
                _Change("text", f"word/document.xml p={paragraph_index}", before, replacement)
            )
        else:
            for hyperlink in client_hyperlinks:
                position = list(paragraph).index(hyperlink)
                for child in list(hyperlink):
                    paragraph.insert(position, child)
                    position += 1
                paragraph.remove(hyperlink)
                changes.append(
                    _Change(
                        "hyperlink removed",
                        f"word/document.xml p={paragraph_index}",
                        f"{hyperlink.get(f'{R}id')}: {_paragraph_text(hyperlink)}",
                        "plain text run",
                    )
                )

    for relationship in list(relationships.findall(f"{{{RELATIONSHIPS_NS}}}Relationship")):
        if relationship.attrib.get("Id") in removed_ids:
            relationships.remove(relationship)
            changes.append(
                _Change(
                    "relationship removed",
                    f"word/document.xml {relationship.attrib['Id']}",
                    relationship.attrib.get("Target", ""),
                    "(none)",
                )
            )

    parts[document_name] = ElementTree.tostring(
        document, encoding="utf-8", xml_declaration=True
    )
    parts[relationship_name] = ElementTree.tostring(
        relationships, encoding="utf-8", xml_declaration=True
    )

    source_media = {item.part_name: item for item in source_package.media}
    for name, media in source_media.items():
        if name in BOILERPLATE_MEDIA:
            continue
        parts[name] = _neutral_media(media.width, media.height, media.image_format)
        changes.append(
            _Change("media neutralized", name, media.sha256, "neutral stamp"))

    _add_signoff_structure(parts, changes)
    _embed_montserrat(parts, changes)
    master_path.parent.mkdir(parents=True, exist_ok=True)
    _deterministic_zip(master_path, parts)
    validation = check_master_build(open_docx_package(master_path), source_package)
    if not validation.passed:
        raise MasterBuildError(validation.format())
    diff_path.write_text(_format_diff(source_path, master_path, changes), encoding="utf-8")
    return MasterBuild(master=master_path, diff=diff_path, validation=validation)


__all__ = [
    "EXPECTED_TOKENS",
    "MasterBuild",
    "MasterBuildError",
    "build_master",
]
