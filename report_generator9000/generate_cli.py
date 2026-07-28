"""Command line tracer bullet for one Pasta from the control sheet."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .control_sheet import (
    Engagement,
    SkippedRow,
    StopCondition,
    read_control_sheet_for_pasta,
)
from .generate import generate_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gerar_relatorio.py")
    parser.add_argument(
        "--linha",
        required=True,
        metavar="PASTA",
        help="Pasta whose engagement row(s) should be processed",
    )
    parser.add_argument(
        "--planilha",
        type=Path,
        default=Path("Planilha para controle de relatórios.xlsx"),
        help="SEBRAETEC control workbook",
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("master-build-check") / "MASTER.docx",
        help="approved built Master package",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=Path("relatorios-gerados"),
        help="root directory for generated engagement artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        outcomes = read_control_sheet_for_pasta(
            arguments.planilha, arguments.linha
        )
        for outcome in outcomes:
            if isinstance(outcome, Engagement):
                generated = generate_report(
                    arguments.master, arguments.saida, outcome
                )
                print(f"DOCX\t{generated.document.resolve()}")
            elif isinstance(outcome, StopCondition):
                print(
                    f"STOP CONDITION\t{arguments.linha}\t{outcome.cause}"
                )
            elif isinstance(outcome, SkippedRow):
                print(f"SKIPPED\t{arguments.linha}\t{outcome.reason}")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


__all__ = ["build_parser", "main"]
