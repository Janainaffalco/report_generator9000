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

    def _image_follows(paragraph) -> bool:
        following = by_position.get(
            (paragraph.source_part, paragraph.index + 1)
        )
        return following is not None and following.has_image

    stranded: set[tuple[str, int]] = set()
    for paragraph in package.paragraphs:
        if not paragraph.keep_next or not paragraph.text.strip():
            continue
        if not _image_follows(paragraph):
            stranded.add((paragraph.source_part, paragraph.index))
            violations.append(
                violation(
                    GATE,
                    "heading-without-image",
                    f"{paragraph.source_part} p={paragraph.index}",
                    paragraph.text,
                )
            )

    declared = tuple(heading.strip() for heading in context.blocks)
    occurrences: dict[str, list] = {heading: [] for heading in declared}
    for paragraph in package.paragraphs:
        text = paragraph.text.strip()
        if text in occurrences:
            occurrences[text].append(paragraph)

    for heading in declared:
        found = occurrences[heading]
        if not found:
            violations.append(
                violation(
                    GATE,
                    "block-heading-missing",
                    heading,
                    "no paragraph in the package matches this heading",
                )
            )
            continue
        if len(found) > 1:
            violations.append(
                violation(
                    GATE,
                    "duplicate-block-heading",
                    heading,
                    f"{len(found)} paragraphs carry this heading",
                )
            )
        for paragraph in found:
            position = (paragraph.source_part, paragraph.index)
            if not paragraph.keep_next:
                violations.append(
                    violation(
                        GATE,
                        "block-heading-unbound",
                        f"{paragraph.source_part} p={paragraph.index}",
                        f"{heading} is not bound to the paragraph below it",
                    )
                )
            if not _image_follows(paragraph) and position not in stranded:
                stranded.add(position)
                violations.append(
                    violation(
                        GATE,
                        "heading-without-image",
                        f"{paragraph.source_part} p={paragraph.index}",
                        paragraph.text,
                    )
                )

    if declared:
        for paragraph in package.paragraphs:
            text = paragraph.text.strip()
            if not paragraph.keep_next or not text or text in occurrences:
                continue
            if _image_follows(paragraph):
                violations.append(
                    violation(
                        GATE,
                        "undeclared-block",
                        f"{paragraph.source_part} p={paragraph.index}",
                        f"{text} is a Block the run context does not declare",
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
