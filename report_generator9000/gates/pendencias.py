"""The Pendencias report and the document agree in both directions."""

from __future__ import annotations

from ..docx_package import DocxPackage
from ..run_context import Artifact, RunContext
from .results import GateResult, Violation, result, violation


GATE = "pendencias-agreement"


def check_pendencias_agreement(
    package: DocxPackage, context: RunContext
) -> GateResult:
    violations: list[Violation] = []

    placeholder_by_digest: dict[str, list[Artifact]] = {}
    for artifact in context.artifacts_of("placeholder"):
        placeholder_by_digest.setdefault(
            artifact.digest.lower(), []
        ).append(artifact)
    declared_evidence = {
        pendencia.evidence.lower() for pendencia in context.pendencias
    }
    for media in package.media:
        digest = media.sha256.lower()
        placeholders = placeholder_by_digest.get(digest, [])
        if not placeholders or digest in declared_evidence:
            continue
        violations.append(
            violation(
                GATE,
                "placeholder-without-pendencia",
                media.part_name,
                placeholders[0].label,
            )
        )

    media_digests = {media.sha256.lower() for media in package.media}
    part_texts = tuple(
        part.text for part in package.parts if part.text is not None
    )
    paragraph_texts = tuple(
        paragraph.text for paragraph in package.paragraphs
    )
    for pendencia in context.pendencias:
        evidence = pendencia.evidence
        if evidence.lower() in media_digests:
            continue
        if any(evidence in text for text in part_texts):
            continue
        if any(evidence in text for text in paragraph_texts):
            continue
        violations.append(
            violation(
                GATE,
                "pendencia-without-evidence",
                pendencia.slot,
                f"evidence {evidence!r} matches no media digest in "
                f"the package and appears in no document text "
                f"(classification={pendencia.classification})",
            )
        )

    slot_counts: dict[str, int] = {}
    for pendencia in context.pendencias:
        slot_counts[pendencia.slot] = slot_counts.get(pendencia.slot, 0) + 1
    for slot, count in slot_counts.items():
        if count > 1:
            violations.append(
                violation(
                    GATE,
                    "duplicate-pendencia",
                    slot,
                    f"{count} Pendências declare slot {slot!r}",
                )
            )

    return result(GATE, violations)
