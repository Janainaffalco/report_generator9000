import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from report_generator9000.gates.results import GateReport, GateResult, Violation
from report_generator9000.generate import StopCondition
from report_generator9000.master import build_master
from report_generator9000.prose import (
    GroundedField,
    ProseConfig,
    ProseRequest,
    ProseResponse,
)
from report_generator9000.run_context import Pendencia
from report_generator9000.sheet_store import SheetStore
from report_generator9000.control_sheet import Engagement
from report_generator9000.runs import GateRejected, RunService, RunStore, STAGES
from report_generator9000.web import DEFAULT_STATIC_DIR, create_app


sys.path.insert(0, str(Path(__file__).with_name("fixtures")))
import generate_control_sheet  # noqa: E402
from tests.test_lista_paginas import serve_fixture_site  # noqa: E402
from tests.test_master_build import approved_source  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"


def _client(tmp_path: Path) -> TestClient:
    store = SheetStore(tmp_path / "sheets")
    return TestClient(create_app(static_dir=tmp_path / "missing-web", sheet_store=store))


def _upload(client: TestClient, path: Path, filename: str = "planilha.xlsx"):
    with path.open("rb") as handle:
        return client.post(
            "/api/control-sheet",
            files={
                "file": (
                    filename,
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )


def test_app_serves_the_frontend_and_supports_spa_routes(tmp_path: Path) -> None:
    static_dir = tmp_path / "web"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<main data-testid="app-shell">Relatórios SEBRAETEC</main>',
        encoding="utf-8",
    )
    (assets_dir / "app.css").write_text(":root { --primary: #e60023; }", encoding="utf-8")

    client = TestClient(create_app(static_dir=static_dir))

    root_response = client.get("/")
    stage_response = client.get("/enviar", headers={"accept": "text/html"})
    asset_response = client.get("/assets/app.css")

    assert root_response.status_code == 200
    assert root_response.text == stage_response.text
    assert 'data-testid="app-shell"' in root_response.text
    assert asset_response.status_code == 200
    assert "--primary: #e60023" in asset_response.text


def test_health_endpoint_does_not_depend_on_the_frontend_build(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=tmp_path / "missing"))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_packaged_frontend_is_the_served_application_shell() -> None:
    assert (DEFAULT_STATIC_DIR / "index.html").is_file()

    client = TestClient(create_app())
    response = client.get("/enviar", headers={"accept": "text/html"})

    assert response.status_code == 200
    assert "Relatórios · SEBRAETEC" in response.text
    assert "fonts.googleapis.com" not in response.text


def test_control_sheet_upload_returns_three_groups_from_fixture(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE, "Planilha para controle de relatorios.xlsx")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "Planilha para controle de relatorios.xlsx"
    assert body["sheet_id"]
    assert [row["row"]["row_number"] for row in body["engagements"]] == [2, 5, 6, 14]
    assert [row["row"]["row_number"] for row in body["stop_conditions"]] == [
        3, 4, 8, 11, 13, 16,
    ]
    assert body["skipped_rows"]["total"] == 2
    assert body["skipped_rows"]["resumo"] == "2 linhas ficaram de fora"


def test_every_engagement_field_named_in_the_contract_is_present(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE)

    engagement = response.json()["engagements"][0]
    assert engagement == {
        "row": {"pasta": "40-2026", "row_number": 2},
        "demanda": "011616/2026",
        "razao_social": "DENISE BARROS DE ALMEIDA",
        "especialista": "Bruno Henrique Santana Leal",
        "kick_off": "15/04/2026",
        "capture_origin": "https://denise.example/",
        "published_domain": None,
    }


def test_stop_conditions_are_translated_and_carry_the_original_cause(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE)

    by_cause = {
        row["cause"]: row for row in response.json()["stop_conditions"]
    }
    assert by_cause["Pasta is absent"] == {
        "row": {"pasta": None, "row_number": 8},
        "coluna": "nº da pasta",
        "problema": "A coluna nº da pasta está vazia.",
        "solucao": "Preencha o número da pasta, como 115-2026.",
        "cause": "Pasta is absent",
    }
    assert by_cause["Link is absent"]["coluna"] == "Link"
    assert by_cause["Link is absent"]["problema"] == "A coluna Link está vazia."
    assert (
        by_cause["Link contains a delivery date"]["problema"]
        == "A coluna Link tem uma data no lugar do endereço."
    )
    assert (
        by_cause["Link is not a URL"]["problema"]
        == "O que está na coluna Link não é um endereço de site."
    )
    assert by_cause["Link is not a URL"]["row"] == {"pasta": "45-2026", "row_number": 16}
    assert (
        by_cause["CNPJ must contain 13 or 14 digits"]["coluna"] == "CNPJ"
    )
    assert by_cause["Kick off is not a date"]["coluna"] == "Kick off"
    assert set(by_cause) == {
        "Link is absent",
        "Link contains a delivery date",
        "Link is not a URL",
        "Pasta is absent",
        "CNPJ must contain 13 or 14 digits",
        "Kick off is not a date",
    }


def test_skipped_rows_are_grouped_by_reason_with_counts(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE)

    skipped = response.json()["skipped_rows"]
    reasons = {reason["cause"]: reason for reason in skipped["reasons"]}
    assert reasons["Tema is out of scope"]["titulo"] == "Tema fora do escopo"
    assert reasons["Tema is out of scope"]["total"] == 1
    assert reasons["Tema is out of scope"]["rows"] == [
        {"pasta": "72-2026", "row_number": 10}
    ]
    assert reasons["already complete"]["titulo"] == "Relatório já marcado como pronto"
    assert reasons["already complete"]["total"] == 1
    assert reasons["already complete"]["rows"] == [
        {"pasta": "26-2026", "row_number": 7}
    ]


def test_zero_engagement_workbook_returns_200_with_empty_list(tmp_path: Path) -> None:
    empty = generate_control_sheet.build(tmp_path / "empty.xlsx", rows=(), row_numbers=())
    client = _client(tmp_path)

    response = _upload(client, empty)

    assert response.status_code == 200
    body = response.json()
    assert body["engagements"] == []
    assert body["stop_conditions"] == []
    assert body["skipped_rows"] == {"total": 0, "resumo": "0 linhas ficaram de fora", "reasons": []}


def test_non_workbook_upload_returns_422(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/control-sheet",
        files={"file": ("nota.txt", b"nao sou uma planilha", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Este arquivo não é uma planilha .xlsx que possamos ler."
    }


def test_workbook_without_lv_e_site_worksheet_returns_422(tmp_path: Path) -> None:
    other_sheet = generate_control_sheet.build(
        tmp_path / "outra-aba.xlsx", sheet_name="Outra aba"
    )
    client = _client(tmp_path)

    response = _upload(client, other_sheet)

    assert response.status_code == 422
    assert response.json() == {"detail": "A planilha não tem a aba “LV e Site”."}


def test_worksheet_missing_expected_columns_says_so_rather_than_blaming_the_file(
    tmp_path: Path,
) -> None:
    without_pasta = generate_control_sheet.build(
        tmp_path / "sem-coluna.xlsx",
        headers=tuple(
            header
            for header in generate_control_sheet.HEADERS
            if "pasta" not in header.casefold()
        ),
        rows=(),
        row_numbers=(),
    )
    client = _client(tmp_path)

    response = _upload(client, without_pasta)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "A aba “LV e Site” não tem as colunas esperadas."
    }


def test_an_empty_worksheet_reports_the_columns_not_a_corrupt_file(
    tmp_path: Path,
) -> None:
    empty_sheet = generate_control_sheet.build(
        tmp_path / "aba-vazia.xlsx", headers=(), rows=(), row_numbers=()
    )
    client = _client(tmp_path)

    response = _upload(client, empty_sheet)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "A aba “LV e Site” não tem as colunas esperadas."
    }


def test_two_sequential_uploads_both_succeed_and_are_independently_retained(
    tmp_path: Path,
) -> None:
    empty = generate_control_sheet.build(tmp_path / "empty.xlsx", rows=(), row_numbers=())
    client = _client(tmp_path)

    first = _upload(client, FIXTURE, "primeira.xlsx")
    second = _upload(client, empty, "segunda.xlsx")

    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.json()["sheet_id"]
    second_id = second.json()["sheet_id"]
    assert first_id != second_id
    assert first.json()["engagements"]
    assert second.json()["engagements"] == []


def test_copy_never_claims_two_addresses_in_one_cell_are_an_error(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE)

    body = response.json()
    concatenated = next(
        row for row in body["engagements"] if row["row"]["row_number"] == 5
    )
    assert concatenated["capture_origin"] == (
        "https://midnightblue-jellyfish-121804.hostingersite.com/"
    )
    assert concatenated["published_domain"] == "sanfrio.com.br"
    all_copy = " ".join(
        text
        for row in body["stop_conditions"]
        for text in (row["problema"], row["solucao"])
    )
    assert "dois endere" not in all_copy.lower()
    assert "duas urls" not in all_copy.lower()


def test_the_same_pasta_on_two_rows_is_disambiguated_by_row_number(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE)

    matching = [
        row["row"]
        for row in response.json()["engagements"]
        if row["row"]["pasta"] == "40-2026"
    ]
    assert matching == [
        {"pasta": "40-2026", "row_number": 2},
        {"pasta": "40-2026", "row_number": 14},
    ]


def test_starting_one_engagement_returns_immediately_then_polls_and_downloads(
    tmp_path: Path,
) -> None:
    sheet_store = SheetStore(tmp_path / "sheets")
    app = create_app(
        static_dir=tmp_path / "missing-web",
        sheet_store=sheet_store,
    )
    release = Event()
    entered = Event()

    def assemble(master, output_root, engagement, gated_root, **options):
        progress = options["progress"]
        for stage in STAGES:
            if stage == "capture":
                entered.set()
                release.wait(timeout=5)
            progress(stage, 3 if stage == "derive_pages" else None)
        document = (
            Path(output_root)
            / f"RELATÃ“RIO TÃ‰CNICO FINAL - {engagement.pasta}_{engagement.razao_social}.docx"
        )
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b"generated docx")
        return SimpleNamespace(
            pages=(object(), object(), object()),
            previews=(),
            report=SimpleNamespace(
                status="draft",
                document=document,
                gate_report=SimpleNamespace(results=()),
                context=SimpleNamespace(pendencias=()),
            ),
        )

    service = RunService(
        store=RunStore(tmp_path / "runs"),
        master=tmp_path / "MASTER.docx",
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        assembler=assemble,
        no_llm=True,
    )
    app.state.run_service = service
    client = TestClient(app)
    uploaded = _upload(client, FIXTURE)

    started_at = monotonic()
    response = client.post(
        "/api/runs",
        json={
            "sheet_id": uploaded.json()["sheet_id"],
            "row_number": 2,
        },
    )
    elapsed = monotonic() - started_at

    assert response.status_code == 202
    assert elapsed < 1
    assert response.headers["location"] == (
        f"/api/runs/{response.json()['run_id']}"
    )
    assert entered.wait(timeout=2)
    running = client.get(response.headers["location"]).json()
    assert running["outcome"] == "running"
    assert running["current_stage"] == "capture"
    assert running["page_count"] == 3
    assert [stage["name"] for stage in running["stages"]] == list(STAGES)
    assert running["stage_history"] == [
        "read_row",
        "open_origin",
        "derive_pages",
    ]
    assert [stage["state"] for stage in running["stages"][:4]] == [
        "done",
        "done",
        "done",
        "current",
    ]

    release.set()
    deadline = monotonic() + 3
    finished = running
    while finished["outcome"] == "running" and monotonic() < deadline:
        sleep(0.01)
        finished = client.get(response.headers["location"]).json()

    assert finished["outcome"] == "finished"
    assert finished["status"] == "draft"
    assert finished["page_count"] == 3
    assert finished["filename"] == (
        "RELATÃ“RIO TÃ‰CNICO FINAL - 40-2026_DENISE BARROS DE ALMEIDA.docx"
    )
    download = client.get(finished["download_url"])
    assert download.status_code == 200
    assert download.content == b"generated docx"
    disposition = download.headers["content-disposition"]
    assert "40-2026_DENISE%20BARROS%20DE%20ALMEIDA.docx" in disposition
    service.shutdown()


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (StopCondition("Capture Origin indisponÃ­vel"), "stopped"),
        (GateRejected("block-integrity recusou o documento"), "rejected"),
    ],
)
def test_failed_runs_name_the_terminal_outcome_and_never_offer_a_document(
    tmp_path: Path,
    error: Exception,
    outcome: str,
) -> None:
    sheet_store = SheetStore(tmp_path / "sheets")
    app = create_app(
        static_dir=tmp_path / "missing-web",
        sheet_store=sheet_store,
    )

    def fail(*args, **options):
        options["progress"]("read_row", None)
        raise error

    service = RunService(
        store=RunStore(tmp_path / "runs"),
        master=tmp_path / "MASTER.docx",
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        assembler=fail,
        no_llm=True,
    )
    app.state.run_service = service
    client = TestClient(app)
    uploaded = _upload(client, FIXTURE)
    started = client.post(
        "/api/runs",
        json={"sheet_id": uploaded.json()["sheet_id"], "row_number": 2},
    )
    location = started.headers["location"]
    deadline = monotonic() + 2
    record = client.get(location).json()
    while record["outcome"] == "running" and monotonic() < deadline:
        sleep(0.01)
        record = client.get(location).json()

    assert record["outcome"] == outcome
    assert record["reason"] == str(error)
    assert record["filename"] is None
    assert record["download_url"] is None
    assert client.get(f"/api/runs/{record['run_id']}/download").status_code == 404
    service.shutdown()


def test_http_run_drives_real_workbook_master_cloning_and_gates(
    tmp_path: Path,
) -> None:
    class ProseProvider:
        def generate(
            self,
            request: ProseRequest,
            config: ProseConfig,
        ) -> ProseResponse:
            assert request.site_text
            return ProseResponse(
                company_description=GroundedField("Texto para revisão", False),
                briefing_objective=GroundedField("Objetivo para revisão", False),
            )

    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    sheet_store = SheetStore(tmp_path / "sheets")
    app = create_app(
        static_dir=tmp_path / "missing-web",
        sheet_store=sheet_store,
    )
    service = RunService(
        store=RunStore(tmp_path / "runs"),
        master=master,
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        prose_provider=ProseProvider(),
        prose_config=ProseConfig("test-provider", 200),
    )
    app.state.run_service = service
    client = TestClient(app)

    with serve_fixture_site() as origin:
        workbook = generate_control_sheet.build(
            tmp_path / "one-engagement.xlsx",
            rows=(
                (
                    "011616/2026",
                    "40-2026",
                    generate_control_sheet.IN_SCOPE,
                    "52052612000121",
                    "CLIENTE",
                    "Especialista",
                    datetime(2026, 4, 15),
                    origin,
                    "",
                ),
            ),
            row_numbers=(2,),
        )
        gated_folder = tmp_path / "gated" / "40-2026_CLIENTE"
        gated_folder.mkdir(parents=True)
        (gated_folder / "valores.json").write_text(
            json.dumps(
                {
                    "pasta": "40-2026",
                    "razao_social": "CLIENTE",
                    "lista_paginas": [
                        {
                            "tipo": "pagina_principal",
                            "rotulo": "Home",
                            "url": "/",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        uploaded = _upload(client, workbook)
        started = client.post(
            "/api/runs",
            json={
                "sheet_id": uploaded.json()["sheet_id"],
                "row_number": 2,
            },
        )
        location = started.headers["location"]
        deadline = monotonic() + 30
        record = client.get(location).json()
        while record["outcome"] == "running" and monotonic() < deadline:
            sleep(0.05)
            record = client.get(location).json()

    assert record["outcome"] == "finished", record["reason"]
    assert record["page_count"] == 3
    assert [stage["name"] for stage in record["stages"]] == list(STAGES)
    assert {stage["state"] for stage in record["stages"]} == {"done"}
    assert record["stage_history"] == list(STAGES)
    assert record["status"] == "draft"
    downloaded = client.get(record["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content[:2] == b"PK"
    assert "40-2026_CLIENTE.docx" in record["filename"]
    service.shutdown()


def test_expired_run_is_gone_even_when_no_new_run_was_submitted(
    tmp_path: Path,
) -> None:
    app = create_app(
        static_dir=tmp_path / "missing-web",
        sheet_store=SheetStore(tmp_path / "sheets"),
    )
    store = RunStore(tmp_path / "runs")
    service = RunService(
        store=store,
        master=tmp_path / "MASTER.docx",
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        no_llm=True,
    )
    app.state.run_service = service
    record = store.create(
        Engagement(
            row_number=2,
            demanda="011616/2026",
            pasta="40-2026",
            razao_social="CLIENTE",
            cnpj="52.052.612/0001-21",
            kick_off=datetime(2026, 4, 15),
            especialista="Especialista",
            capture_origin="https://example.test/",
            published_domain=None,
        ),
        "retained-sheet",
    )
    path = tmp_path / "runs" / f"{record.run_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")

    client = TestClient(app)
    assert client.get(f"/api/runs/{record.run_id}").status_code == 404
    assert client.get(f"/api/runs/{record.run_id}/download").status_code == 404
    assert not path.exists()
    service.shutdown()


def _finished_run_client(
    tmp_path: Path,
    *,
    gate_report: GateReport,
    pendencias: tuple[Pendencia, ...],
) -> tuple[TestClient, str]:
    sheet_store = SheetStore(tmp_path / "sheets")
    app = create_app(static_dir=tmp_path / "missing-web", sheet_store=sheet_store)

    def assemble(master, output_root, engagement, gated_root, **options):
        progress = options["progress"]
        for stage in STAGES:
            progress(stage, 3 if stage == "derive_pages" else None)
        document = (
            Path(output_root)
            / f"{engagement.pasta}_{engagement.razao_social}"
            / f"RELATÓRIO TÉCNICO FINAL - {engagement.pasta}_{engagement.razao_social}.docx"
        )
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b"generated docx")
        previews_dir = document.parent / "previews"
        previews_dir.mkdir(parents=True, exist_ok=True)
        # Deliberately unequal to the three pages of the Lista de Páginas: a
        # Block spans more than one page in Word, so conflating the two counts
        # would leave the last pages of the document unreachable.
        previews = tuple(
            previews_dir / f"preview-{number:03d}.png"
            for number in range(1, 6)
        )
        for preview in previews:
            preview.write_bytes(_TINY_PNG)
        return SimpleNamespace(
            pages=(object(), object(), object()),
            previews=previews,
            report=SimpleNamespace(
                status=("complete" if not pendencias else "draft"),
                document=document,
                gate_report=gate_report,
                context=SimpleNamespace(pendencias=pendencias),
            ),
        )

    service = RunService(
        store=RunStore(tmp_path / "runs"),
        master=tmp_path / "MASTER.docx",
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        assembler=assemble,
        no_llm=True,
    )
    app.state.run_service = service
    client = TestClient(app)
    uploaded = _upload(client, FIXTURE)
    started = client.post(
        "/api/runs",
        json={"sheet_id": uploaded.json()["sheet_id"], "row_number": 2},
    )
    location = started.headers["location"]
    deadline = monotonic() + 2
    record = client.get(location).json()
    while record["outcome"] == "running" and monotonic() < deadline:
        sleep(0.01)
        record = client.get(location).json()
    assert record["outcome"] == "finished", record
    return client, record["run_id"]


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_finished_report_returns_pendencias_checks_and_download_filename(
    tmp_path: Path,
) -> None:
    gate_report = GateReport(
        results=(
            GateResult(gate="media-provenance"),
            GateResult(
                gate="block-integrity",
                violations=(
                    Violation(
                        gate="block-integrity",
                        rule="heading-without-image",
                        artifact="word/document.xml p=4",
                        detail="SEÇÃO CONTATO",
                    ),
                ),
            ),
        )
    )
    pendencias = (
        Pendencia(
            slot="paleta",
            classification="UNDECLARED",
            reason="site nao declara cores",
            evidence="deadbeef",
            name="paleta de cores",
            page="documento",
            required_action="Revisar a paleta no Word e substituir se necessário",
        ),
        Pendencia(
            slot="capture:foto-home.png",
            classification="TOOL_BLOCKED",
            reason="falha ao capturar a página",
            evidence="cafefeed",
            name="captura da PÁGINA HOME",
            page="PÁGINA HOME",
            required_action="Gerar novamente; se persistir, avise quem cuida do sistema",
        ),
        Pendencia(
            slot="cnpj_doc",
            classification="GATED",
            reason="valor nao fornecido no Gated Drop Folder",
            evidence="[PENDÊNCIA: NÃO FORNECIDO — cnpj_doc]",
            name="cnpj doc",
            page="documento",
            required_action="Fornecer cnpj doc no valores.json",
        ),
    )
    client, run_id = _finished_run_client(
        tmp_path, gate_report=gate_report, pendencias=pendencias
    )

    response = client.get(f"/api/runs/{run_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["page_count"] == 3
    assert body["filename"].endswith(".docx")
    assert body["download_url"] == f"/api/runs/{run_id}/download"
    assert [check["passed"] for check in body["checks"]] == [True, False]
    check_labels = [check["label"] for check in body["checks"]]
    assert "media-provenance" not in check_labels
    assert "block-integrity" not in check_labels
    assert len(set(check_labels)) == 2

    by_classification = {
        item["classification"]: item for item in body["pendencias"]
    }
    assert set(by_classification) == {"UNDECLARED", "TOOL_BLOCKED", "GATED"}
    for item in body["pendencias"]:
        assert "slot" not in item
        assert item["name"]
        assert item["required_action"]
        assert item["page"]
    explanations = {
        item["classification"]: item["classification_explanation"]
        for item in body["pendencias"]
    }
    assert len(set(explanations.values())) == 3
    labels = {
        item["classification"]: item["classification_label"]
        for item in body["pendencias"]
    }
    assert len(set(labels.values())) == 3


def test_finished_report_with_no_pendencias_is_complete_and_empty(
    tmp_path: Path,
) -> None:
    client, run_id = _finished_run_client(
        tmp_path, gate_report=GateReport(results=()), pendencias=()
    )

    response = client.get(f"/api/runs/{run_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["pendencias"] == []


def test_report_endpoint_404s_before_the_run_finishes(tmp_path: Path) -> None:
    sheet_store = SheetStore(tmp_path / "sheets")
    app = create_app(static_dir=tmp_path / "missing-web", sheet_store=sheet_store)
    release = Event()

    def assemble(master, output_root, engagement, gated_root, **options):
        options["progress"]("read_row", None)
        release.wait(timeout=5)
        options["progress"]("open_origin", None)
        raise StopCondition("STOP CONDITION: never finishes")

    service = RunService(
        store=RunStore(tmp_path / "runs"),
        master=tmp_path / "MASTER.docx",
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        assembler=assemble,
        no_llm=True,
    )
    app.state.run_service = service
    client = TestClient(app)
    uploaded = _upload(client, FIXTURE)
    started = client.post(
        "/api/runs",
        json={"sheet_id": uploaded.json()["sheet_id"], "row_number": 2},
    )
    run_id = started.json()["run_id"]

    response = client.get(f"/api/runs/{run_id}/report")

    assert response.status_code == 404
    release.set()
    service.shutdown()


def test_preview_page_images_are_served_as_png(tmp_path: Path) -> None:
    client, run_id = _finished_run_client(
        tmp_path, gate_report=GateReport(results=()), pendencias=()
    )

    first = client.get(f"/api/runs/{run_id}/previews/1")
    missing = client.get(f"/api/runs/{run_id}/previews/99")

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert missing.status_code == 404


def test_every_page_of_the_document_is_reachable_in_the_preview(
    tmp_path: Path,
) -> None:
    """The counted pages are the document's, and each one is actually served.

    The Lista de Páginas and the document's pagination are different numbers —
    a Block spans more than one page in Word — so paging through the review
    screen on the site's page count would leave the tail of the report with no
    thumbnail and no way to reach it.
    """
    client, run_id = _finished_run_client(
        tmp_path, gate_report=GateReport(results=()), pendencias=()
    )
    rendered = sorted(tmp_path.glob("outputs/*/previews/preview-*.png"))

    body = client.get(f"/api/runs/{run_id}/report").json()

    assert rendered, "the fake assembler rendered no preview pages"
    assert body["preview_page_count"] == len(rendered)
    assert body["preview_page_count"] != body["page_count"]
    served = [
        client.get(f"/api/runs/{run_id}/previews/{page}")
        for page in range(1, body["preview_page_count"] + 1)
    ]
    assert [response.status_code for response in served] == [200] * len(rendered)
    assert (
        client.get(
            f"/api/runs/{run_id}/previews/{body['preview_page_count'] + 1}"
        ).status_code
        == 404
    )
