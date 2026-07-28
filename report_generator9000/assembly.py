"""Assemble every engagement deliverable in one self-contained directory."""

from __future__ import annotations

import tempfile
import textwrap
import hashlib
from io import BytesIO
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont

from .artifact_paths import engagement_artifact_key
from .block_stamping import BlockImage, stamp_blocks
from .capture import CaptureRun, capture_site, extract_site_text
from .control_sheet import Engagement
from .docx_package import open_docx_package
from .generate import (
    GeneratedReport,
    _write_sidecars,
    generate_report,
)
from .gated_inputs import load_gated_inputs
from .lista_paginas import Pagina, derive_lista_paginas
from .prose import ProseConfig, ProseProvider
from .placeholders import render_placeholder
from .run_context import Pendencia


class PreviewRenderer(Protocol):
    """Optional QA renderer; delivery never depends on headless office."""

    def render(
        self,
        document: Path,
        output_folder: Path,
    ) -> tuple[Path, ...]: ...


class TextPreviewRenderer:
    """Built-in PNG content previews requiring no office installation."""

    page_size = (1240, 1754)
    margin = 80

    def render(
        self,
        document: Path,
        output_folder: Path,
    ) -> tuple[Path, ...]:
        package = open_docx_package(document)
        lines = ["QA PREVIEW — confirme o layout final no Word", ""]
        for paragraph in package.paragraphs:
            text = paragraph.text.strip()
            if text:
                lines.extend(textwrap.wrap(text, width=82) or [""])
                lines.append("")
        output_folder.mkdir(parents=True, exist_ok=True)
        font = ImageFont.truetype(
            str(
                Path(__file__).parent
                / "assets"
                / "Montserrat-wght.ttf"
            ),
            25,
        )
        line_height = 36
        capacity = max(
            1,
            (self.page_size[1] - 2 * self.margin) // line_height,
        )
        pages = [
            lines[index : index + capacity]
            for index in range(0, len(lines), capacity)
        ] or [[]]
        rendered = []
        for index, page_lines in enumerate(pages, start=1):
            image = Image.new("RGB", self.page_size, "white")
            draw = ImageDraw.Draw(image)
            y = self.margin
            for line in page_lines:
                draw.text((self.margin, y), line, fill="black", font=font)
                y += line_height
            path = output_folder / f"preview-{index:03d}.png"
            image.save(path, format="PNG", optimize=True)
            rendered.append(path.resolve())
        return tuple(rendered)


@dataclass(frozen=True)
class OutputPackage:
    engagement: Engagement
    directory: Path
    report: GeneratedReport
    pages: tuple[Pagina, ...]
    capture_run: CaptureRun
    previews: tuple[Path, ...]
    raw_captures: tuple[Path, ...]


def assemble_output_package(
    master: str | Path,
    output_root: str | Path,
    engagement: Engagement,
    gated_drop_root: str | Path,
    *,
    prose_provider: ProseProvider | None = None,
    prose_config: ProseConfig | None = None,
    no_llm: bool = False,
    preview_renderer: PreviewRenderer | None = None,
) -> OutputPackage:
    """Run Lista, Capture, Blocks, prose, report, and sidecars once."""
    directory = (
        Path(output_root) / engagement_artifact_key(engagement)
    ).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    gated = load_gated_inputs(gated_drop_root, engagement)
    pages = derive_lista_paginas(
        engagement.capture_origin,
        gated.declared_pages,
    )
    captures = capture_site(pages, directory / "capturas")
    captures_by_page = {
        capture.pagina: capture for capture in captures.captures
    }
    failures_by_page = {
        failure.pagina: failure for failure in captures.failures
    }
    block_images_list: list[BlockImage] = []
    capture_pendencias: list[Pendencia] = [
        item for item in captures.pendencias
        if item.slot.startswith("capture:")
        and item.evidence not in {
            failure.pendencia.evidence for failure in captures.failures
        }
    ]
    for index, page in enumerate(pages, start=1):
        captured = captures_by_page.get(page)
        if captured is not None:
            block_images_list.append(
                BlockImage(
                    pagina=page,
                    path=captured.embedding_path,
                    digest=captured.embedding_digest,
                    origin="capture",
                )
            )
            continue
        failure = failures_by_page[page]
        base = Image.new("RGB", (1200, 675), "white")
        buffer = BytesIO()
        base.save(buffer, format="PNG")
        content = render_placeholder(
            buffer.getvalue(),
            "TOOL_BLOCKED",
            page.titulo_bloco,
            1200,
            675,
        )
        placeholder_path = (
            captures.folder
            / "embutir"
            / f"{index:02d}-tool-blocked.png"
        )
        placeholder_path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        block_images_list.append(
            BlockImage(
                pagina=page,
                path=placeholder_path,
                digest=digest,
                origin="placeholder",
            )
        )
        capture_pendencias.append(
            replace(failure.pendencia, evidence=digest)
        )
    block_images = tuple(block_images_list)
    site_text = (
        ()
        if no_llm
        else extract_site_text(pages)
    )

    with tempfile.TemporaryDirectory(
        prefix="assembly-",
        dir=directory,
    ) as temporary:
        stamped = stamp_blocks(
            master,
            Path(temporary) / "stamped-master.docx",
            pages,
            block_images,
            capture_folder=captures.folder,
            drop_folder=gated.folder,
        )
        generated = generate_report(
            stamped.document,
            output_root,
            engagement,
            gated_drop_root,
            pages=pages,
            site_text=site_text,
            prose_provider=prose_provider,
            prose_config=prose_config,
            no_llm=no_llm,
            run_artifacts=stamped.artifacts,
            blocks=stamped.headings,
            capture_folder=captures.folder,
            run_pendencias=tuple(capture_pendencias),
        )

    renderer = (
        TextPreviewRenderer()
        if preview_renderer is None
        else preview_renderer
    )
    previews = renderer.render(
        generated.document,
        directory / "previews",
    )
    raw_captures = tuple(
        [
            capture.raw_path.resolve()
            for capture in captures.captures
        ]
        + [
            failure.raw_path.resolve()
            for failure in captures.failures
            if failure.raw_path is not None
        ]
    )
    output_paths = (
        generated.document.resolve(),
        generated.context_document.resolve(),
        generated.pendencias_document.resolve(),
        generated.pendencias_json.resolve(),
        *previews,
        *raw_captures,
    )
    context = replace(
        generated.context,
        output_paths=tuple(str(path) for path in output_paths),
    )
    context_path, pendencias_document, pendencias_json = _write_sidecars(
        generated.document,
        context,
    )
    report = replace(
        generated,
        context=context,
        context_document=context_path,
        pendencias_document=pendencias_document,
        pendencias_json=pendencias_json,
    )
    return OutputPackage(
        engagement=engagement,
        directory=directory,
        report=report,
        pages=pages,
        capture_run=captures,
        previews=previews,
        raw_captures=raw_captures,
    )


__all__ = [
    "OutputPackage",
    "PreviewRenderer",
    "TextPreviewRenderer",
    "assemble_output_package",
]
