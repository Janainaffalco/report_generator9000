"""Replace the Master's canonical Blocks with this run's Lista de Páginas."""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from PIL import Image

from .capture import fitted_emu_dimensions
from .lista_paginas import Pagina
from .master import (
    CONTENT_TYPES_NS,
    OFFICE_REL_NS,
    RELATIONSHIPS_NS,
    W,
    clone_block_stamp,
)
from .run_context import Artifact, is_within


WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = f"{{{OFFICE_REL_NS}}}"
REL = f"{{{RELATIONSHIPS_NS}}}"
CT = f"{{{CONTENT_TYPES_NS}}}"
_IMAGE_RELATIONSHIP = f"{OFFICE_REL_NS}/image"
_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class BlockStampingError(ValueError):
    """The Master and run inputs cannot produce trustworthy Blocks."""


@dataclass(frozen=True)
class BlockImage:
    """A Lista entry's image, with provenance declared by this run."""

    pagina: Pagina
    path: Path
    digest: str
    origin: str = "capture"

    @property
    def pixel_size(self) -> tuple[int, int]:
        with Image.open(self.path) as image:
            return image.size


@dataclass(frozen=True)
class StampedBlocks:
    document: Path
    headings: tuple[str, ...]
    artifacts: tuple[Artifact, ...]


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(item.text or "" for item in paragraph.iter(f"{W}t"))


def _next_relationship_id(used: set[str]) -> str:
    candidate = 1
    while f"rIdBlock{candidate}" in used:
        candidate += 1
    value = f"rIdBlock{candidate}"
    used.add(value)
    return value


def _set_image_extent(
    paragraph: ElementTree.Element,
    width: int,
    height: int,
) -> None:
    slot = paragraph.find(f".//{WP}extent")
    if slot is None:
        raise BlockStampingError("MASTER_BLOCK_STAMP has no image extent")
    fitted_width, fitted_height = fitted_emu_dimensions(
        int(slot.get("cx", "0")),
        width,
        height,
    )
    slot.set("cx", str(fitted_width))
    slot.set("cy", str(fitted_height))
    for extent in paragraph.iter(f"{A}ext"):
        if "cx" in extent.attrib and "cy" in extent.attrib:
            extent.set("cx", str(fitted_width))
            extent.set("cy", str(fitted_height))


def _ensure_content_type(parts: dict[str, bytes], suffix: str) -> None:
    content_type = _CONTENT_TYPES.get(suffix)
    if content_type is None:
        raise BlockStampingError(
            f"Block image format {suffix or '<none>'!r} is unsupported"
        )
    root = ElementTree.fromstring(parts["[Content_Types].xml"])
    extension = suffix.removeprefix(".")
    if not any(
        item.get("Extension", "").casefold() == extension
        for item in root.findall(f"{CT}Default")
    ):
        ElementTree.SubElement(
            root,
            f"{CT}Default",
            {"Extension": extension, "ContentType": content_type},
        )
        parts["[Content_Types].xml"] = ElementTree.tostring(
            root, encoding="utf-8", xml_declaration=True
        )


def _removed_relationship_media(
    document: ElementTree.Element,
    relationships: ElementTree.Element,
) -> set[str]:
    referenced = {
        value
        for element in document.iter()
        for attribute, value in element.attrib.items()
        if attribute.startswith(R)
    }
    removed_media: set[str] = set()
    for relationship in list(relationships.findall(f"{REL}Relationship")):
        relation_id = relationship.get("Id", "")
        if (
            relationship.get("Type") == _IMAGE_RELATIONSHIP
            and relation_id not in referenced
        ):
            target = relationship.get("Target", "")
            relationships.remove(relationship)
            if target and not any(
                other.get("Target") == target
                for other in relationships.findall(f"{REL}Relationship")
            ):
                removed_media.add(
                    posixpath.normpath(posixpath.join("word", target))
                )
    return removed_media


def _validate_inputs(
    pages: tuple[Pagina, ...],
    images: tuple[BlockImage, ...],
    capture_folder: str | Path | None,
    drop_folder: str | Path | None,
) -> tuple[bytes, ...]:
    if len(pages) != len(images):
        raise BlockStampingError(
            "Block image count must equal Lista de Páginas length"
        )
    headings = tuple(page.titulo_bloco for page in pages)
    if len(set(headings)) != len(headings):
        raise BlockStampingError("Lista de Páginas has duplicate Block headings")
    contents = []
    for index, (page, image) in enumerate(zip(pages, images), start=1):
        if image.pagina != page:
            raise BlockStampingError(
                f"Block image {index} does not match its Lista entry"
            )
        if image.origin not in {"capture", "gated", "placeholder"}:
            raise BlockStampingError(
                f"Block image {index} origin must be capture, gated, "
                "or placeholder"
            )
        source_root = (
            capture_folder
            if image.origin in {"capture", "placeholder"}
            else drop_folder
        )
        source_name = (
            "Capture folder"
            if image.origin in {"capture", "placeholder"}
            else "Gated Drop Folder"
        )
        if source_root is None or not is_within(
            str(image.path.resolve()),
            str(Path(source_root).resolve()),
        ):
            raise BlockStampingError(
                f"Block image {index} is outside this run's {source_name}"
            )
        try:
            content = image.path.read_bytes()
        except OSError as error:
            raise BlockStampingError(
                f"Block image {index} cannot be read: {error}"
            ) from error
        actual = hashlib.sha256(content).hexdigest()
        if actual.casefold() != image.digest.casefold():
            raise BlockStampingError(
                f"Block image {index} digest does not match its source"
            )
        try:
            image.pixel_size
        except (OSError, ValueError) as error:
            raise BlockStampingError(
                f"Block image {index} is not a readable image: {error}"
            ) from error
        contents.append(content)
    return tuple(contents)


def stamp_blocks(
    master: str | Path,
    output: str | Path,
    pages: tuple[Pagina, ...],
    images: tuple[BlockImage, ...],
    *,
    capture_folder: str | Path | None = None,
    drop_folder: str | Path | None = None,
) -> StampedBlocks:
    """Stamp exactly one bound Block for each ordered Lista entry."""
    contents = _validate_inputs(
        pages,
        images,
        capture_folder,
        drop_folder,
    )
    master_path = Path(master)
    destination = Path(output)
    try:
        with ZipFile(master_path) as archive:
            entries = tuple(
                (item, archive.read(item.filename))
                for item in archive.infolist()
            )
    except (BadZipFile, OSError, ValueError) as error:
        raise BlockStampingError(f"{master_path}: invalid Master: {error}") from error

    parts = {item.filename: content for item, content in entries}
    try:
        document = ElementTree.fromstring(parts["word/document.xml"])
        relationships = ElementTree.fromstring(
            parts["word/_rels/document.xml.rels"]
        )
    except (ElementTree.ParseError, KeyError) as error:
        raise BlockStampingError(
            "Master lacks a valid document relationship structure"
        ) from error

    body = document.find(f"{W}body")
    if body is None:
        raise BlockStampingError("Master document has no body")
    children = list(body)
    stamp_index = next(
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
    if stamp_index is None:
        raise BlockStampingError("MASTER_BLOCK_STAMP not found")
    boundary_index = next(
        (
            index
            for index, paragraph in enumerate(children)
            if index > stamp_index
            and _paragraph_text(paragraph).strip().casefold()
            == "painel de configuração wordpress"
        ),
        None,
    )
    if boundary_index is None:
        raise BlockStampingError("Block insertion boundary not found")
    original_region = children[stamp_index:boundary_index]

    used_relationship_ids = {
        item.get("Id", "")
        for item in relationships.findall(f"{REL}Relationship")
    }
    artifacts: list[Artifact] = []
    for index, (page, image, content) in enumerate(
        zip(pages, images, contents),
        start=1,
    ):
        suffix = image.path.suffix.casefold()
        _ensure_content_type(parts, suffix)
        target = f"media/block-{index:03d}{suffix}"
        part_name = f"word/{target}"
        relationship_id = _next_relationship_id(used_relationship_ids)
        ElementTree.SubElement(
            relationships,
            f"{REL}Relationship",
            {
                "Id": relationship_id,
                "Type": _IMAGE_RELATIONSHIP,
                "Target": target,
            },
        )
        _heading, image_paragraph = clone_block_stamp(
            document,
            page.titulo_bloco,
            relationship_id,
        )
        width, height = image.pixel_size
        _set_image_extent(image_paragraph, width, height)
        parts[part_name] = content
        artifacts.append(
            Artifact(
                digest=image.digest.casefold(),
                origin=image.origin,
                label=page.titulo_bloco,
                source=str(image.path.resolve()),
            )
        )

    for paragraph in original_region:
        body.remove(paragraph)
    for part_name in _removed_relationship_media(document, relationships):
        parts.pop(part_name, None)

    parts["word/document.xml"] = ElementTree.tostring(
        document, encoding="utf-8", xml_declaration=True
    )
    parts["word/_rels/document.xml.rels"] = ElementTree.tostring(
        relationships, encoding="utf-8", xml_declaration=True
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    original_names = {item.filename for item, _content in entries}
    with ZipFile(
        destination,
        "w",
        compression=ZIP_DEFLATED,
        compresslevel=9,
    ) as generated:
        for item, _content in entries:
            if item.filename in parts:
                generated.writestr(item, parts[item.filename])
        for name in sorted(set(parts) - original_names):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_DEFLATED
            generated.writestr(info, parts[name])
    return StampedBlocks(
        document=destination.resolve(),
        headings=tuple(page.titulo_bloco for page in pages),
        artifacts=tuple(artifacts),
    )


__all__ = [
    "BlockImage",
    "BlockStampingError",
    "StampedBlocks",
    "stamp_blocks",
]
