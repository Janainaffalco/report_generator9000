"""Read a DOCX as an OPC package, retaining structure and relationships."""

from __future__ import annotations

import hashlib
import posixpath
import struct
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree


RELATIONSHIPS_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WORD_DRAWING_NS = (
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
)

NAMESPACES = {
    "a": DRAWING_NS,
    "r": OFFICE_REL_NS,
    "w": WORD_NS,
    "wp": WORD_DRAWING_NS,
}


@dataclass(frozen=True)
class Part:
    name: str
    size: int


@dataclass(frozen=True)
class Media:
    part_name: str
    sha256: str
    width: int
    height: int
    image_format: str


@dataclass(frozen=True)
class Relationship:
    source_part: str
    relationship_id: str
    relationship_type: str
    target: str
    target_mode: str | None
    resolved_target: str | None

    @property
    def external(self) -> bool:
        return self.target_mode == "External"


@dataclass(frozen=True)
class Run:
    text: str
    relationship_ids: tuple[str, ...]


@dataclass(frozen=True)
class Paragraph:
    source_part: str
    index: int
    runs: tuple[Run, ...]


@dataclass(frozen=True)
class Slot:
    source_part: str
    paragraph_index: int
    run_index: int
    relationship_id: str
    media_part: str | None
    width_emu: int | None
    height_emu: int | None


@dataclass(frozen=True)
class DocxPackage:
    parts: tuple[Part, ...]
    media: tuple[Media, ...]
    relationships: tuple[Relationship, ...]
    paragraphs: tuple[Paragraph, ...]
    slots: tuple[Slot, ...]


def _relationship_source(relationship_part: str) -> str:
    if relationship_part == "_rels/.rels":
        return "/"
    directory, filename = posixpath.split(relationship_part)
    if not directory.endswith("/_rels") or not filename.endswith(".rels"):
        raise ValueError(f"invalid relationship part path: {relationship_part}")
    source_directory = directory.removesuffix("/_rels")
    return posixpath.join(source_directory, filename.removesuffix(".rels"))


def _resolve_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    base = "" if source_part == "/" else posixpath.dirname(source_part)
    return posixpath.normpath(posixpath.join(base, target))


def _read_relationships(
    package: ZipFile, names: set[str]
) -> tuple[Relationship, ...]:
    relationships = []
    for name in sorted(item for item in names if item.endswith(".rels")):
        source = _relationship_source(name)
        root = ElementTree.fromstring(package.read(name))
        for element in root.findall(f"{{{RELATIONSHIPS_NS}}}Relationship"):
            target_mode = element.get("TargetMode")
            target = element.attrib["Target"]
            relationships.append(
                Relationship(
                    source_part=source,
                    relationship_id=element.attrib["Id"],
                    relationship_type=element.attrib["Type"].rsplit("/", 1)[-1],
                    target=target,
                    target_mode=target_mode,
                    resolved_target=(
                        None
                        if target_mode == "External"
                        else _resolve_target(source, target)
                    ),
                )
            )
    return tuple(
        sorted(
            relationships,
            key=lambda item: (item.source_part, item.relationship_id),
        )
    )


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    return None


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    return None


def _bmp_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"BM") and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return width, abs(height)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    position = 2
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while position + 3 < len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(data):
            break
        segment_length = struct.unpack(">H", data[position : position + 2])[0]
        if segment_length < 2 or position + segment_length > len(data):
            break
        if marker in start_of_frame and segment_length >= 7:
            height, width = struct.unpack(
                ">HH", data[position + 3 : position + 7]
            )
            return width, height
        position += segment_length
    return None


def _image_dimensions(data: bytes) -> tuple[int, int, str]:
    readers = (
        ("PNG", _png_dimensions),
        ("JPEG", _jpeg_dimensions),
        ("GIF", _gif_dimensions),
        ("BMP", _bmp_dimensions),
    )
    for image_format, reader in readers:
        dimensions = reader(data)
        if dimensions is not None:
            return *dimensions, image_format
    raise ValueError("unsupported or corrupt image bytes")


def _read_media(package: ZipFile, names: set[str]) -> tuple[Media, ...]:
    media = []
    for name in sorted(
        item for item in names if "/media/" in f"/{item}"
    ):
        data = package.read(name)
        try:
            width, height, image_format = _image_dimensions(data)
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
        media.append(
            Media(
                part_name=name,
                sha256=hashlib.sha256(data).hexdigest(),
                width=width,
                height=height,
                image_format=image_format,
            )
        )
    return tuple(media)


def _read_structure(
    package: ZipFile,
    names: set[str],
    relationships: tuple[Relationship, ...],
) -> tuple[tuple[Paragraph, ...], tuple[Slot, ...]]:
    relationship_index = {
        (item.source_part, item.relationship_id): item
        for item in relationships
    }
    paragraphs = []
    slots = []
    for name in sorted(item for item in names if item.endswith(".xml")):
        try:
            root = ElementTree.fromstring(package.read(name))
        except ElementTree.ParseError:
            continue
        for paragraph_index, paragraph_element in enumerate(
            root.iter(f"{{{WORD_NS}}}p")
        ):
            runs = []
            for run_index, run_element in enumerate(
                paragraph_element.iter(f"{{{WORD_NS}}}r")
            ):
                text = "".join(
                    element.text or ""
                    for element in run_element.iter(f"{{{WORD_NS}}}t")
                )
                relationship_ids = tuple(
                    dict.fromkeys(
                        value
                        for element in run_element.iter()
                        for attribute, value in element.attrib.items()
                        if attribute.startswith(f"{{{OFFICE_REL_NS}}}")
                    )
                )
                runs.append(Run(text=text, relationship_ids=relationship_ids))
                extent = run_element.find(".//wp:extent", NAMESPACES)
                width_emu = (
                    int(extent.attrib["cx"]) if extent is not None else None
                )
                height_emu = (
                    int(extent.attrib["cy"]) if extent is not None else None
                )
                for blip in run_element.findall(".//a:blip", NAMESPACES):
                    relationship_id = blip.get(f"{{{OFFICE_REL_NS}}}embed")
                    if relationship_id is None:
                        relationship_id = blip.get(
                            f"{{{OFFICE_REL_NS}}}link"
                        )
                    if relationship_id is None:
                        continue
                    relationship = relationship_index.get(
                        (name, relationship_id)
                    )
                    slots.append(
                        Slot(
                            source_part=name,
                            paragraph_index=paragraph_index,
                            run_index=run_index,
                            relationship_id=relationship_id,
                            media_part=(
                                relationship.resolved_target
                                if relationship is not None
                                else None
                            ),
                            width_emu=width_emu,
                            height_emu=height_emu,
                        )
                    )
            paragraphs.append(
                Paragraph(
                    source_part=name,
                    index=paragraph_index,
                    runs=tuple(runs),
                )
            )
    return tuple(paragraphs), tuple(slots)


def open_docx_package(path: str | Path) -> DocxPackage:
    """Open *path* and return its package-level inventory."""
    document = Path(path)
    try:
        with ZipFile(document) as package:
            corrupt_part = package.testzip()
            if corrupt_part is not None:
                raise ValueError(f"corrupt DOCX part: {corrupt_part}")
            names = {
                item.filename
                for item in package.infolist()
                if not item.is_dir()
            }
            relationships = _read_relationships(package, names)
            media = _read_media(package, names)
            paragraphs, slots = _read_structure(
                package, names, relationships
            )
            parts = tuple(
                Part(name=item.filename, size=item.file_size)
                for item in sorted(
                    package.infolist(), key=lambda entry: entry.filename
                )
                if not item.is_dir()
            )
    except BadZipFile as error:
        raise ValueError(f"not a valid DOCX package: {document}") from error
    return DocxPackage(
        parts=parts,
        media=media,
        relationships=relationships,
        paragraphs=paragraphs,
        slots=slots,
    )
