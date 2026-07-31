"""Read a DOCX as an OPC package, retaining structure and relationships."""

from __future__ import annotations

import hashlib
import posixpath
import re
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree


RELATIONSHIPS_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
CONTENT_TYPES_NS = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WORD_DRAWING_NS = (
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
)
MARKUP_COMPATIBILITY_NS = (
    "http://schemas.openxmlformats.org/markup-compatibility/2006"
)
PICTURE_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"

NAMESPACES = {
    "a": DRAWING_NS,
    "r": OFFICE_REL_NS,
    "w": WORD_NS,
    "wp": WORD_DRAWING_NS,
}
TWIP_TO_EMU = 635
CM_TO_EMU = 360_000

# The reporter measured a Capture bleeding past the bottom margin even after
# every derivable reservation (heading, caption, paragraph spacing) was
# subtracted from the usable page height -- Word's own layout slop (widow
# control, running header band, line-height rounding) still ate into the
# page. 22.5 cm is that measured ceiling: it caps the returned height
# regardless of what the geometry computation below yields.
BLOCK_EMBEDDING_HEIGHT_CEILING_EMU = int(22.5 * CM_TO_EMU)

_NAMESPACE_PREFIXES = (
    ("mc", MARKUP_COMPATIBILITY_NS),
    ("o", "urn:schemas-microsoft-com:office:office"),
    ("r", OFFICE_REL_NS),
    ("v", "urn:schemas-microsoft-com:vml"),
    ("w", WORD_NS),
    ("w10", "urn:schemas-microsoft-com:office:word"),
    ("w14", "http://schemas.microsoft.com/office/word/2010/wordml"),
    ("w15", "http://schemas.microsoft.com/office/word/2012/wordml"),
    ("wp", WORD_DRAWING_NS),
    ("wp14", "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"),
    ("wpg", "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"),
    ("wps", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"),
    ("a", DRAWING_NS),
    ("pic", PICTURE_NS),
)

for _prefix, _namespace_uri in _NAMESPACE_PREFIXES:
    ElementTree.register_namespace(_prefix, _namespace_uri)

# Deliberately not registered here: `ElementTree.register_namespace("", uri)`
# only ever holds one URI under the empty prefix -- registering a second
# default-namespace URI silently evicts the first (its own docstring: "any
# existing mapping for either the given prefix or the namespace URI will be
# removed"). `[Content_Types].xml` and every `.rels` part each want the bare
# `xmlns="..."` form for a *different* URI, so `serialize_xml` flattens
# whichever auto-assigned `nsN` prefix ElementTree chose back to the bare
# default per part instead, driven by what the original part declared.


def _root_namespace_declarations(data: bytes) -> tuple[tuple[str, str], ...]:
    declarations: list[tuple[str, str]] = []
    for event, value in ElementTree.iterparse(
        BytesIO(data), events=("start-ns", "start")
    ):
        if event == "start-ns":
            declarations.append(value)
        else:
            break
    return tuple(declarations)


def _flatten_to_default_namespace(text: str, uri: str) -> str:
    """Rewrite whichever auto-assigned `nsN` prefix ElementTree gave *uri*.

    `ElementTree.register_namespace("", uri)` can only ever hold one URI
    under the empty prefix at a time (registering a second evicts the
    first), so a part whose original root used a bare `xmlns="uri"` with no
    surviving global registration serializes with an auto-assigned `nsN`
    prefix instead. This restores the bare default form the part actually
    had, driven by what its own original bytes declared rather than by a
    single global mapping.
    """
    if f'xmlns="{uri}"' in text:
        return text
    match = re.search(rf'xmlns:(ns\d+)="{re.escape(uri)}"', text)
    if match is None:
        return text
    prefix = match.group(1)
    text = text.replace(f'xmlns:{prefix}="{uri}"', f'xmlns="{uri}"')
    return re.sub(rf"(?<=[<\s/]){re.escape(prefix)}:", "", text)


def preserve_namespace_declarations(serialized: bytes, original: bytes) -> bytes:
    """Reinject any xmlns declaration *original*'s root carried that *serialized* lost.

    ``ElementTree.tostring`` only emits a namespace declaration for a URI some
    surviving element or attribute in the tree still uses. A declaration that
    exists solely so an ``mc:Ignorable`` token (or any other out-of-band
    reference) resolves is silently dropped on re-serialization -- the exact
    defect that made ``xmlns:w15`` vanish from a rebuilt ``word/document.xml``
    while its value stayed listed in ``mc:Ignorable``. Restoring the original
    declarations keeps every such reference resolvable. This also restores
    any bare default namespace ElementTree could not honor (see
    `_flatten_to_default_namespace`).
    """
    declared = _root_namespace_declarations(original)
    if not declared:
        return serialized
    text = serialized.decode("utf-8")
    for prefix, uri in declared:
        if not prefix:
            text = _flatten_to_default_namespace(text, uri)
    root_start = text.index("<", text.index("?>") + 2 if text.startswith("<?") else 0)
    tag_end = text.index(">", root_start)
    self_closing = text[tag_end - 1] == "/"
    insertion_point = tag_end - 1 if self_closing else tag_end
    root_tag = text[:insertion_point]
    additions = "".join(
        f' {attribute}="{uri}"'
        for prefix, uri in declared
        for attribute in (f"xmlns:{prefix}" if prefix else "xmlns",)
        if f'{attribute}="{uri}"' not in root_tag
    )
    if not additions:
        return text.encode("utf-8")
    return (
        text[:insertion_point] + additions + text[insertion_point:]
    ).encode("utf-8")


def serialize_xml(element: ElementTree.Element, original: bytes) -> bytes:
    """Serialize *element*, keeping *original*'s namespace declarations intact."""
    serialized = ElementTree.tostring(
        element, encoding="utf-8", xml_declaration=True
    )
    return preserve_namespace_declarations(serialized, original)


def text_column_width_emu(document: ElementTree.Element) -> int:
    """Return the body text column width, in EMU, from the document's sectPr."""
    return page_geometry_emu(document).text_width_emu


@dataclass(frozen=True)
class PageGeometry:
    """The Master's page box expressed in Word's EMU drawing unit."""

    page_width_emu: int
    page_height_emu: int
    left_margin_emu: int
    right_margin_emu: int
    top_margin_emu: int
    bottom_margin_emu: int

    @property
    def text_width_emu(self) -> int:
        return (
            self.page_width_emu
            - self.left_margin_emu
            - self.right_margin_emu
        )

    @property
    def usable_height_emu(self) -> int:
        return (
            self.page_height_emu
            - self.top_margin_emu
            - self.bottom_margin_emu
        )


def page_geometry_emu(document: ElementTree.Element) -> PageGeometry:
    """Read the body section's page size and margins without assuming A4."""
    w = f"{{{WORD_NS}}}"
    section_properties = document.find(f"{w}body/{w}sectPr")
    if section_properties is None:
        section_properties = next(document.iter(f"{w}sectPr"), None)
    if section_properties is None:
        raise ValueError("document has no sectPr")
    page_size = section_properties.find(f"{w}pgSz")
    margins = section_properties.find(f"{w}pgMar")
    if page_size is None or margins is None:
        raise ValueError("sectPr lacks pgSz or pgMar")
    required = {
        "page width": page_size.get(f"{w}w"),
        "page height": page_size.get(f"{w}h"),
        "left margin": margins.get(f"{w}left"),
        "right margin": margins.get(f"{w}right"),
        "top margin": margins.get(f"{w}top"),
        "bottom margin": margins.get(f"{w}bottom"),
    }
    if any(value is None for value in required.values()):
        missing = ", ".join(
            label for label, value in required.items() if value is None
        )
        raise ValueError(f"sectPr lacks {missing}")
    values = {label: int(value) for label, value in required.items()}
    geometry = PageGeometry(
        page_width_emu=values["page width"] * TWIP_TO_EMU,
        page_height_emu=values["page height"] * TWIP_TO_EMU,
        left_margin_emu=values["left margin"] * TWIP_TO_EMU,
        right_margin_emu=values["right margin"] * TWIP_TO_EMU,
        top_margin_emu=values["top margin"] * TWIP_TO_EMU,
        bottom_margin_emu=values["bottom margin"] * TWIP_TO_EMU,
    )
    if geometry.text_width_emu <= 0 or geometry.usable_height_emu <= 0:
        raise ValueError("sectPr page margins leave no usable page area")
    return geometry


def _style_chain(
    paragraph: ElementTree.Element,
    styles: ElementTree.Element | None,
    w: str,
) -> list[ElementTree.Element]:
    """Return *paragraph*'s style ancestry, nearest first, following basedOn."""
    if styles is None:
        return []
    styles_by_id = {
        item.get(f"{w}styleId"): item for item in styles.findall(f"{w}style")
    }
    style_id_node = paragraph.find(f"{w}pPr/{w}pStyle")
    style_id = (
        style_id_node.get(f"{w}val") if style_id_node is not None else None
    )
    chain: list[ElementTree.Element] = []
    visited: set[str] = set()
    while style_id and style_id not in visited:
        visited.add(style_id)
        style = styles_by_id.get(style_id)
        if style is None:
            break
        chain.append(style)
        based_on = style.find(f"{w}basedOn")
        style_id = based_on.get(f"{w}val") if based_on is not None else None
    return chain


def _inherited_spacing(
    paragraph: ElementTree.Element,
    style_chain: list[ElementTree.Element],
    attribute: str,
    w: str,
) -> int:
    """Return *paragraph*'s inherited ``w:spacing`` attribute, in twips."""
    direct_spacing = paragraph.find(f"{w}pPr/{w}spacing")
    if direct_spacing is not None:
        value = direct_spacing.get(f"{w}{attribute}")
        if value is not None:
            return int(value)
    for style in style_chain:
        element = style.find(f"{w}pPr/{w}spacing")
        if element is not None:
            value = element.get(f"{w}{attribute}")
            if value is not None:
                return int(value)
    return 0


def _paragraph_flow_height_emu(
    paragraph: ElementTree.Element,
    styles: ElementTree.Element | None,
    w: str,
) -> int:
    """Return the vertical footprint *paragraph* reserves on the page.

    This is spacing-before + one line of text at the paragraph's effective
    font size + spacing-after, resolved through the paragraph's own direct
    formatting, its style's ``basedOn`` chain, and the styles part's
    ``docDefaults`` -- the same resolution order Word itself uses.
    """
    style_chain = _style_chain(paragraph, styles, w)
    before = _inherited_spacing(paragraph, style_chain, "before", w)
    after = _inherited_spacing(paragraph, style_chain, "after", w)
    explicit_line = _inherited_spacing(paragraph, style_chain, "line", w)
    inherited_font_size = next(
        (
            int(size)
            for style in style_chain
            for size_node in style.findall(f"{w}rPr/{w}sz")
            if (size := size_node.get(f"{w}val")) is not None
        ),
        None,
    )
    default_font_sizes = (
        [
            int(size)
            for size_node in styles.findall(
                f"{w}docDefaults/{w}rPrDefault/{w}rPr/{w}sz"
            )
            if (size := size_node.get(f"{w}val")) is not None
        ]
        if styles is not None
        else []
    )
    style_font_size = (
        inherited_font_size
        if inherited_font_size is not None
        else max(default_font_sizes or [24])
    )
    run_font_sizes = []
    for run in paragraph.iter(f"{w}r"):
        size_node = run.find(f"{w}rPr/{w}sz")
        size = size_node.get(f"{w}val") if size_node is not None else None
        run_font_sizes.append(
            int(size) if size is not None else style_font_size
        )
    effective_font_size = max(run_font_sizes or [style_font_size])
    line_height_twips = max(explicit_line, effective_font_size * 10)
    return (before + line_height_twips + after) * TWIP_TO_EMU


def block_embedding_box_emu(
    document: ElementTree.Element,
    styles: ElementTree.Element | None = None,
) -> tuple[int, int]:
    """Return the Block Slot width and one-page image-height cap.

    The cap reserves space for everything that sits above the image within
    its own Block -- the heading and, if the Master ever grows one, a
    caption paragraph between heading and image -- plus the paragraph
    spacing Word inserts immediately above the image itself. It is then
    clamped to the empirically measured ceiling below.
    """
    w = f"{{{WORD_NS}}}"
    wp = f"{{{WORD_DRAWING_NS}}}"
    body = document.find(f"{w}body")
    if body is None:
        raise ValueError("document has no body")
    children = list(body)
    heading_index = next(
        (
            index
            for index, paragraph in enumerate(children)
            if paragraph.find(
                f"{w}bookmarkStart[@{w}name='MASTER_BLOCK_STAMP']"
            )
            is not None
        ),
        None,
    )
    if heading_index is None or heading_index + 1 >= len(children):
        raise ValueError("MASTER_BLOCK_STAMP is incomplete")
    image_index = next(
        (
            index
            for index in range(heading_index + 1, len(children))
            if children[index].find(f".//{wp}extent") is not None
        ),
        None,
    )
    if image_index is None:
        raise ValueError("MASTER_BLOCK_STAMP has no image extent")
    image_paragraph = children[image_index]
    extent = image_paragraph.find(f".//{wp}extent")
    if extent is None or extent.get("cx") is None:
        raise ValueError("MASTER_BLOCK_STAMP has no image extent")

    # Everything from the heading up to (but excluding) the image paragraph
    # sits above the Capture and must be reserved -- the heading itself, and
    # any caption paragraph(s) between heading and image.
    above_image_height_emu = sum(
        _paragraph_flow_height_emu(paragraph, styles, w)
        for paragraph in children[heading_index:image_index]
    )
    # The gap Word inserts between that text and the image is the image
    # paragraph's own spacing-before -- its line height is the image being
    # sized, so only its "before" spacing belongs to the reservation.
    image_spacing_before_emu = (
        _inherited_spacing(
            image_paragraph,
            _style_chain(image_paragraph, styles, w),
            "before",
            w,
        )
        * TWIP_TO_EMU
    )
    reserved_height_emu = above_image_height_emu + image_spacing_before_emu
    computed_max_height_emu = (
        page_geometry_emu(document).usable_height_emu - reserved_height_emu
    )
    if computed_max_height_emu <= 0:
        raise ValueError("Block heading leaves no usable image height")
    max_height_emu = min(
        computed_max_height_emu, BLOCK_EMBEDDING_HEIGHT_CEILING_EMU
    )
    return int(extent.get("cx")), max_height_emu


@dataclass(frozen=True)
class Part:
    name: str
    size: int
    text: str | None = None


@dataclass(frozen=True)
class Media:
    part_name: str
    sha256: str
    width: int
    height: int
    image_format: str


@dataclass(frozen=True)
class FontPart:
    part_name: str
    data: bytes


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
    keep_next: bool = False
    has_image: bool = False
    relationship_ids: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


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
    fonts: tuple[FontPart, ...] = ()


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


def _read_fonts(package: ZipFile, names: set[str]) -> tuple[FontPart, ...]:
    return tuple(
        FontPart(part_name=name, data=package.read(name))
        for name in sorted(item for item in names if "/fonts/" in f"/{item}")
    )


def _keep_next(paragraph_element: ElementTree.Element) -> bool:
    properties = paragraph_element.find(f"{{{WORD_NS}}}pPr")
    if properties is None:
        return False
    element = properties.find(f"{{{WORD_NS}}}keepNext")
    if element is None:
        return False
    value = element.get(f"{{{WORD_NS}}}val")
    if value is None:
        return True
    return value not in ("false", "0", "off")


def _has_image(paragraph_element: ElementTree.Element) -> bool:
    for blip in paragraph_element.iter(f"{{{DRAWING_NS}}}blip"):
        if (
            blip.get(f"{{{OFFICE_REL_NS}}}embed") is not None
            or blip.get(f"{{{OFFICE_REL_NS}}}link") is not None
        ):
            return True
    return False


def _relationship_ids(
    paragraph_element: ElementTree.Element,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value
            for element in paragraph_element.iter()
            for attribute, value in element.attrib.items()
            if attribute.startswith(f"{{{OFFICE_REL_NS}}}")
        )
    )


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
                    keep_next=_keep_next(paragraph_element),
                    has_image=_has_image(paragraph_element),
                    relationship_ids=_relationship_ids(paragraph_element),
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
            fonts = _read_fonts(package, names)
            paragraphs, slots = _read_structure(
                package, names, relationships
            )
            parts = tuple(
                Part(
                    name=item.filename,
                    size=item.file_size,
                    text=(
                        package.read(item.filename).decode(
                            "utf-8", errors="replace"
                        )
                        if item.filename.endswith((".xml", ".rels"))
                        else None
                    ),
                )
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
        fonts=fonts,
    )
