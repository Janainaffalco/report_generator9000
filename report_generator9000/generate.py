"""Clone the approved Master and fill control-sheet Tokens for an Engagement."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZipFile

from .artifact_paths import engagement_artifact_key
from .control_sheet import Engagement
from .docx_package import DocxPackage, open_docx_package
from .gates import GateReport, run_gates
from .gates.master import BOILERPLATE_MEDIA
from .gated_inputs import (
    GATED_IMAGE_PARTS,
    GATED_VALUE_SLOTS,
    GatedInputError,
    load_gated_inputs,
)
from .placeholders import render_placeholder, slot_pixel_dimensions
from .prose import (
    ExtractedPageText,
    ProseBudgetExceeded,
    ProseConfig,
    ProseProvider,
    draft_prose,
)
from .lista_paginas import Pagina, derive_lista_paginas
from .palette import PaletteDerivation, render_palette
from .run_context import Artifact, Grounding, Pendencia, RunContext


SPREADSHEET_TOKENS = {
    "{{DEMANDA}}": "demanda",
    "{{RAZAO_SOCIAL}}": "razao_social",
    "{{CNPJ}}": "cnpj",
    "{{ESPECIALISTA}}": "especialista",
    "{{DATA_KICKOFF}}": "kick_off_br",
}
@dataclass(frozen=True)
class GeneratedReport:
    """One report artifact produced for an Engagement."""

    engagement: Engagement
    document: Path
    context: RunContext
    context_document: Path
    pendencias_document: Path
    pendencias_json: Path
    gate_report: GateReport

    @property
    def ready_to_send(self) -> bool:
        return self.context.ready_to_send

    @property
    def status(self) -> str:
        return self.context.status


class ReportGenerationError(ValueError):
    """The Master cannot safely produce the requested report."""

    def __init__(
        self,
        message: str,
        *,
        pendencia: Pendencia | None = None,
    ) -> None:
        super().__init__(message)
        self.pendencia = pendencia


class StopCondition(ReportGenerationError):
    """A gate rejected the staged package, so the row produces nothing."""


def _media_location(
    package: DocxPackage, part_name: str
) -> tuple[str, str]:
    """Return the structural Slot and nearest human-readable page heading."""
    media_slots = [
        slot for slot in package.slots if slot.media_part == part_name
    ]
    if not media_slots:
        return f"capture:{part_name}", part_name
    media_slot = media_slots[0]
    preceding = [
        paragraph
        for paragraph in package.paragraphs
        if paragraph.source_part == media_slot.source_part
        and paragraph.index < media_slot.paragraph_index
        and paragraph.keep_next
        and paragraph.text.strip()
    ]
    page = preceding[-1].text.strip() if preceding else part_name
    slot = (
        f"{media_slot.source_part}:p={media_slot.paragraph_index}:"
        f"r={media_slot.run_index}"
    )
    return slot, page


def _placeholder_pixel_dimensions(
    package: DocxPackage, part_name: str
) -> tuple[int, int]:
    media_slot = next(
        (
            slot
            for slot in package.slots
            if slot.media_part == part_name
            and slot.width_emu is not None
            and slot.height_emu is not None
        ),
        None,
    )
    if media_slot is not None:
        return slot_pixel_dimensions(
            media_slot.width_emu, media_slot.height_emu
        )
    media = next(
        item for item in package.media if item.part_name == part_name
    )
    return media.width, media.height


def report_output_path(output_root: str | Path, engagement: Engagement) -> Path:
    """Return the collision-safe path keyed by Pasta and Razao Social."""
    key = engagement_artifact_key(engagement)
    return (
        Path(output_root)
        / key
        / f"RELATÓRIO TÉCNICO FINAL - {key}.docx"
    )


def _context_document(context: RunContext) -> dict[str, object]:
    return {
        "pasta": context.pasta,
        "media": [asdict(item) for item in context.media],
        "boilerplate_links": sorted(context.boilerplate_links),
        "input_origins": sorted(context.input_origins),
        "drop_folder": context.drop_folder,
        "capture_folder": context.capture_folder,
        "output_paths": list(context.output_paths),
        "blocks": list(context.blocks),
        "pendencias": [asdict(item) for item in context.pendencias],
        "prose_grounding": [
            asdict(item) for item in context.prose_grounding
        ],
    }


def _write_sidecars(
    output: Path, context: RunContext
) -> tuple[Path, Path, Path]:
    context_path = output.with_name("run.json")
    pendencias_json = output.with_name("pendencias.json")
    pendencias_document = output.with_name("PENDENCIAS.md")
    context_path.write_text(
        json.dumps(
            _context_document(context), ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    public_pendencias = [
        {
            "slot": item.slot,
            "name": item.name,
            "page": item.page,
            "class": item.classification,
            "reason": item.reason,
            "required_action": item.required_action,
            "evidence": item.evidence,
        }
        for item in context.pendencias
    ]
    pendencias_json.write_text(
        json.dumps(
            {
                "status": context.status,
                "ready_to_send": context.ready_to_send,
                "pendencias": public_pendencias,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# PEND\u00caNCIAS",
        "",
        (
            "Estado: **COMPLETO** — nenhuma Pendência registrada."
            if context.ready_to_send
            else "Estado: **RASCUNHO** — existem Pendências a resolver."
        ),
        "",
    ]
    if public_pendencias:
        lines.extend(
            (
                "| Slot | Nome | Página | Classe | Motivo | Ação necessária |",
                "| --- | --- | --- | --- | --- | --- |",
            )
        )
        lines.extend(
            f"| {item.slot} | {item.name} | {item.page} | "
            f"{item.classification} | {item.reason} | "
            f"{item.required_action} |"
            for item in context.pendencias
        )
    pendencias_document.write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return context_path, pendencias_document, pendencias_json


def generate_report(
    master: str | Path,
    output_root: str | Path,
    engagement: Engagement,
    gated_drop_root: str | Path | None = None,
    *,
    pages: tuple[Pagina, ...] | None = None,
    site_text: tuple[ExtractedPageText, ...] = (),
    prose_provider: ProseProvider | None = None,
    prose_config: ProseConfig | None = None,
    no_llm: bool = False,
    run_artifacts: tuple[Artifact, ...] = (),
    blocks: tuple[str, ...] = (),
    capture_folder: str | Path | None = None,
    run_pendencias: tuple[Pendencia, ...] = (),
    derived_palette: PaletteDerivation | None = None,
) -> GeneratedReport:
    """Clone *master* and fill spreadsheet and available Gated Inputs."""
    master_path = Path(master)
    output = report_output_path(output_root, engagement)
    try:
        gated = load_gated_inputs(
            Path("gated") if gated_drop_root is None else gated_drop_root,
            engagement,
        )
    except GatedInputError as error:
        raise ReportGenerationError(str(error)) from error

    selected_pages = (
        derive_lista_paginas(
            engagement.capture_origin,
            gated.declared_pages,
        )
        if pages is None
        else pages
    )
    try:
        drafted = draft_prose(
            selected_pages,
            site_text,
            prose_provider,
            prose_config,
            no_llm=no_llm,
        )
    except ProseBudgetExceeded as error:
        raise StopCondition(
            "STOP CONDITION: prose provider exhausted its output budget",
            pendencia=error.pendencia,
        ) from error
    except ValueError as error:
        raise ReportGenerationError(str(error)) from error

    replacement_text = {
        token: str(getattr(engagement, field))
        for token, field in SPREADSHEET_TOKENS.items()
    }
    supplied_gated_values = gated.values_by_token()
    replacement_text.update(supplied_gated_values)
    pendencias: list[Pendencia] = [
        *run_pendencias,
        *drafted.pendencias,
    ]
    replacement_text.update(drafted.token_values)
    for slot, tokens in GATED_VALUE_SLOTS:
        if all(token in supplied_gated_values for token in tokens):
            continue
        evidence = f"[PEND\u00caNCIA GATED: {slot}]"
        replacement_text.update({token: evidence for token in tokens})
        pendencias.append(
            Pendencia(
                slot=slot,
                classification="GATED",
                reason="valor nao fornecido no Gated Drop Folder",
                evidence=evidence,
                name=slot.replace("_", " "),
                page="documento",
                required_action=(
                    f"Fornecer {slot.replace('_', ' ')} no valores.json"
                ),
            )
        )
    values = {
        token: escape(value).encode("utf-8")
        for token, value in replacement_text.items()
    }
    token_bytes = {token: token.encode("ascii") for token in values}

    try:
        with ZipFile(master_path) as archive:
            entries = [
                (item, archive.read(item.filename))
                for item in archive.infolist()
            ]
    except (BadZipFile, OSError, ValueError) as error:
        raise ReportGenerationError(
            f"{master_path}: invalid Master: {error}"
        ) from error

    parts = {item.filename: content for item, content in entries}
    try:
        master_package = open_docx_package(master_path)
    except (OSError, ValueError) as error:
        raise ReportGenerationError(
            f"{master_path}: invalid Master package: {error}"
        ) from error
    artifacts: list[Artifact] = []
    run_artifacts_by_digest: dict[str, list[Artifact]] = {}
    for artifact in run_artifacts:
        run_artifacts_by_digest.setdefault(
            artifact.digest.casefold(), []
        ).append(artifact)
    used_run_artifacts: set[Artifact] = set()
    palette_grounding: list[Grounding] = []
    claimed_media_parts: set[str] = set()
    supplied_images = gated.images_by_part()
    for slot, _filename, part_name in GATED_IMAGE_PARTS:
        supplied = supplied_images.get(part_name)
        if part_name not in parts:
            if supplied is not None:
                raise ReportGenerationError(
                    f"Master lacks Gated image Slot {slot!r} ({part_name})"
                )
            continue
        claimed_media_parts.add(part_name)
        if supplied is not None:
            _source_slot, source_path = supplied
            content = source_path.read_bytes()
            parts[part_name] = content
            artifacts.append(
                Artifact(
                    digest=hashlib.sha256(content).hexdigest(),
                    origin="gated",
                    label=slot,
                    source=str(source_path.resolve()),
                )
            )
        elif slot == "paleta" and (
            derived_palette is not None and derived_palette.colors
        ):
            width, height = _placeholder_pixel_dimensions(
                master_package, part_name
            )
            content = render_palette(
                tuple(color.hex for color in derived_palette.colors),
                width=width,
                height=height,
            )
            parts[part_name] = content
            palette_digest = hashlib.sha256(content).hexdigest()
            artifacts.append(
                Artifact(
                    digest=palette_digest,
                    origin="derived",
                    label=slot,
                )
            )
            palette_grounding.extend(
                Grounding(
                    field=f"paleta:{color.hex}",
                    capture_origin=color.source,
                    excerpt=color.evidence,
                    artifact_digest=palette_digest,
                )
                for color in derived_palette.colors
            )
        else:
            is_undeclared_palette = slot == "paleta"
            classification = (
                "UNDECLARED" if is_undeclared_palette else "GATED"
            )
            required_action = (
                "Revisar a paleta no Word e substituir a imagem se necessario"
                if is_undeclared_palette
                else f"Fornecer {slot} no Gated Drop Folder"
            )
            _document_slot, page = _media_location(
                master_package, part_name
            )
            width, height = _placeholder_pixel_dimensions(
                master_package, part_name
            )
            content = render_placeholder(
                parts[part_name], classification, slot, width, height
            )
            parts[part_name] = content
            digest = hashlib.sha256(content).hexdigest()
            artifacts.append(
                Artifact(
                    digest=digest,
                    origin="placeholder",
                    label=slot,
                )
            )
            pendencias.append(
                Pendencia(
                    slot=slot,
                    classification=classification,
                    reason=(
                        "site nao declara cores e nao tem ao menos duas "
                        "cores observadas utilizaveis"
                        if is_undeclared_palette
                        else "imagem nao fornecida no Gated Drop Folder"
                    ),
                    evidence=digest,
                    name=slot,
                    page=page,
                    required_action=required_action,
                )
            )

    for media in master_package.media:
        if media.part_name in claimed_media_parts:
            continue
        matching_run_artifacts = run_artifacts_by_digest.get(
            media.sha256.casefold(),
            (),
        )
        if matching_run_artifacts:
            for artifact in matching_run_artifacts:
                if artifact not in used_run_artifacts:
                    artifacts.append(artifact)
                    used_run_artifacts.add(artifact)
            continue
        if media.part_name in BOILERPLATE_MEDIA:
            artifacts.append(
                Artifact(
                    digest=media.sha256,
                    origin="boilerplate",
                    label=media.part_name,
                )
            )
            continue
        slot, page = _media_location(master_package, media.part_name)
        required_action = f"Investigar a falha e refazer a Capture de {page}"
        width, height = _placeholder_pixel_dimensions(
            master_package, media.part_name
        )
        content = render_placeholder(
            parts[media.part_name],
            "TOOL_BLOCKED",
            page,
            width,
            height,
        )
        parts[media.part_name] = content
        digest = hashlib.sha256(content).hexdigest()
        artifacts.append(
            Artifact(
                digest=digest,
                origin="placeholder",
                label=slot,
            )
        )
        pendencias.append(
            Pendencia(
                slot=slot,
                classification="TOOL_BLOCKED",
                reason="Capture nao produzida nesta etapa",
                evidence=digest,
                name=page,
                page=page,
                required_action=required_action,
            )
        )

    counts = {token: 0 for token in values}
    for item, _content in entries:
        replaced = parts[item.filename]
        if item.filename.casefold().endswith(".xml"):
            for token, marker in token_bytes.items():
                counts[token] += replaced.count(marker)
                replaced = replaced.replace(marker, values[token])
        parts[item.filename] = replaced

    missing = sorted(token for token, count in counts.items() if count == 0)
    if missing:
        raise ReportGenerationError(
            "Master lacks spreadsheet Token(s): " + ", ".join(missing)
        )
    residue = [
        token
        for token, marker in token_bytes.items()
        if any(marker in content for content in parts.values())
    ]
    if residue:
        raise ReportGenerationError(
            "spreadsheet Token substitution was incomplete: "
            + ", ".join(sorted(residue))
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".report-gates-",
        dir=output.parent,
    ) as staging_directory:
        staged_output = Path(staging_directory) / output.name
        with ZipFile(staged_output, "w") as generated:
            for item, _content in entries:
                generated.writestr(item, parts[item.filename])
        try:
            package = open_docx_package(staged_output)
        except (OSError, ValueError) as error:
            raise ReportGenerationError(
                f"generated DOCX package is invalid: {error}"
            ) from error
        boilerplate_links = frozenset(
            relationship.target
            for relationship in package.relationships
            if relationship.external
        )
        context = RunContext(
            pasta=engagement.pasta,
            media=tuple(artifacts),
            boilerplate_links=boilerplate_links,
            drop_folder=(
                None
                if gated.folder is None
                else str(gated.folder.resolve())
            ),
            capture_folder=(
                None
                if capture_folder is None
                else str(Path(capture_folder).resolve())
            ),
            output_paths=(str(output.resolve()),),
            blocks=blocks,
            pendencias=tuple(pendencias),
            prose_grounding=(*drafted.grounding, *palette_grounding),
        )
        gate_report = run_gates(package, context)
        if not gate_report.passed:
            raise StopCondition(
                "STOP CONDITION: correctness gates rejected the staged "
                "package:\n"
                + gate_report.format()
            )
        staged_output.replace(output)
    context_path, pendencias_document, pendencias_json = _write_sidecars(
        output, context
    )
    return GeneratedReport(
        engagement=engagement,
        document=output,
        context=context,
        context_document=context_path,
        pendencias_document=pendencias_document,
        pendencias_json=pendencias_json,
        gate_report=gate_report,
    )


__all__ = [
    "GeneratedReport",
    "ReportGenerationError",
    "StopCondition",
    "SPREADSHEET_TOKENS",
    "generate_report",
    "report_output_path",
]
