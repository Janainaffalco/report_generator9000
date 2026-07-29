import sys
from pathlib import Path

from fastapi.testclient import TestClient

from report_generator9000.sheet_store import SheetStore
from report_generator9000.web import DEFAULT_STATIC_DIR, create_app


sys.path.insert(0, str(Path(__file__).with_name("fixtures")))
import generate_control_sheet  # noqa: E402


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
