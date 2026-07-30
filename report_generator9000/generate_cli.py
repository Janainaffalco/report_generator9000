"""Command line tracer bullet for one Pasta from the control sheet."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import Sequence

from .assembly import assemble_output_package
from .control_sheet import (
    Engagement,
    SkippedRow,
    StopCondition,
    read_control_sheet_for_pasta,
)
from .gated_inputs import load_gated_inputs
from .generate import generate_report
from .gemini_provider import (
    GeminiProseProvider,
    GeminiProviderError,
    GeminiSettings,
)
from .lista_paginas import derive_lista_paginas
from .prose import ProseConfig, ProseProvider
from .runs import PACKAGED_MASTER_PATH


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
        default=PACKAGED_MASTER_PATH,
        help="signed-off Master (defaults to the versioned application asset)",
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
        help=(
            "model identifier (defaults to GEMINI_MODEL for the built-in "
            "Gemini provider)"
        ),
    )
    parser.add_argument(
        "--prose-output-budget",
        type=int,
        help=(
            "maximum output tokens (defaults to GEMINI_OUTPUT_BUDGET for "
            "the built-in Gemini provider)"
        ),
    )
    parser.add_argument(
        "--prose-provider",
        metavar="MODULE:ATTRIBUTE",
        help=(
            "override Gemini by loading a ProseProvider instance or "
            "zero-argument factory"
        ),
    )
    parser.add_argument(
        "--skip-assembly",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def load_prose_provider(specification: str) -> ProseProvider:
    """Load the configured provider without coupling the pipeline to a vendor."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError(
            "prose provider must use MODULE:ATTRIBUTE syntax"
        )
    module = importlib.import_module(module_name)
    configured = getattr(module, attribute_name)
    provider = configured() if callable(configured) else configured
    if not callable(getattr(provider, "generate", None)):
        raise ValueError(
            "configured prose provider must expose generate(request, config)"
        )
    return provider


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
        or arguments.prose_provider is not None
    ):
        parser.error("--no-llm cannot be combined with prose model settings")
    prose_config: ProseConfig | None = None
    managed_gemini_provider: GeminiProseProvider | None = None
    if prose_provider is None and arguments.prose_provider is not None:
        try:
            prose_provider = load_prose_provider(arguments.prose_provider)
        except (ImportError, AttributeError, TypeError, ValueError) as error:
            parser.error(str(error))
    if not arguments.no_llm and prose_provider is None:
        try:
            settings = GeminiSettings.from_environment()
            managed_gemini_provider = GeminiProseProvider(settings)
            prose_provider = managed_gemini_provider
            prose_config = ProseConfig(
                model=arguments.prose_model or settings.model,
                output_budget=(
                    arguments.prose_output_budget
                    or settings.output_budget
                ),
            )
        except GeminiProviderError as error:
            parser.error(str(error))
    elif not arguments.no_llm:
        if (
            arguments.prose_model is None
            or arguments.prose_output_budget is None
        ):
            parser.error(
                "--prose-model and --prose-output-budget are required "
                "with a custom prose provider"
            )
        prose_config = ProseConfig(
            model=arguments.prose_model,
            output_budget=arguments.prose_output_budget,
        )
    try:
        outcomes = read_control_sheet_for_pasta(
            arguments.planilha, arguments.linha
        )
        for outcome in outcomes:
            if isinstance(outcome, Engagement):
                load_gated_inputs(arguments.gated_drop_root, outcome)
        for outcome in outcomes:
            if isinstance(outcome, Engagement):
                if arguments.skip_assembly:
                    gated = load_gated_inputs(
                        arguments.gated_drop_root,
                        outcome,
                    )
                    pages = derive_lista_paginas(
                        outcome.capture_origin,
                        gated.declared_pages,
                    )
                    generated = generate_report(
                        arguments.master,
                        arguments.saida,
                        outcome,
                        arguments.gated_drop_root,
                        pages=pages,
                        prose_provider=prose_provider,
                        prose_config=prose_config,
                        no_llm=arguments.no_llm,
                    )
                else:
                    package = assemble_output_package(
                        arguments.master,
                        arguments.saida,
                        outcome,
                        arguments.gated_drop_root,
                        prose_provider=prose_provider,
                        prose_config=prose_config,
                        no_llm=arguments.no_llm,
                    )
                    generated = package.report
                print(f"DOCX\t{generated.document.resolve()}")
                print(
                    f"STATUS\t{generated.status.upper()}\t"
                    f"{generated.document.resolve()}"
                )
                if not arguments.skip_assembly:
                    print(f"DIRECTORY\t{package.directory}")
                    for preview in package.previews:
                        print(f"PREVIEW\t{preview}")
                    for capture in package.raw_captures:
                        print(f"CAPTURE\t{capture}")
            elif isinstance(outcome, StopCondition):
                print(
                    f"STOP CONDITION\t{arguments.linha}\t{outcome.cause}"
                )
            elif isinstance(outcome, SkippedRow):
                print(f"SKIPPED\t{arguments.linha}\t{outcome.reason}")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    finally:
        if managed_gemini_provider is not None:
            managed_gemini_provider.close()
    return 0


__all__ = ["build_parser", "main"]
