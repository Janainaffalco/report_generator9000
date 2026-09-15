"""Loja Virtual reports must never disclose access credentials."""

from __future__ import annotations

import re

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, result, violation


GATE = "loja-credential-exposure"
_CREDENTIAL = re.compile(r"\b(?:senhas?|passwords?|passwd|pwd)\b", re.IGNORECASE)


def check_loja_credentials(package: DocxPackage, context: RunContext) -> GateResult:
    violations = []
    if any(_CREDENTIAL.search(paragraph.text) for paragraph in package.paragraphs):
        violations.append(
            violation(GATE, "credential-bearing-text", "document", "remove credential-bearing content")
        )
    return result(GATE, violations)
