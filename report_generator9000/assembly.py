"""Assemble every engagement deliverable in one self-contained directory."""

from __future__ import annotations

import hashlib
import tempfile
from io import BytesIO
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from .artifact_paths import engagement_artifact_key
from .block_stamping import BlockImage, stamp_blocks
from .capture import (
    CaptureRun,
    capture_config_from_master,
    capture_site,
    extract_site_text,
)
from .control_sheet import Engagement
from .docx_package import open_docx_package
from .generate import (
    GeneratedReport,
    StopCondition,
    _write_sidecars,
    generate_report,
)
from .gates import run_gates
from .gated_inputs import (
    GATED_IMAGE_PARTS,
    GatedInputError,
    load_gated_inputs,
)
from .lista_paginas import Pagina, derive_lista_paginas
from .logo import LogoCapture, capture_client_logo
from .palette import PaletteCollectionError, derive_palette_from_site
from .prose import ProseConfig, ProseProvider
from .placeholders import render_placeholder
from .previews import DocumentPreviewRenderer, PreviewRenderer
from .run_context import Pendencia


@dataclass(frozen=True)
class OutputPackage:
    engagement: Engagement
    directory: Path
    report: GeneratedReport
    pages: tuple[Pagina, ...]
    capture_run: CaptureRun
    previews: tuple[Path, ...]
    raw_captures: tuple[Path, ...]


def _assemble_staged_package(
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
    """Build an engagement package below a disposable staging root."""
    directory = (
        Path(output_root) / engagement_artifact_key(engagement)
    ).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        gated = load_gated_inputs(gated_drop_root, engagement)
    except GatedInputError as error:
        raise StopCondition(f"STOP CONDITION: {error}") from error
    palette_part = next(
        part_name
        for slot, _filename, part_name in GATED_IMAGE_PARTS
        if slot == "paleta"
    )
    derived_palette = None
    if palette_part not in gated.images_by_part():
        try:
            derived_palette = derive_palette_from_site(
                engagement.capture_origin
            )
        except PaletteCollectionError as error:
            raise StopCondition(f"STOP CONDITION: {error}") from error
    pages = derive_lista_paginas(
        engagement.capture_origin,
        gated.declared_pages,
    )
    capture_config = capture_config_from_master(master)
    captures = capture_site(
        pages,
        directory / "capturas",
        config=capture_config,
    )
    client_logo = capture_client_logo(
        engagement.capture_origin,
        captures.folder,
    )
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
            derived_palette=derived_palette,
            client_logo=client_logo,
        )

    renderer = (
        DocumentPreviewRenderer()
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
        + (
            [client_logo.path.resolve()]
            if isinstance(client_logo, LogoCapture)
            else []
        )
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
    """Build, certify, then promote one self-contained engagement package."""
    output_root_path = Path(output_root).resolve()
    output_root_path.mkdir(parents=True, exist_ok=True)
    key = engagement_artifact_key(engagement)
    final_directory = output_root_path / key

    with tempfile.TemporaryDirectory(
        prefix=f".{key}-assembly-",
        dir=output_root_path,
    ) as temporary:
        staging_root = Path(temporary)
        staged = _assemble_staged_package(
            master,
            staging_root,
            engagement,
            gated_drop_root,
            prose_provider=prose_provider,
            prose_config=prose_config,
            no_llm=no_llm,
            preview_renderer=preview_renderer,
        )

        def promoted(path: str | Path) -> Path:
            relative = Path(path).resolve().relative_to(staged.directory)
            return (final_directory / relative).resolve()

        final_document = promoted(staged.report.document)
        final_context_document = promoted(
            staged.report.context_document
        )
        final_pendencias_document = promoted(
            staged.report.pendencias_document
        )
        final_pendencias_json = promoted(staged.report.pendencias_json)
        final_previews = tuple(promoted(path) for path in staged.previews)
        final_raw_captures = tuple(
            promoted(path) for path in staged.raw_captures
        )
        final_capture_folder = promoted(staged.capture_run.folder)
        final_media = tuple(
            replace(
                artifact,
                source=str(promoted(artifact.source)),
            )
            if artifact.origin == "capture" and artifact.source is not None
            else artifact
            for artifact in staged.report.context.media
        )
        final_context = replace(
            staged.report.context,
            media=final_media,
            capture_folder=str(final_capture_folder),
            output_paths=tuple(
                str(path)
                for path in (
                    final_document,
                    final_context_document,
                    final_pendencias_document,
                    final_pendencias_json,
                    *final_previews,
                    *final_raw_captures,
                )
            ),
        )
        package = open_docx_package(staged.report.document)
        gate_report = run_gates(package, final_context)
        if not gate_report.passed:
            raise StopCondition(
                "STOP CONDITION: correctness gates rejected the staged "
                "output package:\n"
                + gate_report.format()
            )
        _write_sidecars(staged.report.document, final_context)

        previous_directory = staging_root / ".previous-output"
        replaced_previous = final_directory.exists()
        if replaced_previous:
            final_directory.replace(previous_directory)
        try:
            staged.directory.replace(final_directory)
        except OSError:
            if replaced_previous and not final_directory.exists():
                previous_directory.replace(final_directory)
            raise

        final_report = replace(
            staged.report,
            document=final_document,
            context=final_context,
            context_document=final_context_document,
            pendencias_document=final_pendencias_document,
            pendencias_json=final_pendencias_json,
            gate_report=gate_report,
        )
        final_capture_run = replace(
            staged.capture_run,
            folder=final_capture_folder,
            captures=tuple(
                replace(
                    capture,
                    raw_path=promoted(capture.raw_path),
                    embedding_path=promoted(capture.embedding_path),
                )
                for capture in staged.capture_run.captures
            ),
            failures=tuple(
                replace(
                    failure,
                    raw_path=(
                        None
                        if failure.raw_path is None
                        else promoted(failure.raw_path)
                    ),
                )
                for failure in staged.capture_run.failures
            ),
        )
        return OutputPackage(
            engagement=engagement,
            directory=final_directory,
            report=final_report,
            pages=staged.pages,
            capture_run=final_capture_run,
            previews=final_previews,
            raw_captures=final_raw_captures,
        )


__all__ = [
    "OutputPackage",
    "PreviewRenderer",
    "assemble_output_package",
]
