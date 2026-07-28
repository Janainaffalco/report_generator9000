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
from .gated_inputs import load_gated_inputs
from .prose import ProseConfig, ProseProvider


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
    parser.add_argument(
        "--gated-drop-root",
        type=Path,
        default=Path("gated"),
        help="root containing one Pasta + Razao Social Gated Drop Folder",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="skip the prose provider and insert marked prose gaps",
    )
    parser.add_argument(
        "--prose-model",
        help="configured model identifier for the injected prose provider",
    )
    parser.add_argument(
        "--prose-output-budget",
        type=int,
        help="measured maximum output tokens for the prose provider",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    prose_provider: ProseProvider | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.no_llm and (
        arguments.prose_model is not None
        or arguments.prose_output_budget is not None
    ):
        parser.error("--no-llm cannot be combined with prose model settings")
    configured = (
        arguments.prose_model is not None
        or arguments.prose_output_budget is not None
    )
    if configured and (
        arguments.prose_model is None
        or arguments.prose_output_budget is None
    ):
        parser.error(
            "--prose-model and --prose-output-budget must be set together"
        )
    prose_config = (
        None
        if not configured
        else ProseConfig(
            model=arguments.prose_model,
            output_budget=arguments.prose_output_budget,
        )
    )
    if prose_config is not None and prose_provider is None:
        parser.error("a prose provider must be injected for model mode")
    try:
        outcomes = read_control_sheet_for_pasta(
            arguments.planilha, arguments.linha
        )
        for outcome in outcomes:
            if isinstance(outcome, Engagement):
                load_gated_inputs(arguments.gated_drop_root, outcome)
        for outcome in outcomes:
            if isinstance(outcome, Engagement):
                generated = generate_report(
                    arguments.master,
                    arguments.saida,
                    outcome,
                    arguments.gated_drop_root,
                    prose_provider=prose_provider,
                    prose_config=prose_config,
                    no_llm=arguments.no_llm,
                )
                print(f"DOCX\t{generated.document.resolve()}")
                print(
                    f"STATUS\t{generated.status.upper()}\t"
                    f"{generated.document.resolve()}"
                )
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
