"""Loja Virtual reports must never claim a handover this Run did not evidence."""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, result, violation


GATE = "loja-handover-claims"


class _Claim(NamedTuple):
    rule_slug: str
    pattern: re.Pattern[str]


def _normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


_NUMERAL = (
    r"\d+|um|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|"
    r"vinte|trinta|quarenta|cinquenta|sessenta|noventa"
)

_CLAIMS = (
    _Claim(
        "retention-promise-in-days",
        re.compile(rf"permanec\w*\s+dispon\w*\s+por\s+(?:{_NUMERAL})\s+dias"),
    ),
    _Claim(
        "project-receipt-declared",
        re.compile(r"representante\s+declara\s+ter\s+recebido\s+o\s+projeto"),
    ),
    _Claim(
        "training-declared-complete",
        re.compile(r"todas\s+as\s+orientacoes\s+foram\s+realizadas\s+junto\s+d[oa]\s+responsavel"),
    ),
    _Claim(
        "source-code-handed-over",
        re.compile(r"codigo\s+fonte\s+foi\s+cedido"),
    ),
    _Claim(
        "password-rotation-instructed",
        re.compile(r"recomendamos\s+alterar\s+as\s+senhas\s+de\s+acesso"),
    ),
)


def check_loja_handover_claims(package: DocxPackage, context: RunContext) -> GateResult:
    violations = []
    for paragraph in package.paragraphs:
        text = _normalized(paragraph.text)
        for claim in _CLAIMS:
            if claim.pattern.search(text):
                violations.append(
                    violation(
                        GATE,
                        claim.rule_slug,
                        "document",
                        "remove unevidenced handover claim",
                    )
                )
    return result(GATE, violations)
