"""This run read this engagement's folders, and wrote to its Pasta."""

from __future__ import annotations

from pathlib import PurePosixPath

from ..docx_package import DocxPackage
from ..run_context import RunContext, is_within
from .results import GateResult, Violation, result, violation


GATE = "engagement-scope"


def _normalise(path: str) -> str:
    return path.replace("\\", "/")


def _keyed_to(pasta: str, path: str) -> bool:
    parts = PurePosixPath(_normalise(path)).parts
    return any(part == pasta or part.startswith(f"{pasta}_") for part in parts)


def check_engagement_scope(
    package: DocxPackage, context: RunContext
) -> GateResult:
    violations: list[Violation] = []

    declared = bool(
        context.drop_folder or context.capture_folder or context.output_paths
    )
    if not context.pasta and declared:
        violations.append(
            violation(
                GATE,
                "pasta-not-declared",
                "run context",
                "no Pasta declared while drop_folder, capture_folder, or "
                "output_paths is present",
            )
        )

    pasta = context.pasta

    if context.drop_folder is not None:
        drop_folder = _normalise(context.drop_folder)
        final_component = PurePosixPath(drop_folder).name
        if pasta and final_component != pasta:
            violations.append(
                violation(
                    GATE,
                    "drop-folder-not-this-engagement",
                    context.drop_folder,
                    f"final path component {final_component!r} is not "
                    f"Pasta {pasta!r}",
                )
            )

    if context.capture_folder is not None:
        capture_folder = context.capture_folder
        if pasta and not _keyed_to(pasta, capture_folder):
            violations.append(
                violation(
                    GATE,
                    "capture-folder-not-this-engagement",
                    context.capture_folder,
                    f"no component of {capture_folder!r} is Pasta {pasta!r} "
                    f"or starts with '{pasta}_'",
                )
            )

    if context.drop_folder is None:
        for artifact in context.artifacts_of("gated"):
            if artifact.source is not None:
                violations.append(
                    violation(
                        GATE,
                        "drop-folder-not-declared",
                        artifact.source,
                        "no drop_folder declared while a gated Artifact "
                        f"carries source {artifact.source!r}",
                    )
                )
    else:
        drop_folder = _normalise(context.drop_folder)
        for artifact in context.artifacts_of("gated"):
            source = artifact.source
            if source is None or not is_within(_normalise(source), drop_folder):
                violations.append(
                    violation(
                        GATE,
                        "gated-input-outside-drop-folder",
                        artifact.label,
                        f"source {source!r} is not within declared "
                        f"drop_folder {context.drop_folder!r}",
                    )
                )

    if context.capture_folder is not None:
        capture_folder = _normalise(context.capture_folder)
        for artifact in context.artifacts_of("capture"):
            source = artifact.source
            if source is None or not is_within(
                _normalise(source), capture_folder
            ):
                violations.append(
                    violation(
                        GATE,
                        "capture-outside-run",
                        artifact.label,
                        f"source {source!r} is not within declared "
                        f"capture_folder {context.capture_folder!r}",
                    )
                )

    if pasta:
        for output_path in context.output_paths:
            if not _keyed_to(pasta, output_path):
                violations.append(
                    violation(
                        GATE,
                        "output-path-outside-pasta",
                        output_path,
                        f"no component of {output_path!r} is Pasta "
                        f"{pasta!r} or starts with '{pasta}_'",
                    )
                )

    return result(GATE, violations)
