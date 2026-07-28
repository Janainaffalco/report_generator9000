"""Constrain the report's only model-authored prose behind one provider seam."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .lista_paginas import Pagina
from .run_context import Grounding, Pendencia


_RAW_MARKUP = re.compile(r"<[A-Za-z][^>]*>")


@dataclass(frozen=True)
class ExtractedPageText:
    """Visible page text extracted by script, never raw markup."""

    capture_origin: str
    text: str

    def __post_init__(self) -> None:
        if not self.capture_origin.strip():
            raise ValueError("Capture Origin must be non-empty")
        if not self.text.strip():
            raise ValueError("extracted page text must be non-empty")
        if _RAW_MARKUP.search(self.text):
            raise ValueError(
                "provider input must be script-extracted text, not raw markup"
            )


@dataclass(frozen=True)
class ProseConfig:
    """Measured provider configuration supplied by the caller."""

    model: str
    output_budget: int

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("prose model must be configured")
        if self.output_budget <= 0:
            raise ValueError("prose output budget must be positive")


@dataclass(frozen=True)
class ProseRequest:
    """The complete grounding surface visible to a provider."""

    site_text: tuple[ProviderPageText, ...]


@dataclass(frozen=True)
class ProviderPageText:
    """Opaque source identity plus text; it cannot be used for research."""

    source_id: str
    text: str


@dataclass(frozen=True)
class GroundingCitation:
    """An exact excerpt from one opaque provider input."""

    source_id: str
    excerpt: str


@dataclass(frozen=True)
class GroundedField:
    value: str | None
    grounded: bool
    citations: tuple[GroundingCitation, ...] = ()


@dataclass(frozen=True)
class ProseResponse:
    """Structured provider output; no other authored fields are accepted."""

    company_description: GroundedField
    briefing_objective: GroundedField
    output_budget_exhausted: bool = False


class ProseProvider(Protocol):
    """The single replaceable boundary around model execution."""

    def generate(
        self,
        request: ProseRequest,
        config: ProseConfig,
    ) -> ProseResponse: ...


@dataclass(frozen=True)
class DraftedProse:
    token_values: dict[str, str]
    pendencias: tuple[Pendencia, ...]
    grounding: tuple[Grounding, ...] = ()


class ProseBudgetExceeded(RuntimeError):
    """The provider returned a truncated response that must never ship."""

    def __init__(self, pendencia: Pendencia) -> None:
        super().__init__(
            "prose provider exhausted its configured output budget"
        )
        self.pendencia = pendencia


def _natural_list(labels: tuple[str, ...]) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} e {labels[1]}"
    return f"{', '.join(labels[:-1])} e {labels[-1]}"


def deterministic_page_paragraph(pages: tuple[Pagina, ...]) -> str:
    """Describe exactly the Lista entries that belong in the Briefing."""
    labels = tuple(
        page.rotulo for page in pages if page.entra_no_briefing
    )
    if not labels:
        return "A estrutura do site não possui páginas declaradas no Briefing."
    return f"A estrutura do site contempla as páginas {_natural_list(labels)}."


def _gap(
    *,
    slot: str,
    name: str,
    classification: str,
    reason: str,
) -> tuple[str, Pendencia]:
    marker = f"[PENDÊNCIA {classification}: {reason}]"
    return marker, Pendencia(
        slot=slot,
        classification=classification,
        reason=reason,
        evidence=marker,
        name=name,
        page="BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO",
        required_action=f"Fornecer e revisar {name}",
    )


def _field_value(
    field: GroundedField,
    *,
    slot: str,
    name: str,
    gap_reason: str,
    provider_pages: dict[str, ProviderPageText],
    extracted_pages: dict[str, ExtractedPageText],
) -> tuple[str, Pendencia, tuple[Grounding, ...]]:
    citations_are_exact = bool(field.citations) and all(
        citation.source_id in provider_pages
        and citation.excerpt.strip()
        and citation.excerpt in provider_pages[citation.source_id].text
        for citation in field.citations
    )
    if (
        not field.grounded
        or field.value is None
        or not field.value.strip()
        or not citations_are_exact
    ):
        marker, pendencia = _gap(
            slot=slot,
            name=name,
            classification="TOOL_BLOCKED",
            reason=gap_reason,
        )
        return marker, pendencia, ()
    text = field.value.strip()
    grounding = tuple(
        Grounding(
            field=slot,
            capture_origin=extracted_pages[citation.source_id].capture_origin,
            excerpt=citation.excerpt,
        )
        for citation in field.citations
    )
    return (
        text,
        Pendencia(
            slot=slot,
            classification="REVIEW",
            reason="texto gerado requer revisão humana antes da entrega",
            evidence=text,
            name=name,
            page="BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO",
            required_action=f"Revisar {name} contra o texto do site",
        ),
        grounding,
    )


def draft_prose(
    pages: tuple[Pagina, ...],
    site_text: tuple[ExtractedPageText, ...],
    provider: ProseProvider | None,
    config: ProseConfig | None,
    *,
    no_llm: bool = False,
) -> DraftedProse:
    """Draft the two permitted fields and one deterministic page paragraph."""
    deterministic = deterministic_page_paragraph(pages)
    if no_llm:
        company, company_gap = _gap(
            slot="descricao_empresa",
            name="descrição da empresa",
            classification="GATED",
            reason="descrição da empresa não gerada (--no-llm)",
        )
        objective, objective_gap = _gap(
            slot="objetivo_briefing",
            name="objetivo do briefing",
            classification="GATED",
            reason="objetivo do briefing não gerado (--no-llm)",
        )
        return DraftedProse(
            token_values={
                "{{SOBRE_A_EMPRESA}}": company,
                "{{BRIEFING_INICIAL}}": objective,
                "{{LISTA_DE_PAGINAS}}": deterministic,
            },
            pendencias=(company_gap, objective_gap),
        )
    if config is None:
        raise ValueError("prose configuration is required unless --no-llm")
    if provider is None:
        raise ValueError("prose provider is required unless --no-llm")
    provider_text = tuple(
        ProviderPageText(source_id=f"page-{index}", text=page.text)
        for index, page in enumerate(site_text, start=1)
    )
    provider_pages = {page.source_id: page for page in provider_text}
    extracted_pages = {
        f"page-{index}": page
        for index, page in enumerate(site_text, start=1)
    }
    response = provider.generate(
        ProseRequest(site_text=provider_text),
        config,
    )
    if response.output_budget_exhausted:
        raise ProseBudgetExceeded(
            Pendencia(
                slot="prosa",
                classification="TOOL_BLOCKED",
                reason="orçamento de saída esgotado; resposta truncada",
                evidence="[PENDÊNCIA TOOL_BLOCKED: prosa truncada]",
                name="prosa gerada",
                page="BRIEFING INICIAL PARA DEFINIÇÃO DO ESCOPO",
                required_action=(
                    "Aumentar o orçamento medido e refazer a geração"
                ),
            )
        )
    company, company_review, company_grounding = _field_value(
        response.company_description,
        slot="descricao_empresa",
        name="descrição da empresa",
        gap_reason="descrição da empresa sem base no site",
        provider_pages=provider_pages,
        extracted_pages=extracted_pages,
    )
    objective, objective_review, objective_grounding = _field_value(
        response.briefing_objective,
        slot="objetivo_briefing",
        name="objetivo do briefing",
        gap_reason="objetivo do briefing sem base no site",
        provider_pages=provider_pages,
        extracted_pages=extracted_pages,
    )
    return DraftedProse(
        token_values={
            "{{SOBRE_A_EMPRESA}}": company,
            "{{BRIEFING_INICIAL}}": objective,
            "{{LISTA_DE_PAGINAS}}": deterministic,
        },
        pendencias=(company_review, objective_review),
        grounding=(*company_grounding, *objective_grounding),
    )


__all__ = [
    "DraftedProse",
    "ExtractedPageText",
    "GroundingCitation",
    "GroundedField",
    "ProseBudgetExceeded",
    "ProseConfig",
    "ProseProvider",
    "ProviderPageText",
    "ProseRequest",
    "ProseResponse",
    "deterministic_page_paragraph",
    "draft_prose",
]
