from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from report_generator9000.lista_paginas import (
    AREA_LEGAL,
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    Pagina,
)
from report_generator9000.control_sheet import Engagement
from report_generator9000.capture import CaptureConfig, extract_site_text
from report_generator9000.generate import (
    ReportGenerationError,
    generate_report,
)
from report_generator9000.generate_cli import build_parser, load_prose_provider
from report_generator9000.master import build_master
from report_generator9000.prose import (
    ExtractedPageText,
    GroundingCitation,
    GroundedField,
    ProseBudgetExceeded,
    ProseConfig,
    ProseRequest,
    ProseResponse,
    draft_prose,
)
from report_generator9000.runs import PACKAGED_MASTER_PATH
from report_generator9000.docx_package import open_docx_package
from tests.test_master_build import approved_source
from tests.test_lista_paginas import serve_fixture_site


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
        capture_origin="https://example.test/",
        text="A Acme fabrica componentes industriais desde 1998.",
    ),
    ExtractedPageText(
        capture_origin="https://example.test/servicos",
        text="Projetamos componentes sob medida para linhas de produção.",
    ),
)
COMPANY_CITATION = GroundingCitation(
    source_id="page-1",
    excerpt="A Acme fabrica componentes industriais desde 1998.",
)
OBJECTIVE_CITATION = GroundingCitation(
    source_id="page-2",
    excerpt="Projetamos componentes sob medida para linhas de produção.",
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


def configured_provider_factory() -> CannedProvider:
    return CannedProvider(
        ProseResponse(
            company_description=GroundedField(
                "Empresa",
                True,
                (COMPANY_CITATION,),
            ),
            briefing_objective=GroundedField(
                "Objetivo",
                True,
                (OBJECTIVE_CITATION,),
            ),
        )
    )


def test_grounded_provider_authors_only_two_fields_and_pages_are_deterministic() -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField(
                "A Acme fabrica componentes industriais.",
                grounded=True,
                citations=(COMPANY_CITATION,),
            ),
            briefing_objective=GroundedField(
                "O projeto tem como objetivo apresentar os componentes da Acme.",
                grounded=True,
                citations=(OBJECTIVE_CITATION,),
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
    assert [item.source_id for item in request.site_text] == [
        "page-1",
        "page-2",
    ]
    assert [item.text for item in request.site_text] == [
        item.text for item in SITE_TEXT
    ]
    assert not hasattr(request.site_text[0], "capture_origin")
    assert received_config is config
    assert len(drafted.pendencias) == 2
    assert all(
        item.classification == "REVIEW" for item in drafted.pendencias
    )
    assert all("Revisar" in item.required_action for item in drafted.pendencias)
    assert all(item.evidence in drafted.token_values.values() for item in drafted.pendencias)
    assert [item.capture_origin for item in drafted.grounding] == [
        "https://example.test/",
        "https://example.test/servicos",
    ]
    assert [item.excerpt for item in drafted.grounding] == [
        COMPANY_CITATION.excerpt,
        OBJECTIVE_CITATION.excerpt,
    ]


@pytest.mark.parametrize(
    ("company", "objective"),
    [
        (
            GroundedField(None, grounded=True),
            GroundedField("Objetivo", True, (OBJECTIVE_CITATION,)),
        ),
        (
            GroundedField("Empresa", grounded=False),
            GroundedField("Objetivo", True, (OBJECTIVE_CITATION,)),
        ),
        (
            GroundedField("Empresa", True, (COMPANY_CITATION,)),
            GroundedField(None, False),
        ),
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
            "[PENDÊNCIA: FALHA NA AUTOMAÇÃO — descrição da empresa sem "
            "base no site]"
        )
    if not objective.grounded or objective.value is None:
        assert values["{{BRIEFING_INICIAL}}"] == (
            "[PENDÊNCIA: FALHA NA AUTOMAÇÃO — objetivo do briefing sem "
            "base no site]"
        )
    assert all(item.evidence in values.values() for item in drafted.pendencias)


def test_partial_prose_rejection_logs_the_specific_field_reason(
    recording_sink,
) -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField(
                "A Acme fabrica componentes industriais.",
                True,
                (COMPANY_CITATION,),
            ),
            briefing_objective=GroundedField(None, False),
        )
    )

    drafted = draft_prose(
        PAGES,
        SITE_TEXT,
        provider,
        ProseConfig(model="m", output_budget=500),
    )

    assert drafted.token_values["{{BRIEFING_INICIAL}}"].startswith(
        "[PENDÊNCIA: FALHA NA AUTOMAÇÃO —"
    )
    rejections = [
        event
        for event in recording_sink.events
        if event.name == "prose_field_rejected"
    ]
    assert len(rejections) == 1
    assert rejections[0].fields == {
        "slot": "objetivo_briefing",
        "reason": "missing_value",
        "citation_count": 0,
    }


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
        "[PENDÊNCIA: NÃO FORNECIDO —"
    )
    assert drafted.token_values["{{BRIEFING_INICIAL}}"].startswith(
        "[PENDÊNCIA: NÃO FORNECIDO —"
    )
    assert drafted.token_values["{{LISTA_DE_PAGINAS}}"].endswith(
        "Política de Privacidade."
    )
    assert all(item.classification == "GATED" for item in drafted.pendencias)


def test_provider_input_type_rejects_raw_markup() -> None:
    with pytest.raises(ValueError, match="raw markup"):
        ExtractedPageText(
            capture_origin="https://example.test/",
            text="<main>Texto do site</main>",
        )


def test_grounded_claim_without_exact_site_excerpt_becomes_a_gap() -> None:
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField(
                "A Acme é líder mundial.",
                True,
                (
                    GroundingCitation(
                        source_id="page-1",
                        excerpt="líder mundial",
                    ),
                ),
            ),
            briefing_objective=GroundedField(
                "Objetivo",
                True,
                (OBJECTIVE_CITATION,),
            ),
        )
    )

    drafted = draft_prose(
        PAGES,
        SITE_TEXT,
        provider,
        ProseConfig(model="m", output_budget=500),
    )

    assert drafted.token_values["{{SOBRE_A_EMPRESA}}"].startswith(
        "[PENDÊNCIA: FALHA NA AUTOMAÇÃO —"
    )


def _engagement() -> Engagement:
    return Engagement(
        row_number=2,
        demanda="011616/2026",
        pasta="40-2026",
        razao_social="CLIENTE",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin="https://example.test/",
        published_domain=None,
    )


def test_no_llm_reaches_the_report_and_pendencias_sidecars(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master

    generated = generate_report(
        master,
        tmp_path / "reports",
        _engagement(),
        tmp_path / "absent-gated",
        pages=PAGES,
        no_llm=True,
    )

    package = open_docx_package(generated.document)
    text = "\n".join(part.text or "" for part in package.parts)
    assert "{{SOBRE_A_EMPRESA}}" not in text
    assert "{{BRIEFING_INICIAL}}" not in text
    assert "{{LISTA_DE_PAGINAS}}" not in text
    assert (
        "[PENDÊNCIA: NÃO FORNECIDO — descrição da empresa não gerada "
        "(--no-llm)]"
    ) in text
    assert "Home, Serviços e Política de Privacidade" in text
    assert {
        item.slot
        for item in generated.context.pendencias
    }.issuperset({"descricao_empresa", "objetivo_briefing"})
    sidecar = json.loads(generated.context_document.read_text(encoding="utf-8"))
    assert sidecar["prose_grounding"] == []


def test_budget_failure_stops_report_generation_with_tool_classification(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    provider = CannedProvider(
        ProseResponse(
            company_description=GroundedField("Parcial", True),
            briefing_objective=GroundedField("Parcial", True),
            output_budget_exhausted=True,
        )
    )

    with pytest.raises(ReportGenerationError) as raised:
        generate_report(
            master,
            tmp_path / "reports",
            _engagement(),
            tmp_path / "absent-gated",
            pages=PAGES,
            site_text=SITE_TEXT,
            prose_provider=provider,
            prose_config=ProseConfig("configured", 17),
        )

    assert raised.value.pendencia is not None
    assert raised.value.pendencia.classification == "TOOL_BLOCKED"
    assert not list((tmp_path / "reports").rglob("*.docx"))


def test_cli_exposes_no_llm_model_and_budget_configuration() -> None:
    parser = build_parser()

    no_llm = parser.parse_args(["--linha", "40-2026", "--no-llm"])
    configured = parser.parse_args(
        [
            "--linha",
            "40-2026",
            "--prose-model",
            "configured-model",
            "--prose-output-budget",
            "730",
            "--prose-provider",
            f"{__name__}:configured_provider_factory",
        ]
    )

    assert no_llm.no_llm is True
    assert no_llm.master == PACKAGED_MASTER_PATH
    assert configured.prose_model == "configured-model"
    assert configured.prose_output_budget == 730
    assert isinstance(
        load_prose_provider(configured.prose_provider),
        CannedProvider,
    )


def test_visible_site_text_is_script_extracted_with_a_real_browser() -> None:
    with serve_fixture_site() as origin:
        pages = (
            Pagina(PAGINA_PRINCIPAL, "Home", origin, "PÁGINA HOME"),
            Pagina(ELEMENTO_TRANSVERSAL, "Rodapé", origin, "RODAPÉ"),
        )
        extracted = extract_site_text(
            pages,
            config=CaptureConfig(
                viewport_width=800,
                viewport_height=500,
                device_scale_factor=1,
                navigation_timeout_ms=10_000,
                network_idle_timeout_ms=2_000,
                lazy_settle_ms=150,
                embedding_max_width=600,
                minimum_color_count=8,
            ),
        )

    assert len(extracted) == 1
    assert extracted[0].capture_origin == origin
    assert "Site de teste" in extracted[0].text
    assert "<main" not in extracted[0].text
