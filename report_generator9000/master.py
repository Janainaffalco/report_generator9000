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
    CONTENT_TYPES_NS,
    DRAWING_NS,
    OFFICE_REL_NS,
    PICTURE_NS,
    RELATIONSHIPS_NS,
    WORD_DRAWING_NS,
    WORD_NS,
    DocxPackage,
    open_docx_package,
    serialize_xml,
    text_column_width_emu,
)
from .gates.master import (
    BOILERPLATE_MEDIA,
    CANONICAL_HEADINGS,
    EXPECTED_TOKENS,
    MASTER_BLOCK_HEADINGS,
    check_master_build,
)
from .gates.results import GateResult


W = f"{{{WORD_NS}}}"
R = f"{{{OFFICE_REL_NS}}}"
WP = f"{{{WORD_DRAWING_NS}}}"
PIC = f"{{{PICTURE_NS}}}"
A = f"{{{DRAWING_NS}}}"
XML = "{http://www.w3.org/XML/1998/namespace}"
_TOKEN = re.compile(r"(\{\{[^{}<>]{1,64}\}\})")
_FONT_KEY = "6D5E55E7-46BF-4B17-9DCE-422D31C5A72D"
_FONT_UPSTREAM_REVISION = "76fca9fd0bb4ea46583f92e978660f3984ab9442"
_FICHA_TECNICA_CITATION = "Fonte: Ficha Técnica SEBRAETEC 4.0, p. 3"
_SOURCE_CITATION_SIZE = "16"

_FONT_FACE_ORDER = (
    "Montserrat",
    "Montserrat Medium",
    "Montserrat Light",
    "Montserrat ExtraLight",
    "Montserrat Black",
)
_FONT_FACE_ASSETS = {
    "Montserrat": "Montserrat-Regular.ttf",
    "Montserrat Medium": "Montserrat-Medium.ttf",
    "Montserrat Light": "Montserrat-Light.ttf",
    "Montserrat ExtraLight": "Montserrat-ExtraLight.ttf",
    "Montserrat Black": "Montserrat-Black.ttf",
}

_NUMBERING_CHILD_ORDER = ("numPicBullet", "abstractNum", "num", "numIdMacAtCleanup")
_LEVEL_CHILD_ORDER = (
    "start",
    "numFmt",
    "lvlRestart",
    "pStyle",
    "isLgl",
    "suff",
    "lvlText",
    "lvlPicBulletId",
    "legacy",
    "lvlJc",
    "pPr",
    "rPr",
)
_PARAGRAPH_PROPERTIES_CHILD_ORDER = (
    "pStyle",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "framePr",
    "widowControl",
    "numPr",
    "suppressLineNumbers",
    "pBdr",
    "shd",
    "tabs",
    "suppressAutoHyphens",
    "kinsoku",
    "wordWrap",
    "overflowPunct",
    "topLinePunct",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
)
_RUN_PROPERTIES_CHILD_ORDER = (
    "rStyle",
    "rFonts",
    "b",
    "bCs",
    "i",
    "iCs",
    "caps",
    "smallCaps",
    "strike",
    "dstrike",
    "outline",
    "shadow",
    "emboss",
    "imprint",
    "noProof",
    "snapToGrid",
    "vanish",
    "webHidden",
    "color",
    "spacing",
    "w",
    "kern",
    "position",
    "sz",
    "szCs",
    "highlight",
    "u",
    "effect",
    "bdr",
    "shd",
    "fitText",
    "vertAlign",
    "rtl",
    "cs",
    "em",
    "lang",
    "eastAsianLayout",
    "specVanish",
    "oMath",
)
_STYLE_CHILD_ORDER = (
    "name",
    "aliases",
    "basedOn",
    "next",
    "link",
    "autoRedefine",
    "hidden",
    "uiPriority",
    "semiHidden",
    "unhideWhenUsed",
    "qFormat",
    "locked",
    "personal",
    "personalCompose",
    "personalReply",
    "rsid",
    "pPr",
    "rPr",
    "tblPr",
    "trPr",
    "tcPr",
    "tblStylePr",
)


def _insertion_index(
    parent: ElementTree.Element, tag: str, order: tuple[str, ...]
) -> int:
    """Return the index at which a schema-ordered *tag* child belongs in *parent*."""
    local_name = tag.rsplit("}", 1)[-1]
    position = order.index(local_name)
    for index, child in enumerate(parent):
        child_local_name = child.tag.rsplit("}", 1)[-1]
        if child_local_name in order and order.index(child_local_name) > position:
            return index
    return len(parent)


def _ordered_child(
    parent: ElementTree.Element, tag: str, order: tuple[str, ...]
) -> ElementTree.Element:
    """Return parent's `tag` child, inserting it at its schema position if absent.

    `order` is the local-name sequence for the parent's complex type
    (ECMA-376 Part 1, Section 17). `ElementTree.SubElement` always appends,
    which is invalid for the ordered `xsd:sequence` every OOXML complex type
    uses.
    """
    existing = parent.find(tag)
    if existing is not None:
        return existing
    element = ElementTree.Element(tag)
    parent.insert(_insertion_index(parent, tag, order), element)
    return element


def _ordered_insert(
    parent: ElementTree.Element, element: ElementTree.Element, order: tuple[str, ...]
) -> None:
    """Insert a new, repeatable *element* into *parent* at its schema position."""
    parent.insert(_insertion_index(parent, element.tag, order), element)


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


def _restyle_source_citations(
    document: ElementTree.Element, changes: list[_Change]
) -> None:
    for paragraph in document.iter(f"{W}p"):
        if _paragraph_text(paragraph) != _FICHA_TECNICA_CITATION:
            continue
        for run in paragraph.findall(f"{W}r"):
            properties = run.find(f"{W}rPr")
            if properties is None:
                properties = ElementTree.Element(f"{W}rPr")
                run.insert(0, properties)
            _ordered_child(properties, f"{W}i", _RUN_PROPERTIES_CHILD_ORDER)
            size = _ordered_child(properties, f"{W}sz", _RUN_PROPERTIES_CHILD_ORDER)
            size.set(f"{W}val", _SOURCE_CITATION_SIZE)
            size_complex_script = _ordered_child(
                properties, f"{W}szCs", _RUN_PROPERTIES_CHILD_ORDER
            )
            size_complex_script.set(f"{W}val", _SOURCE_CITATION_SIZE)
        changes.append(
            _Change(
                "source citation restyled",
                "word/document.xml",
                "Ficha Técnica SEBRAETEC 4.0 – Pág. 3",
                f"{_FICHA_TECNICA_CITATION}; smaller italic right-aligned citation",
            )
        )


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
    if text == "Ficha Técnica SEBRAETEC 4.0 – Pág. 3":
        return _FICHA_TECNICA_CITATION

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
    style = _ordered_child(
        properties, f"{W}pStyle", _PARAGRAPH_PROPERTIES_CHILD_ORDER
    )
    style.set(f"{W}val", style_id)


def _set_spacing(
    paragraph: ElementTree.Element, *, before: int, after: int
) -> None:
    properties = _paragraph_properties(paragraph)
    spacing = _ordered_child(
        properties, f"{W}spacing", _PARAGRAPH_PROPERTIES_CHILD_ORDER
    )
    spacing.set(f"{W}before", str(before))
    spacing.set(f"{W}after", str(after))


def _strip_dot_leader_tabs(properties: ElementTree.Element) -> bool:
    tabs = properties.find(f"{W}tabs")
    if tabs is None:
        return False
    leaders = [tab for tab in tabs.findall(f"{W}tab") if tab.get(f"{W}leader")]
    for tab in leaders:
        tabs.remove(tab)
    if not list(tabs):
        properties.remove(tabs)
    return bool(leaders)


def _scale_block_image(
    image: ElementTree.Element, column_width_emu: int, changes: list[_Change]
) -> None:
    extent = image.find(f".//{WP}extent")
    if extent is None or extent.get("cx") is None:
        return
    width = int(extent.get("cx"))
    height = int(extent.get("cy"))
    if width <= column_width_emu:
        return
    scale = column_width_emu / width
    scaled_width = column_width_emu
    scaled_height = round(height * scale)
    extent.set("cx", str(scaled_width))
    extent.set("cy", str(scaled_height))
    for sibling_extent in image.iter(f"{A}ext"):
        if "cx" in sibling_extent.attrib and "cy" in sibling_extent.attrib:
            sibling_extent.set("cx", str(scaled_width))
            sibling_extent.set("cy", str(scaled_height))
    changes.append(
        _Change(
            "Block image scaled to column",
            "word/document.xml",
            f"{width}x{height} EMU",
            f"{scaled_width}x{scaled_height} EMU",
        )
    )


def _canonicalize_blocks(
    parts: dict[str, bytes], changes: list[_Change]
) -> None:
    original_document = parts["word/document.xml"]
    document = ElementTree.fromstring(original_document)
    try:
        column_width_emu = text_column_width_emu(document)
    except ValueError as error:
        raise MasterBuildError(str(error)) from error
    body = document.find(f"{W}body")
    if body is None:
        raise MasterBuildError("word/document.xml has no body")
    children = list(body)
    start = next(
        (
            index
            for index, item in enumerate(children)
            if item.tag == f"{W}p"
            and _paragraph_text(item).strip().casefold()
            == "página home e seções"
        ),
        None,
    )
    end = next(
        (
            index
            for index, item in enumerate(children)
            if item.tag == f"{W}p"
            and _paragraph_text(item).strip().casefold()
            == "painel de configuração wordpress"
            and index > (start or 0)
        ),
        None,
    )
    if start is None or end is None:
        raise MasterBuildError("canonical Block region boundaries not found")

    region = children[start + 1 : end]
    empty_spacers = [
        item
        for item in region
        if item.tag == f"{W}p"
        and not _paragraph_text(item).strip()
        and item.find(f".//{W}drawing") is None
    ]
    for spacer in empty_spacers:
        body.remove(spacer)
        changes.append(
            _Change(
                "Block spacer removed",
                "word/document.xml",
                "empty paragraph",
                "paragraph spacing",
            )
        )

    children = list(body)
    block_pairs = []
    cursor = start + 1
    for expected in MASTER_BLOCK_HEADINGS:
        heading_index = next(
            (
                index
                for index, item in enumerate(children[cursor:], cursor)
                if item.tag == f"{W}p"
                and _paragraph_text(item).strip().casefold()
                == expected.casefold()
            ),
            None,
        )
        if heading_index is None or heading_index + 1 >= len(children):
            raise MasterBuildError(f"canonical Block missing: {expected}")
        heading = children[heading_index]
        image = children[heading_index + 1]
        if image.find(f".//{W}drawing") is None:
            raise MasterBuildError(f"Block image does not follow heading: {expected}")
        properties = _paragraph_properties(heading)
        keep = _ordered_child(
            properties, f"{W}keepNext", _PARAGRAPH_PROPERTIES_CHILD_ORDER
        )
        keep.set(f"{W}val", "true")
        style = properties.find(f"{W}pStyle")
        if style is not None and style.get(f"{W}val") in {
            "Heading1",
            "Heading2",
        }:
            style.set(f"{W}val", "Normal")
        if _strip_dot_leader_tabs(properties):
            changes.append(
                _Change(
                    "dot-leader tab stop removed",
                    "word/document.xml",
                    expected,
                    "leftover summary tab stop removed",
                )
            )
        _set_spacing(heading, before=240, after=80)
        _set_spacing(image, before=0, after=240)
        _scale_block_image(image, column_width_emu, changes)
        block_pairs.append((heading, image))
        changes.append(
            _Change(
                "Block canonicalized",
                "word/document.xml",
                expected,
                "two paragraphs; keepNext; pPr spacing; TOC-excluded",
            )
        )
        cursor = heading_index + 2

    stamp_heading, stamp_image = block_pairs[0]
    for paragraph in (stamp_heading, stamp_image):
        for marker in list(paragraph.findall(f"{W}bookmarkStart")) + list(
            paragraph.findall(f"{W}bookmarkEnd")
        ):
            paragraph.remove(marker)
    used_bookmark_ids = {
        int(marker.get(f"{W}id"))
        for marker in document.iter()
        if marker.tag in {f"{W}bookmarkStart", f"{W}bookmarkEnd"}
        and (marker.get(f"{W}id") or "").isdigit()
    }
    stamp_id = str(max(used_bookmark_ids, default=-1) + 1)
    stamp_heading.insert(
        1 if stamp_heading.find(f"{W}pPr") is not None else 0,
        ElementTree.Element(
            f"{W}bookmarkStart",
            {f"{W}id": stamp_id, f"{W}name": "MASTER_BLOCK_STAMP"},
        ),
    )
    stamp_image.append(
        ElementTree.Element(f"{W}bookmarkEnd", {f"{W}id": stamp_id})
    )
    changes.append(
        _Change(
            "Block stamp designated",
            "word/document.xml",
            "PÁGINA HOME Block",
            "MASTER_BLOCK_STAMP",
        )
    )
    parts["word/document.xml"] = serialize_xml(document, original_document)


def clone_block_stamp(
    document: ElementTree.Element,
    heading: str,
    relationship_id: str,
) -> tuple[ElementTree.Element, ElementTree.Element]:
    """Clone and insert the Master's Block stamp before the next body section."""
    if not relationship_id:
        raise ValueError("relationship_id must not be empty")
    body = document.find(f"{W}body")
    if body is None:
        raise ValueError("document has no body")
    children = list(body)
    source_index = next(
        (
            index
            for index, paragraph in enumerate(children)
            if paragraph.find(
                f"{W}bookmarkStart[@{W}name='MASTER_BLOCK_STAMP']"
            )
            is not None
        ),
        None,
    )
    if source_index is None or source_index + 1 >= len(children):
        raise ValueError("MASTER_BLOCK_STAMP not found")
    cloned_heading = deepcopy(children[source_index])
    cloned_image = deepcopy(children[source_index + 1])
    _replace_paragraph(cloned_heading, heading)
    for paragraph in (cloned_heading, cloned_image):
        for marker in list(paragraph.findall(f"{W}bookmarkStart")) + list(
            paragraph.findall(f"{W}bookmarkEnd")
        ):
            paragraph.remove(marker)
    blip = cloned_image.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    )
    if blip is None:
        raise ValueError("MASTER_BLOCK_STAMP has no image Slot")
    blip.set(f"{R}embed", relationship_id)
    blip.attrib.pop(f"{R}link", None)

    used_doc_ids = {
        int(item.get("id"))
        for item in document.iter(f"{WP}docPr")
        if (item.get("id") or "").isdigit()
    }
    used_picture_ids = {
        int(item.get("id"))
        for item in document.iter(f"{PIC}cNvPr")
        if (item.get("id") or "").isdigit()
    }
    next_doc_id = max(used_doc_ids, default=0) + 1
    next_picture_id = max(used_picture_ids, default=0) + 1
    for item in cloned_image.iter(f"{WP}docPr"):
        item.set("id", str(next_doc_id))
        next_doc_id += 1
    for item in cloned_image.iter(f"{PIC}cNvPr"):
        item.set("id", str(next_picture_id))
        next_picture_id += 1
    for local_name in ("anchorId", "editId"):
        used_values = {
            value.upper()
            for item in document.iter()
            for attribute, value in item.attrib.items()
            if attribute.rsplit("}", 1)[-1] == local_name
        }
        numeric_values = {
            int(value, 16)
            for value in used_values
            if len(value) == 8
            and all(character in "0123456789ABCDEF" for character in value)
        }
        candidate = max(numeric_values, default=0) + 1
        for item in cloned_image.iter():
            for attribute in tuple(item.attrib):
                if attribute.rsplit("}", 1)[-1] != local_name:
                    continue
                while f"{candidate:08X}" in used_values:
                    candidate += 1
                value = f"{candidate:08X}"
                item.set(attribute, value)
                used_values.add(value)
                candidate += 1

    insertion_index = next(
        (
            index
            for index, paragraph in enumerate(children)
            if index > source_index
            and _paragraph_text(paragraph).strip().casefold()
            == "painel de configuração wordpress"
        ),
        None,
    )
    if insertion_index is None:
        raise ValueError("Block insertion boundary not found")
    body.insert(insertion_index, cloned_heading)
    body.insert(insertion_index + 1, cloned_image)
    return cloned_heading, cloned_image


def _toc_paragraph() -> ElementTree.Element:
    paragraph = ElementTree.Element(f"{W}p")
    begin_run = ElementTree.SubElement(paragraph, f"{W}r")
    ElementTree.SubElement(
        begin_run,
        f"{W}fldChar",
        {f"{W}fldCharType": "begin", f"{W}dirty": "true"},
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
    original_numbering = parts.get(
        "word/numbering.xml", f'<w:numbering xmlns:w="{WORD_NS}"/>'.encode()
    )
    numbering = ElementTree.fromstring(original_numbering)
    for item in list(numbering):
        if item.tag == f"{W}abstractNum" and item.get(f"{W}abstractNumId") == "900":
            numbering.remove(item)
        if item.tag == f"{W}num" and item.get(f"{W}numId") == "900":
            numbering.remove(item)
    abstract = ElementTree.Element(f"{W}abstractNum", {f"{W}abstractNumId": "900"})
    _ordered_insert(numbering, abstract, _NUMBERING_CHILD_ORDER)
    ElementTree.SubElement(
        abstract, f"{W}multiLevelType", {f"{W}val": "multilevel"}
    )
    for level, text, hanging in ((0, "%1", "432"), (1, "%1.%2", "576")):
        item = ElementTree.SubElement(
            abstract, f"{W}lvl", {f"{W}ilvl": str(level)}
        )
        ElementTree.SubElement(item, f"{W}start", {f"{W}val": "1"})
        ElementTree.SubElement(item, f"{W}numFmt", {f"{W}val": "decimal"})
        ElementTree.SubElement(
            item, f"{W}pStyle", {f"{W}val": f"Heading{level + 1}"}
        )
        ElementTree.SubElement(item, f"{W}suff", {f"{W}val": "space"})
        ElementTree.SubElement(item, f"{W}lvlText", {f"{W}val": text})
        ElementTree.SubElement(item, f"{W}lvlJc", {f"{W}val": "left"})
        level_properties = ElementTree.SubElement(item, f"{W}pPr")
        ElementTree.SubElement(
            level_properties,
            f"{W}ind",
            {f"{W}start": hanging, f"{W}hanging": hanging},
        )
    number = ElementTree.Element(f"{W}num", {f"{W}numId": "900"})
    _ordered_insert(numbering, number, _NUMBERING_CHILD_ORDER)
    ElementTree.SubElement(number, f"{W}abstractNumId", {f"{W}val": "900"})
    parts["word/numbering.xml"] = serialize_xml(numbering, original_numbering)
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
    original_relations = parts["word/_rels/document.xml.rels"]
    relations = ElementTree.fromstring(original_relations)
    specifications = (
        ("settings", "settings.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"),
        ("styles", "styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("numbering", "numbering.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"),
        ("fontTable", "fontTable.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"),
    )
    original_content_types = parts["[Content_Types].xml"]
    content_types = ElementTree.fromstring(original_content_types)
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
    parts["word/_rels/document.xml.rels"] = serialize_xml(
        relations, original_relations
    )
    parts["[Content_Types].xml"] = serialize_xml(
        content_types, original_content_types
    )


def _add_signoff_structure(
    parts: dict[str, bytes], changes: list[_Change]
) -> None:
    original_document = parts["word/document.xml"]
    document = ElementTree.fromstring(original_document)
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
            properties = paragraph.find(f"{W}pPr")
            if properties is not None:
                direct_numbering = properties.find(f"{W}numPr")
                if direct_numbering is not None:
                    properties.remove(direct_numbering)
                    changes.append(
                        _Change(
                            "direct numbering removed",
                            "word/document.xml",
                            title,
                            "numId 900 now applies from the style",
                        )
                    )
                if _strip_dot_leader_tabs(properties):
                    changes.append(
                        _Change(
                            "dot-leader tab stop removed",
                            "word/document.xml",
                            title,
                            "leftover summary tab stop removed",
                        )
                    )
            changes.append(
                _Change(
                    "heading assigned",
                    "word/document.xml",
                    title,
                    f"Heading{level}",
                )
            )
        parts["word/document.xml"] = serialize_xml(document, original_document)

    if "word/settings.xml" not in parts:
        parts["word/settings.xml"] = f'<w:settings xmlns:w="{WORD_NS}"/>'.encode()

    original_styles = parts.get(
        "word/styles.xml", f'<w:styles xmlns:w="{WORD_NS}"/>'.encode()
    )
    styles = ElementTree.fromstring(original_styles)
    for level, name in ((1, "Título 1"), (2, "Título 2")):
        style_id = f"Heading{level}"
        style = next((item for item in styles.findall(f"{W}style") if item.get(f"{W}styleId") == style_id), None)
        if style is None:
            style = ElementTree.SubElement(styles, f"{W}style", {f"{W}type": "paragraph", f"{W}styleId": style_id})
        named = _ordered_child(style, f"{W}name", _STYLE_CHILD_ORDER)
        named.set(f"{W}val", name)
        properties = _ordered_child(style, f"{W}pPr", _STYLE_CHILD_ORDER)
        outline = _ordered_child(
            properties, f"{W}outlineLvl", _PARAGRAPH_PROPERTIES_CHILD_ORDER
        )
        outline.set(f"{W}val", str(level - 1))
        run = _ordered_child(style, f"{W}rPr", _STYLE_CHILD_ORDER)
        fonts = run.find(f"{W}rFonts")
        if fonts is None:
            fonts = ElementTree.SubElement(run, f"{W}rFonts")
        for attribute in ("ascii", "hAnsi", "cs", "eastAsia"):
            fonts.set(f"{W}{attribute}", "Montserrat")
        for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(f"{W}{attribute}", None)
        color = run.find(f"{W}color")
        if color is None:
            color = ElementTree.SubElement(run, f"{W}color")
        color.attrib.clear()
        color.set(f"{W}val", "404040")
        number_properties = _ordered_child(
            properties, f"{W}numPr", _PARAGRAPH_PROPERTIES_CHILD_ORDER
        )
        level_element = number_properties.find(f"{W}ilvl")
        if level_element is None:
            level_element = ElementTree.SubElement(number_properties, f"{W}ilvl")
        level_element.set(f"{W}val", str(level - 1))
        number_id = number_properties.find(f"{W}numId")
        if number_id is None:
            number_id = ElementTree.SubElement(number_properties, f"{W}numId")
        number_id.set(f"{W}val", "900")
        indentation = _ordered_child(
            properties, f"{W}ind", _PARAGRAPH_PROPERTIES_CHILD_ORDER
        )
        indentation.set(f"{W}start", "432" if level == 1 else "576")
        indentation.set(f"{W}hanging", "432" if level == 1 else "576")
        changes.append(
            _Change(
                "style updated",
                "word/styles.xml",
                style_id,
                f"{name}; Montserrat; 404040; numbering 900 level {level - 1}",
            )
        )
    parts["word/styles.xml"] = serialize_xml(styles, original_styles)
    _ensure_numbering(parts, changes)
    _ensure_discoverable_parts(parts, changes)


_RFONTS_ASCII = re.compile(r'<w:rFonts\b[^>]*\bw:ascii="([^"]*)"')
_FONT_BEARING_PART = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")


def _referenced_font_faces(parts: dict[str, bytes]) -> tuple[str, ...]:
    found: set[str] = set()
    for name, content in parts.items():
        if not _FONT_BEARING_PART.match(name):
            continue
        found.update(
            _RFONTS_ASCII.findall(content.decode("utf-8", errors="ignore"))
        )
    unknown = found - set(_FONT_FACE_ASSETS)
    if unknown:
        raise MasterBuildError(
            f"document references unrecognized font faces: {sorted(unknown)}"
        )
    return tuple(face for face in _FONT_FACE_ORDER if face in found)


def _embed_montserrat(
    parts: dict[str, bytes], changes: list[_Change]
) -> None:
    asset_folder = Path(__file__).with_name("assets")
    faces = _referenced_font_faces(parts)
    key = uuid.UUID(_FONT_KEY).bytes[::-1]
    font_digests: list[tuple[str, str, str]] = []

    original_font_table = parts.get(
        "word/fontTable.xml",
        f'<w:fonts xmlns:w="{WORD_NS}" xmlns:r="{OFFICE_REL_NS}"/>'.encode(),
    )
    font_table = ElementTree.fromstring(original_font_table)
    for index, face in enumerate(faces):
        asset_name = _FONT_FACE_ASSETS[face]
        font = (asset_folder / asset_name).read_bytes()
        obfuscated = bytearray(font)
        for position in range(min(32, len(obfuscated))):
            obfuscated[position] ^= key[position % len(key)]
        relation_id = f"rIdMontserrat{index}"
        target = f"fonts/montserrat-{index}.odttf"
        parts[f"word/{target}"] = bytes(obfuscated)
        digest = hashlib.sha256(font).hexdigest()
        font_digests.append((face, asset_name, digest))
        changes.append(
            _Change(
                "Boilerplate font embedded",
                f"word/{target}",
                "(none)",
                f"{face}; source={asset_name}; sha256={digest}",
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
    parts["word/fontTable.xml"] = serialize_xml(font_table, original_font_table)

    original_font_relations = parts.get(
        "word/_rels/fontTable.xml.rels",
        f'<Relationships xmlns="{RELATIONSHIPS_NS}"/>'.encode(),
    )
    rels = ElementTree.fromstring(original_font_relations)
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
    parts["word/_rels/fontTable.xml.rels"] = serialize_xml(
        rels, original_font_relations
    )

    original_content_types = parts["[Content_Types].xml"]
    types = ElementTree.fromstring(original_content_types)
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
    font_entries = "".join(
        f'<font name="{face}" file="{asset_name}" sha256="{digest}"/>'
        for face, asset_name, digest in font_digests
    )
    provenance = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<provenance origin="Boilerplate" family="Montserrat" '
        f'upstreamRevision="{_FONT_UPSTREAM_REVISION}">'
        f"{font_entries}"
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
            "Montserrat upstream revision, per-face SHA-256, SIL OFL, source metadata",
        )
    )

    original_document_relations = parts["word/_rels/document.xml.rels"]
    document_relations = ElementTree.fromstring(original_document_relations)
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
    parts["word/_rels/document.xml.rels"] = serialize_xml(
        document_relations, original_document_relations
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
    parts["[Content_Types].xml"] = serialize_xml(types, original_content_types)


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
            "- `Ficha Técnica SEBRAETEC 4.0 – Pág. 3` is a citation of page 3 of the "
            "SEBRAETEC spec, not a page counter for this document, by owner ruling. "
            "It is kept and restyled as `Fonte: Ficha Técnica SEBRAETEC 4.0, p. 3` "
            "so it cannot be misread as pagination.",
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

    original_document = parts[document_name]
    original_relationships = parts[relationship_name]
    document = ElementTree.fromstring(original_document)
    relationships = ElementTree.fromstring(original_relationships)
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

    _restyle_source_citations(document, changes)

    parts[document_name] = serialize_xml(document, original_document)
    parts[relationship_name] = serialize_xml(relationships, original_relationships)

    source_media = {item.part_name: item for item in source_package.media}
    for name, media in source_media.items():
        if name in BOILERPLATE_MEDIA:
            continue
        parts[name] = _neutral_media(media.width, media.height, media.image_format)
        changes.append(
            _Change("media neutralized", name, media.sha256, "neutral stamp"))

    _add_signoff_structure(parts, changes)
    _canonicalize_blocks(parts, changes)
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
    "clone_block_stamp",
]
