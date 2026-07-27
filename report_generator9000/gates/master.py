"""Assertions that make a built Master safe to approve once for all reports."""

from __future__ import annotations

import re

from ..docx_package import DocxPackage
from .results import GateResult, result, violation


GATE = "master-build"

EXPECTED_TOKENS = frozenset(
    {
        "{{DEMANDA}}",
        "{{RAZAO_SOCIAL}}",
        "{{CNPJ}}",
        "{{ESPECIALISTA}}",
        "{{SOBRE_A_EMPRESA}}",
        "{{BRIEFING_INICIAL}}",
        "{{LISTA_DE_PAGINAS}}",
        "{{DATA_BACKUP}}",
        "{{PLANO_HOSPEDAGEM}}",
        "{{DOMINIO_PUBLICADO}}",
        "{{WP_ADMIN_URL}}",
        "{{EMAIL_CLIENTE}}",
        "{{LINK_CODIGO_FONTE}}",
        "{{LINK_GUIA_RAPIDO}}",
        "{{LINK_IDENTIDADE_VISUAL}}",
        "{{LINK_USUARIOS_SENHAS}}",
        "{{DATA_KICKOFF}}",
        "{{DATA_ENTREGA}}",
    }
)

BOILERPLATE_MEDIA = frozenset(
    {"word/media/image1.png", "word/media/image21.png"}
)

_TOKEN = re.compile(r"\{\{[^{}<>]{1,64}\}\}")
_CLIENT_MARKERS = (
    "argel",
    "64.525.744/0001-02",
    "christian albuquerque alonso",
    "010028/2025",
    "argelresistencia.com.br",
    "argelresistencias@hotmail.com",
    "ondviajar.com.br",
    "22/07/2026",
    "05/02/2026",
    "25/06/2026",
    "plano single",
)


def _is_boilerplate_link(target: str) -> bool:
    host = target.casefold().split("/", 3)[2] if "://" in target else ""
    return host in {
        "w3techs.com",
        "br.wordpress.org",
        "popularfx.com",
    }


def check_master_build(
    package: DocxPackage, source: DocxPackage | None = None
) -> GateResult:
    """Check token shape, residue, links, and media against an approved source."""
    violations = []
    seen: set[str] = set()

    for paragraph in package.paragraphs:
        for run in paragraph.runs:
            for token in _TOKEN.findall(run.text):
                seen.add(token)
                if run.text != token:
                    violations.append(
                        violation(
                            GATE,
                            "token-not-one-run",
                            f"{paragraph.source_part} p={paragraph.index}",
                            token,
                        )
                    )

    for token in sorted(EXPECTED_TOKENS - seen):
        violations.append(violation(GATE, "missing-token", "MASTER.docx", token))
    for token in sorted(seen - EXPECTED_TOKENS):
        violations.append(violation(GATE, "unexpected-token", "MASTER.docx", token))

    for part in package.parts:
        text = (part.text or "").casefold()
        for marker in _CLIENT_MARKERS:
            if marker in text:
                violations.append(
                    violation(GATE, "source-client-residue", part.name, marker)
                )

    for relationship in package.relationships:
        if relationship.external and not _is_boilerplate_link(relationship.target):
            violations.append(
                violation(
                    GATE,
                    "client-link-retained",
                    f"{relationship.source_part} {relationship.relationship_id}",
                    relationship.target,
                )
            )

    if source is not None:
        source_media = {item.part_name: item for item in source.media}
        for media in package.media:
            original = source_media.get(media.part_name)
            if (
                original is not None
                and media.part_name not in BOILERPLATE_MEDIA
                and media.sha256 == original.sha256
            ):
                violations.append(
                    violation(
                        GATE,
                        "source-client-media-retained",
                        media.part_name,
                        media.sha256,
                    )
                )

        for relationship in source.relationships:
            if relationship.external and not _is_boilerplate_link(relationship.target):
                if any(
                    item.external and item.target == relationship.target
                    for item in package.relationships
                ):
                    violations.append(
                        violation(
                            GATE,
                            "source-client-link-retained",
                            relationship.source_part,
                            relationship.target,
                        )
                    )

    return result(GATE, violations)
