"""Blocks are whole, and no relationship or media file is stranded."""

from __future__ import annotations

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, Violation, result, violation


GATE = "block-integrity"

_LINKED_RELATIONSHIP_TYPES = ("image", "hyperlink")


def check_block_integrity(
    package: DocxPackage, context: RunContext
) -> GateResult:
    violations: list[Violation] = []

    by_position = {
        (paragraph.source_part, paragraph.index): paragraph
        for paragraph in package.paragraphs
    }
    for paragraph in package.paragraphs:
        if not paragraph.keep_next or not paragraph.text.strip():
            continue
        following = by_position.get(
            (paragraph.source_part, paragraph.index + 1)
        )
        if following is None or not following.has_image:
            violations.append(
                violation(
                    GATE,
                    "heading-without-image",
                    f"{paragraph.source_part} p={paragraph.index}",
                    paragraph.text,
                )
            )

    heading_texts = {
        paragraph.text.strip() for paragraph in package.paragraphs
    }
    for heading in context.blocks:
        if heading.strip() not in heading_texts:
            violations.append(
                violation(
                    GATE,
                    "block-heading-missing",
                    heading,
                    "no paragraph in the package matches this heading",
                )
            )

    part_names = {part.name for part in package.parts}
    for relationship in package.relationships:
        if relationship.external:
            continue
        if relationship.resolved_target not in part_names:
            violations.append(
                violation(
                    GATE,
                    "orphaned-relationship",
                    f"{relationship.source_part} "
                    f"{relationship.relationship_id}",
                    relationship.target,
                )
            )

    resolved_targets = {
        relationship.resolved_target
        for relationship in package.relationships
        if not relationship.external
    }
    for media in package.media:
        if media.part_name not in resolved_targets:
            violations.append(
                violation(
                    GATE,
                    "unreferenced-media",
                    media.part_name,
                    "no relationship in the package targets this part",
                )
            )

    referenced_ids_by_part: dict[str, set[str]] = {}
    for paragraph in package.paragraphs:
        referenced_ids_by_part.setdefault(
            paragraph.source_part, set()
        ).update(paragraph.relationship_ids)
    for relationship in package.relationships:
        if relationship.relationship_type not in _LINKED_RELATIONSHIP_TYPES:
            continue
        referenced = referenced_ids_by_part.get(
            relationship.source_part, set()
        )
        if relationship.relationship_id not in referenced:
            violations.append(
                violation(
                    GATE,
                    "unreferenced-relationship",
                    f"{relationship.source_part} "
                    f"{relationship.relationship_id}",
                    relationship.target,
                )
            )

    return result(GATE, violations)
