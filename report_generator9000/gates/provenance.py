"""Provenance: every media file traces to something this run is entitled to."""

from __future__ import annotations

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, Violation, result, violation


GATE = "media-provenance"


def check_media_provenance(
    package: DocxPackage, context: RunContext
) -> GateResult:
    violations: list[Violation] = []
    claims_by_digest = context.media_by_digest()
    for media in package.media:
        digest = media.sha256.lower()
        claims = claims_by_digest.get(digest)
        if not claims:
            violations.append(
                violation(
                    GATE,
                    "media-without-provenance",
                    media.part_name,
                    f"sha256={digest} traces to no Boilerplate entry, "
                    "no Capture from this run, and no Gated Input from "
                    "this run's Gated Drop Folder",
                )
            )
            continue
        origins = {claim.origin for claim in claims}
        if len(origins) > 1:
            claim_descriptions = ", ".join(
                f"{claim.origin} ({claim.label})" for claim in claims
            )
            violations.append(
                violation(
                    GATE,
                    "ambiguous-provenance",
                    media.part_name,
                    f"sha256={digest} claimed as {claim_descriptions}",
                )
            )
    return result(GATE, violations)
