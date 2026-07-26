"""No unreplaced Token survives anywhere in the package."""

from __future__ import annotations

import re

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, Violation, result, violation


GATE = "token-residue"

_TOKEN = re.compile(r"\{\{[^{}<>]{1,64}\}\}")


def check_token_residue(
    package: DocxPackage, context: RunContext
) -> GateResult:
    violations: list[Violation] = []
    reported: set[tuple[str, str]] = set()
    part_tokens: dict[str, set[str]] = {}

    for part in package.parts:
        if part.text is None:
            continue
        tokens = sorted(set(_TOKEN.findall(part.text)))
        part_tokens[part.name] = set(tokens)
        for token in tokens:
            key = (part.name, token)
            if key in reported:
                continue
            reported.add(key)
            violations.append(
                violation(GATE, "unreplaced-token", part.name, token)
            )

    for paragraph in package.paragraphs:
        tokens = sorted(set(_TOKEN.findall(paragraph.text)))
        if not tokens:
            continue
        already_in_part = part_tokens.get(paragraph.source_part, set())
        artifact = f"{paragraph.source_part} p={paragraph.index}"
        for token in tokens:
            if token in already_in_part:
                continue
            key = (artifact, token)
            if key in reported:
                continue
            reported.add(key)
            violations.append(
                violation(GATE, "token-split-across-runs", artifact, token)
            )

    return result(GATE, violations)
