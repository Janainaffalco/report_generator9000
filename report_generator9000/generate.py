"""Clone the approved Master and fill control-sheet Tokens for an Engagement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZipFile

from .artifact_paths import engagement_artifact_key
from .control_sheet import Engagement
from .docx_package import open_docx_package
from .gates.master import BOILERPLATE_MEDIA
from .gated_inputs import (
    GATED_IMAGE_PARTS,
    GATED_VALUE_SLOTS,
    GatedInputError,
    load_gated_inputs,
)
from .run_context import Artifact, Pendencia, RunContext


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


class ReportGenerationError(ValueError):
    """The Master cannot safely produce the requested report."""


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
    pendencias_json.write_text(
        json.dumps(
            [asdict(item) for item in context.pendencias],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# PEND\u00caNCIAS",
        "",
        "Insumos ausentes, classificados por origem da Pend\u00eancia.",
        "",
    ]
    if context.pendencias:
        lines.extend(
            (
                "| Slot | Classifica\u00e7\u00e3o | Motivo | Evid\u00eancia |",
                "| --- | --- | --- | --- |",
            )
        )
        lines.extend(
            f"| {item.slot} | {item.classification} | {item.reason} | "
            f"`{item.evidence}` |"
            for item in context.pendencias
        )
    else:
        lines.append("Nenhuma Pend\u00eancia registrada.")
    pendencias_document.write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return context_path, pendencias_document, pendencias_json


def generate_report(
    master: str | Path,
    output_root: str | Path,
    engagement: Engagement,
    gated_drop_root: str | Path | None = None,
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

    replacement_text = {
        token: str(getattr(engagement, field))
        for token, field in SPREADSHEET_TOKENS.items()
    }
    supplied_gated_values = gated.values_by_token()
    replacement_text.update(supplied_gated_values)
    pendencias: list[Pendencia] = []
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
            )
        )
    values = {
        token: escape(value).encode("utf-8")
        for token, value in replacement_text.items()
    }
    token_bytes = {token: token.encode("ascii") for token in values}

    try:
        with ZipFile(master_path) as source:
            entries = [
                (item, source.read(item.filename))
                for item in source.infolist()
            ]
    except (BadZipFile, OSError, ValueError) as error:
        raise ReportGenerationError(
            f"{master_path}: invalid Master: {error}"
        ) from error

    parts = {item.filename: content for item, content in entries}
    artifacts: list[Artifact] = []
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
            _source_slot, source = supplied
            content = source.read_bytes()
            parts[part_name] = content
            artifacts.append(
                Artifact(
                    digest=hashlib.sha256(content).hexdigest(),
                    origin="gated",
                    label=slot,
                    source=str(source.resolve()),
                )
            )
        else:
            content = parts[part_name]
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
                    classification="GATED",
                    reason="imagem nao fornecida no Gated Drop Folder",
                    evidence=digest,
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
    with ZipFile(output, "w") as generated:
        for item, _content in entries:
            generated.writestr(item, parts[item.filename])
    try:
        package = open_docx_package(output)
    except (OSError, ValueError) as error:
        output.unlink(missing_ok=True)
        raise ReportGenerationError(
            f"generated DOCX package is invalid: {error}"
        ) from error
    for media in package.media:
        if media.part_name in claimed_media_parts:
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
        artifacts.append(
            Artifact(
                digest=media.sha256,
                origin="placeholder",
                label=media.part_name,
            )
        )
        pendencias.append(
            Pendencia(
                slot=f"capture:{media.part_name}",
                classification="TOOL_BLOCKED",
                reason="Capture ainda nao produzida nesta etapa",
                evidence=media.sha256,
            )
        )
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
            None if gated.folder is None else str(gated.folder.resolve())
        ),
        output_paths=(str(output.resolve()),),
        pendencias=tuple(pendencias),
    )
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
    )


__all__ = [
    "GeneratedReport",
    "ReportGenerationError",
    "SPREADSHEET_TOKENS",
    "generate_report",
    "report_output_path",
]
