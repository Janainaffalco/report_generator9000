"""External links: known boilerplate, or derived from this run's inputs."""

from __future__ import annotations

from urllib.parse import urlparse

from ..docx_package import DocxPackage
from ..run_context import RunContext
from .results import GateResult, Violation, result, violation


GATE = "link-provenance"


def _host(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _derived_from_inputs(target: str, input_urls: frozenset[str]) -> bool:
    stripped_inputs = {url.strip() for url in input_urls}
    if target in stripped_inputs:
        return True
    target_host = _host(target)
    if target_host is None:
        return False
    return any(target_host == _host(url) for url in stripped_inputs)


def check_link_provenance(
    package: DocxPackage, context: RunContext
) -> GateResult:
    violations: list[Violation] = []
    boilerplate_links = {link.strip() for link in context.boilerplate_links}
    for relationship in package.relationships:
        if not relationship.external:
            continue
        target = relationship.target.strip()
        if target in boilerplate_links:
            continue
        if _derived_from_inputs(target, context.input_urls):
            continue
        violations.append(
            violation(
                GATE,
                "link-without-provenance",
                f"{relationship.source_part} {relationship.relationship_id}",
                target,
            )
        )
    return result(GATE, violations)
