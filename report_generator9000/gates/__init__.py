"""The correctness gates: assertions on a finished package, never judgement.

Every rule the pipeline relies on is expressed here once, so the same code is
the Master's acceptance criteria at build time and the per-report check at
generation time.
"""

from __future__ import annotations

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .blocks import check_block_integrity
from .links import check_link_provenance
from .master import check_master_build
from .pendencias import check_pendencias_agreement
from .provenance import check_media_provenance
from .results import GateReport, GateResult, Violation
from .scope import check_engagement_scope
from .tokens import check_token_residue


GATES = (
    check_media_provenance,
    check_link_provenance,
    check_token_residue,
    check_engagement_scope,
    check_block_integrity,
    check_pendencias_agreement,
)

__all__ = [
    "GATES",
    "GateReport",
    "GateResult",
    "Violation",
    "check_block_integrity",
    "check_engagement_scope",
    "check_link_provenance",
    "check_master_build",
    "check_media_provenance",
    "check_pendencias_agreement",
    "check_token_residue",
    "run_gates",
]


def run_gates(package: DocxPackage, context: RunContext) -> GateReport:
    """Run every gate against *package* in a fixed order."""
    return GateReport(results=tuple(gate(package, context) for gate in GATES))
