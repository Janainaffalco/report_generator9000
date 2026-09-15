"""A Loja report retains the curated storefront Block grammar."""

from __future__ import annotations

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .master import LOJA_VIRTUAL_GRAMMAR
from .results import GateResult, result, violation


GATE = "loja-block-grammar"


def check_loja_block_grammar(package: DocxPackage, context: RunContext) -> GateResult:
    required = LOJA_VIRTUAL_GRAMMAR.block_headings
    headings = tuple(
        paragraph.text.strip() for paragraph in package.paragraphs
        if paragraph.source_part == "word/document.xml"
        and paragraph.keep_next and paragraph.text.strip()
    )
    found = tuple(heading for heading in headings if heading in required)
    violations = []
    if found != required:
        violations.append(
            violation(GATE, "required-blocks", "word/document.xml", repr(found))
        )
    if context.blocks and tuple(
        heading for heading in context.blocks if heading in required
    ) != required:
        violations.append(
            violation(GATE, "undeclared-required-blocks", "run-context", repr(context.blocks))
        )
    return result(GATE, violations)
