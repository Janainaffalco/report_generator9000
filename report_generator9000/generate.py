"""Clone the approved Master and fill control-sheet Tokens for an Engagement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZipFile, ZipInfo

from .control_sheet import Engagement
from .docx_package import open_docx_package


SPREADSHEET_TOKENS = {
    "{{DEMANDA}}": "demanda",
    "{{RAZAO_SOCIAL}}": "razao_social",
    "{{CNPJ}}": "cnpj",
    "{{ESPECIALISTA}}": "especialista",
    "{{DATA_KICKOFF}}": "kick_off_br",
}
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True)
class GeneratedReport:
    """One report artifact produced for an Engagement."""

    engagement: Engagement
    document: Path


class ReportGenerationError(ValueError):
    """The Master cannot safely produce the requested report."""


def _path_component(value: str) -> str:
    component = " ".join(_UNSAFE_FILENAME.sub("-", value).split()).rstrip(". ")
    if not component:
        raise ReportGenerationError("output key contains no usable characters")
    if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        component = f"_{component}"
    return component


def report_output_path(output_root: str | Path, engagement: Engagement) -> Path:
    """Return the collision-safe path keyed by Pasta and Razao Social."""
    key = _path_component(f"{engagement.pasta} - {engagement.razao_social}")
    return (
        Path(output_root)
        / key
        / f"RELATÓRIO TÉCNICO FINAL - {key}.docx"
    )


def generate_report(
    master: str | Path,
    output_root: str | Path,
    engagement: Engagement,
) -> GeneratedReport:
    """Clone *master* and fill only Tokens sourced from the control sheet."""
    master_path = Path(master)
    output = report_output_path(output_root, engagement)
    values = {
        token: escape(str(getattr(engagement, field))).encode("utf-8")
        for token, field in SPREADSHEET_TOKENS.items()
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

    counts = {token: 0 for token in values}
    generated_parts: list[tuple[ZipInfo, bytes]] = []
    for item, content in entries:
        replaced = content
        if item.filename.casefold().endswith(".xml"):
            for token, marker in token_bytes.items():
                counts[token] += replaced.count(marker)
                replaced = replaced.replace(marker, values[token])
        generated_parts.append((item, replaced))

    missing = sorted(token for token, count in counts.items() if count == 0)
    if missing:
        raise ReportGenerationError(
            "Master lacks spreadsheet Token(s): " + ", ".join(missing)
        )
    residue = [
        token
        for token, marker in token_bytes.items()
        if any(marker in content for _item, content in generated_parts)
    ]
    if residue:
        raise ReportGenerationError(
            "spreadsheet Token substitution was incomplete: "
            + ", ".join(sorted(residue))
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as generated:
        for item, content in generated_parts:
            generated.writestr(item, content)
    try:
        open_docx_package(output)
    except (OSError, ValueError) as error:
        output.unlink(missing_ok=True)
        raise ReportGenerationError(
            f"generated DOCX package is invalid: {error}"
        ) from error
    return GeneratedReport(engagement=engagement, document=output)


__all__ = [
    "GeneratedReport",
    "ReportGenerationError",
    "SPREADSHEET_TOKENS",
    "generate_report",
    "report_output_path",
]
