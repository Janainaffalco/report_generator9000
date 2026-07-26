"""Compose a synthetic, client-neutral DOCX for gate tests.

Each call builds a package exhibiting exactly the paragraphs, media, and
relationships the caller asks for -- including deliberately broken ones,
such as a relationship pointing at a part that does not exist, or a
relationship no paragraph references.
"""

from __future__ import annotations

import binascii
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WORD_DRAWING_NS = (
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
)
PICTURE_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"

_RELATIONSHIP_TYPES = {
    "image": f"{OFFICE_REL_NS}/image",
    "hyperlink": f"{OFFICE_REL_NS}/hyperlink",
}

_EXTENSION_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


@dataclass(frozen=True)
class ParagraphSpec:
    runs: tuple[str, ...] = ()
    keep_next: bool = False
    image: str | None = None
    hyperlink: str | None = None
    extent: tuple[int, int] = (5400000, 3600000)


@dataclass(frozen=True)
class RelationshipSpec:
    id: str
    target: str
    kind: str = "image"
    external: bool = False


def paragraph(*runs: str, **kwargs: object) -> ParagraphSpec:
    return ParagraphSpec(runs=runs, **kwargs)


def _chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(
        ">I", binascii.crc32(payload) & 0xFFFFFFFF
    )


def _stored_deflate(data: bytes) -> bytes:
    blocks = [data[position : position + 65_535] for position in range(0, len(data), 65_535)]
    if not blocks:
        blocks = [b""]
    output = bytearray(b"\x78\x01")
    for index, block in enumerate(blocks):
        output.append(1 if index == len(blocks) - 1 else 0)
        output += struct.pack("<HH", len(block), len(block) ^ 0xFFFF)
        output += block
    first = 1
    second = 0
    for byte in data:
        first = (first + byte) % 65_521
        second = (second + first) % 65_521
    output += struct.pack(">I", (second << 16) | first)
    return bytes(output)


def png_bytes(
    width: int, height: int, red: int = 0xC0, green: int = 0x00, blue: int = 0x00
) -> bytes:
    pixel = bytes((red & 0xFF, green & 0xFF, blue & 0xFF))
    rows = b"".join(b"\x00" + pixel * width for _ in range(height))
    stored = _stored_deflate(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", stored)
        + _chunk(b"IEND", b"")
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _paragraph_xml(spec: ParagraphSpec) -> str:
    properties = "<w:pPr><w:keepNext/></w:pPr>" if spec.keep_next else ""
    runs_xml = "".join(
        f"<w:r><w:t>{_escape(run)}</w:t></w:r>" for run in spec.runs
    )
    if spec.hyperlink is not None:
        runs_xml = (
            f'<w:hyperlink r:id="{spec.hyperlink}">{runs_xml}</w:hyperlink>'
        )
    drawing_xml = ""
    if spec.image is not None:
        cx, cy = spec.extent
        drawing_xml = (
            "<w:r><w:drawing><wp:inline>"
            f'<wp:extent cx="{cx}" cy="{cy}"/>'
            "<a:graphic><a:graphicData><pic:pic><pic:blipFill>"
            f'<a:blip r:embed="{spec.image}"/>'
            "</pic:blipFill></pic:pic></a:graphicData></a:graphic>"
            "</wp:inline></w:drawing></w:r>"
        )
    return f"    <w:p>{properties}{runs_xml}{drawing_xml}</w:p>\n"


def _document_xml(paragraphs: Sequence[ParagraphSpec]) -> str:
    body = "".join(_paragraph_xml(spec) for spec in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<w:document xmlns:w="{WORD_NS}"\n'
        f' xmlns:r="{OFFICE_REL_NS}"\n'
        f' xmlns:wp="{WORD_DRAWING_NS}"\n'
        f' xmlns:a="{DRAWING_NS}"\n'
        f' xmlns:pic="{PICTURE_NS}">\n'
        "  <w:body>\n"
        f"{body}"
        "    <w:sectPr/>\n"
        "  </w:body>\n"
        "</w:document>\n"
    )


def _content_types_xml(media: Mapping[str, bytes]) -> str:
    extensions = sorted(
        {
            name.rsplit(".", 1)[-1].lower()
            for name in media
            if "." in name
        }
    )
    defaults = "".join(
        f'  <Default Extension="{extension}" ContentType='
        f'"{_EXTENSION_CONTENT_TYPES.get(extension, "application/octet-stream")}"/>\n'
        for extension in extensions
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">\n'
        '  <Default Extension="rels" ContentType='
        '"application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        f"{defaults}"
        '  <Override PartName="/word/document.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.wordprocessingml'
        '.document.main+xml"/>\n'
        "</Types>\n"
    )


_ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006'
    '/relationships">\n'
    '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>\n'
    "</Relationships>\n"
)


def _document_rels_xml(relationships: Sequence[RelationshipSpec]) -> str:
    entries = "".join(
        f'  <Relationship Id="{item.id}" '
        f'Type="{_RELATIONSHIP_TYPES[item.kind]}" '
        f'Target="{item.target}"'
        + (' TargetMode="External"' if item.external else "")
        + "/>\n"
        for item in relationships
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">\n'
        f"{entries}"
        "</Relationships>\n"
    )


def build_docx(
    path: Path,
    *,
    paragraphs: Sequence[ParagraphSpec],
    media: Mapping[str, bytes] | None = None,
    relationships: Sequence[RelationshipSpec] = (),
) -> Path:
    media = media or {}
    parts: dict[str, bytes] = {
        "[Content_Types].xml": _content_types_xml(media).encode("utf-8"),
        "_rels/.rels": _ROOT_RELS_XML.encode("utf-8"),
        "word/document.xml": _document_xml(paragraphs).encode("utf-8"),
        "word/_rels/document.xml.rels": _document_rels_xml(
            relationships
        ).encode("utf-8"),
    }
    for name, data in media.items():
        parts[f"word/{name}"] = data

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as package:
        for name, data in parts.items():
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = ZIP_STORED
            info.external_attr = 0o600 << 16
            package.writestr(info, data)
    return path
