from __future__ import annotations

import pytest

from report_generator9000.lista_paginas import (
    AREA_LEGAL,
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    Pagina,
)
from report_generator9000.prose import (
    ExtractedPageText,
    GroundedField,
    ProseBudgetExceeded,
    ProseConfig,
    ProseRequest,
    ProseResponse,
    draft_prose,
)


PAGES = (
    Pagina(PAGINA_PRINCIPAL, "Home", "https://example.test/", "PÁGINA HOME"),
    Pagina(
        PAGINA_PRINCIPAL,
        "Serviços",
        "https://example.test/servicos",
        "SEÇÃO SERVIÇOS",
    ),
    Pagina(
        AREA_LEGAL,
        "Política de Privacidade",
        "https://example.test/privacidade",
        "POLÍTICA DE PRIVACIDADE",
    ),
    Pagina(
        ELEMENTO_TRANSVERSAL,
        "Cabeçalho",
        "https://example.test/",
        "CABEÇALHO",
    ),
    Pagina(
        ELEMENTO_TRANSVERSAL,
        "Rodapé",
        "https://example.test/",
        "RODAPÉ",
    ),
)
SITE_TEXT = (
    ExtractedPageText(
        url="https://example.test/",
        text="A Acme fabrica componentes industriais desde 1998.",
    ),
    ExtractedPageText(
        url="https://example.test/servicos",
        text="Projetamos componentes sob medida para linhas de produção.",
    ),
)


class CannedProvider:
    def __init__(self, response: ProseResponse) -> None:
        self.response = response
        self.calls: list[tuple[ProseRequest, ProseConfig]] = []

    def generate(
        self,
        request: ProseRequest,
        config: ProseConfig,
    ) -> ProseResponse:
        self.calls.append((request, config))
        return self.response


def test_grounded_provider_authors_only_two_fields_and_pages_are_deterministic() -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField(
                "A Acme fabrica componentes industriais.",
                grounded=True,
            ),
            briefing_objective=GroundedField(
                "O projeto tem como objetivo apresentar os componentes da Acme.",
                grounded=True,
            ),
        )
    )
    config = ProseConfig(model="configured-model", output_budget=730)

    drafted = draft_prose(PAGES, SITE_TEXT, provider, config)

    assert drafted.token_values == {
        "{{SOBRE_A_EMPRESA}}": "A Acme fabrica componentes industriais.",
        "{{BRIEFING_INICIAL}}": (
            "O projeto tem como objetivo apresentar os componentes da Acme."
        ),
        "{{LISTA_DE_PAGINAS}}": (
            "A estrutura do site contempla as páginas Home, Serviços e "
            "Política de Privacidade."
        ),
    }
    assert len(provider.calls) == 1
    request, received_config = provider.calls[0]
    assert request.site_text == SITE_TEXT
    assert received_config is config
    assert len(drafted.pendencias) == 2
    assert all("Revisar" in item.required_action for item in drafted.pendencias)
    assert all(item.evidence in drafted.token_values.values() for item in drafted.pendencias)


@pytest.mark.parametrize(
    ("company", "objective"),
    [
        (GroundedField(None, grounded=True), GroundedField("Objetivo", True)),
        (GroundedField("Empresa", grounded=False), GroundedField("Objetivo", True)),
        (GroundedField("Empresa", grounded=True), GroundedField(None, False)),
    ],
)
def test_null_or_ungrounded_fields_become_marked_gaps(
    company: GroundedField,
    objective: GroundedField,
) -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=company,
            briefing_objective=objective,
        )
    )

    drafted = draft_prose(
        PAGES,
        SITE_TEXT,
        provider,
        ProseConfig(model="m", output_budget=500),
    )

    values = drafted.token_values
    if not company.grounded or company.value is None:
        assert values["{{SOBRE_A_EMPRESA}}"] == (
            "[PENDÊNCIA TOOL_BLOCKED: descrição da empresa sem base no site]"
        )
    if not objective.grounded or objective.value is None:
        assert values["{{BRIEFING_INICIAL}}"] == (
            "[PENDÊNCIA TOOL_BLOCKED: objetivo do briefing sem base no site]"
        )
    assert all(item.evidence in values.values() for item in drafted.pendencias)


def test_budget_exhaustion_is_a_hard_tool_failure() -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField("Parcial", True),
            briefing_objective=GroundedField("Também parcial", True),
            output_budget_exhausted=True,
        )
    )

    with pytest.raises(ProseBudgetExceeded) as raised:
        draft_prose(
            PAGES,
            SITE_TEXT,
            provider,
            ProseConfig(model="measured-model", output_budget=17),
        )

    assert raised.value.pendencia.classification == "TOOL_BLOCKED"
    assert raised.value.pendencia.slot == "prosa"


def test_no_llm_completes_with_marked_gaps_without_calling_provider() -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField("Não deve ser usado", True),
            briefing_objective=GroundedField("Não deve ser usado", True),
        )
    )

    drafted = draft_prose(
        PAGES,
        SITE_TEXT,
        provider,
        None,
        no_llm=True,
    )

    assert provider.calls == []
    assert drafted.token_values["{{SOBRE_A_EMPRESA}}"].startswith(
        "[PENDÊNCIA GATED:"
    )
    assert drafted.token_values["{{BRIEFING_INICIAL}}"].startswith(
        "[PENDÊNCIA GATED:"
    )
    assert drafted.token_values["{{LISTA_DE_PAGINAS}}"].endswith(
        "Política de Privacidade."
    )
    assert all(item.classification == "GATED" for item in drafted.pendencias)


def test_provider_input_type_rejects_raw_markup() -> None:
    with pytest.raises(ValueError, match="raw markup"):
        ExtractedPageText(
            url="https://example.test/",
            text="<main>Texto do site</main>",
        )
