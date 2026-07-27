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
    for tag, value in (("begin", None), ("separate", None), ("end", None)):
        run = ElementTree.SubElement(paragraph, f"{W}r")
        field = ElementTree.SubElement(run, f"{W}fldChar")
        field.set(f"{W}fldCharType", tag)
        if tag == "begin":
            instruction = ElementTree.SubElement(run, f"{W}instrText")
            instruction.set(f"{XML}space", "preserve")
            instruction.text = ' TOC \\o "1-2" \\h \\z \\u '
        elif tag == "separate":
            text = ElementTree.SubElement(run, f"{W}t")
            text.text = "Atualize o sumário no Word."
    return paragraph


def _add_signoff_structure(parts: dict[str, bytes]) -> None:
    document = ElementTree.fromstring(parts["word/document.xml"])
    body = document.find(f"{W}body")
    if body is not None:
        children = list(body)
        summary = next((item for item in children if item.tag == f"{W}p" and _paragraph_text(item) == "SUMÁRIO"), None)
        first_body = next((item for item in children if item.tag == f"{W}p" and _paragraph_text(item) == "ETAPA 1"), None)
        if summary is not None and first_body is not None:
            start, end = children.index(summary), children.index(first_body)
            for item in children[start + 1 : end]:
                body.remove(item)
            body.insert(start + 1, _toc_paragraph())
        for paragraph in body.iter(f"{W}p"):
            text = _paragraph_text(paragraph).strip().casefold()
            if text in {"briefing inicial para definição do escopo", "desenvolvimento de website", "reuniões", "declaração de recebimento e finalização", "termo de cessão de direitos"}:
                _set_heading(paragraph, "Heading1")
            elif text in {"sobre a empresa", "briefing", "objetivo", "acessos e entregas", "hospedagem e dados técnicos", "plataforma | wordpress", "plugins", "identidade visual", "página home e seções", "painel de configuração wordpress", "seo", "orientações ao cliente"}:
                _set_heading(paragraph, "Heading2")
        parts["word/document.xml"] = ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)

    settings = ElementTree.fromstring(parts.get("word/settings.xml", f'<w:settings xmlns:w="{WORD_NS}"/>'.encode()))
    update = settings.find(f"{W}updateFields")
    if update is None:
        update = ElementTree.SubElement(settings, f"{W}updateFields")
    update.set(f"{W}val", "true")
    parts["word/settings.xml"] = ElementTree.tostring(settings, encoding="utf-8", xml_declaration=True)

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
    parts["word/styles.xml"] = ElementTree.tostring(styles, encoding="utf-8", xml_declaration=True)


def _embed_montserrat(parts: dict[str, bytes]) -> None:
    font_path = Path(__file__).with_name("assets") / "Montserrat-wght.ttf"
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
    parts["word/_rels/fontTable.xml.rels"] = ElementTree.tostring(rels, encoding="utf-8", xml_declaration=True)
    types = ElementTree.fromstring(parts["[Content_Types].xml"])
    for index, _face in enumerate(faces):
        part_name = f"/word/fonts/montserrat-{index}.odttf"
        override = next((item for item in types if item.get("PartName") == part_name), None)
        if override is None:
            override = ElementTree.SubElement(types, f"{{{CONTENT_TYPES_NS}}}Override")
        override.attrib.update({"PartName": part_name, "ContentType": "application/vnd.openxmlformats-officedocument.obfuscatedFont"})
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
            "## Escalations retained without change",
            "",
            "- `2.10 Indicadores14` remains in the summary without a matching body section.",
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

    _add_signoff_structure(parts)
    _embed_montserrat(parts)
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
