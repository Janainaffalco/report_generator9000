import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
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
from report_generator9000.previews import PreviewRender
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


def _set_uploaded_at(
    sheet_directory: Path, sheet_id: str, uploaded_at: datetime
) -> None:
    metadata_path = sheet_directory / f"{sheet_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["uploaded_at"] = uploaded_at.isoformat()
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8"
    )


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
    assert [row["row"]["row_number"] for row in body["engagements"]] == [
        2, 5, 6, 7, 14,
    ]
    assert [row["row"]["row_number"] for row in body["stop_conditions"]] == [
        3, 4, 8, 11, 13, 16,
    ]
    assert body["unsupported_rows"]["total"] == 1


def test_report_ready_text_is_display_only_and_returned_verbatim(
    tmp_path: Path,
) -> None:
    rows = (
        (
            "013300/2026",
            "130-2026",
            generate_control_sheet.IN_SCOPE,
            "52052612000121",
            "PRAZO MAIÚSCULO",
            "Bruno Henrique Santana Leal",
            datetime(2026, 7, 1),
            "https://prazo.example/",
            "  PRazo prorrogado  ",
        ),
        (
            "013301/2026",
            "131-2026",
            generate_control_sheet.IN_SCOPE,
            "67671933000181",
            "RELATÓRIO ENVIADO",
            "Bruno Henrique Santana Leal",
            datetime(2026, 7, 2),
            "https://enviado.example/",
            "ok Enviado",
        ),
    )
    workbook = generate_control_sheet.build(
        tmp_path / "status-display-only.xlsx",
        rows=rows,
        row_numbers=(2, 3),
    )
    client = _client(tmp_path)

    response = _upload(client, workbook)

    assert response.status_code == 200
    body = response.json()
    assert [
            (item["row"]["row_number"], item["report_ready_text"])
        for item in body["engagements"]
    ] == [
        (2, "  PRazo prorrogado  "),
        (3, "ok Enviado"),
    ]


def test_july_prorogated_rows_are_recovered_from_status_filtering(
    tmp_path: Path,
) -> None:
    row_numbers = (33, 38, 39, 45, 46, 47, 52, 53)
    statuses = (
        "Prazo Prorrogado",
        "Prazo prorrogado",
        "Prazo prorrogado",
        "PRazo prorrogado",
        "PRazo prorrogado",
        "PRazo prorrogado",
        "PRazo prorrogado",
        "PRazo prorrogado",
    )
    links = (
        "https://row-33.example/",
        "row-38.example",
        "https://row-39.example/",
        "",
        "https://row-46.example/",
        "https://row-47.example/wp-admin",
        "https://row-52.example/",
        "",
    )
    rows = tuple(
        (
            f"013{row_number:03}/2026",
            f"{row_number}-2026",
            generate_control_sheet.IN_SCOPE,
            "52052612000121",
            f"CLIENTE {row_number}",
            "Bruno Henrique Santana Leal",
            datetime(2026, 7, 1),
            link,
            status,
        )
        for row_number, link, status in zip(
            row_numbers, links, statuses, strict=True
        )
    )
    workbook = generate_control_sheet.build(
        tmp_path / "july-prorogated.xlsx",
        rows=rows,
        row_numbers=row_numbers,
    )
    client = _client(tmp_path)

    response = _upload(client, workbook)

    assert response.status_code == 200
    body = response.json()
    assert [
        item["row"]["row_number"] for item in body["engagements"]
    ] == [33, 39, 46, 47, 52]
    assert [
        (item["row"]["row_number"], item["coluna"])
        for item in body["stop_conditions"]
    ] == [(38, "Link"), (45, "Link"), (53, "Link")]
    returned_statuses = {
        item["row"]["row_number"]: item["report_ready_text"]
        for group in ("engagements", "stop_conditions")
        for item in body[group]
    }
    assert returned_statuses == dict(
        zip(row_numbers, statuses, strict=True)
    )


def test_every_worksheet_row_is_ready_blocked_or_unsupported(tmp_path: Path) -> None:
    valid = (
        "013300/2026",
        "130-2026",
        generate_control_sheet.IN_SCOPE,
        "52052612000121",
        "CLIENTE",
        "Bruno Henrique Santana Leal",
        datetime(2026, 7, 1),
        "https://cliente.example/",
        "Prazo prorrogado",
    )
    rows = (
        valid,
        (*valid[:2], "", *valid[3:]),
        (valid[0], "", *valid[2:]),
        (*valid[:7], "", valid[8]),
        (*valid[:3], "", *valid[4:]),
        (*valid[:6], "", *valid[7:]),
        (
            valid[0],
            "131-2026",
            generate_control_sheet.OUT_OF_SCOPE,
            *valid[3:7],
            "",
            "PRazo prorrogado",
        ),
    )
    workbook = generate_control_sheet.build(
        tmp_path / "every-row.xlsx",
        rows=rows,
        row_numbers=(2, 3, 4, 5, 6, 7, 8),
    )
    client = _client(tmp_path)

    response = _upload(client, workbook)

    assert response.status_code == 200
    body = response.json()
    assert "skipped_rows" not in body
    assert [item["row"]["row_number"] for item in body["engagements"]] == [2]
    assert {
        item["row"]["row_number"]: item["coluna"]
        for item in body["stop_conditions"]
    } == {
        3: "Tema",
        4: "nº da pasta",
        5: "Link",
        6: "CNPJ",
        7: "Kick off",
    }
    assert body["unsupported_rows"] == {
        "total": 1,
        "rows": [
            {
                "row": {"pasta": "131-2026", "row_number": 8},
                "tema": generate_control_sheet.OUT_OF_SCOPE,
                "demanda": "013300/2026",
                "razao_social": "CLIENTE",
                "especialista": "Bruno Henrique Santana Leal",
                "kick_off": "01/07/2026",
                "link": "",
                "report_ready_text": "PRazo prorrogado",
                "cause": "Tema is unsupported",
                "explicacao": (
                    "Ainda não existe um Master aprovado para este Tema."
                ),
            }
        ],
    }
    returned_rows = {
        item["row"]["row_number"] for item in body["engagements"]
    } | {
        item["row"]["row_number"] for item in body["stop_conditions"]
    } | {
        item["row"]["row_number"] for item in body["unsupported_rows"]["rows"]
    }
    assert returned_rows == {2, 3, 4, 5, 6, 7, 8}


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
        "report_ready_text": "",
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
        "demanda": "011910/2026",
        "razao_social": "CLINICA SILVIA",
        "especialista": "Bruno Henrique Santana Leal",
        "kick_off": "13/05/2026",
        "link": "https://missing-pasta.example/",
        "coluna": "nº da pasta",
        "problema": "A coluna nº da pasta está vazia.",
        "solucao": "Preencha o número da pasta, como 115-2026.",
        "cause": "Pasta is absent",
        "report_ready_text": "",
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


def test_unsupported_rows_include_tema_and_report_ready_text(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = _upload(client, FIXTURE)

    unsupported = response.json()["unsupported_rows"]
    assert unsupported == {
        "total": 1,
        "rows": [
            {
                "row": {"pasta": "72-2026", "row_number": 10},
                "tema": generate_control_sheet.OUT_OF_SCOPE,
                "demanda": "011547/2026",
                "razao_social": "CASA NOSSA",
                "especialista": "Christian Albuquerque Alonso",
                "kick_off": "21/04/2026",
                "link": "https://out-of-scope.example/",
                "report_ready_text": "",
                "cause": "Tema is unsupported",
                "explicacao": (
                    "Ainda não existe um Master aprovado para este Tema."
                ),
            }
        ],
    }


def test_zero_engagement_workbook_returns_200_with_empty_list(tmp_path: Path) -> None:
    empty = generate_control_sheet.build(tmp_path / "empty.xlsx", rows=(), row_numbers=())
    client = _client(tmp_path)

    response = _upload(client, empty)

    assert response.status_code == 200
    body = response.json()
    assert body["engagements"] == []
    assert body["stop_conditions"] == []
    assert body["unsupported_rows"] == {
        "total": 0,
        "rows": [],
    }


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
    assert client.get(f"/api/control-sheet/{first_id}").status_code == 200
    assert client.get(f"/api/control-sheet/{second_id}").status_code == 200


def test_uploaded_sheet_is_retrievable_after_sheet_store_restarts(
    tmp_path: Path,
) -> None:
    sheet_directory = tmp_path / "sheets"
    first_client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(sheet_directory),
        )
    )
    uploaded = _upload(first_client, FIXTURE, "controle julho.xlsx")

    restarted_client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(sheet_directory),
        )
    )
    retained = restarted_client.get(
        f"/api/control-sheet/{uploaded.json()['sheet_id']}"
    )

    assert retained.status_code == 200
    assert retained.json()["filename"] == "controle julho.xlsx"
    assert retained.json()["engagements"] == uploaded.json()["engagements"]


def test_retained_sheet_rows_are_rederived_from_the_workbook_on_every_read(
    tmp_path: Path,
) -> None:
    sheet_directory = tmp_path / "sheets"
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(sheet_directory),
        )
    )
    uploaded = _upload(client, FIXTURE, "controle.xlsx").json()
    empty = generate_control_sheet.build(
        tmp_path / "edited.xlsx", rows=(), row_numbers=()
    )
    uploaded_at = client.get("/api/control-sheets").json()[0]["uploaded_at"]

    (sheet_directory / f"{uploaded['sheet_id']}.xlsx").write_bytes(
        empty.read_bytes()
    )
    reread = client.get(
        f"/api/control-sheet/{uploaded['sheet_id']}"
    )

    assert reread.status_code == 200
    assert reread.json()["engagements"] == []
    assert client.get("/api/control-sheets").json()[0]["uploaded_at"] == uploaded_at


def test_retained_sheet_listing_is_most_recent_first_with_ready_counts(
    tmp_path: Path,
) -> None:
    sheet_directory = tmp_path / "sheets"
    static_directory = tmp_path / "missing-web"
    static_directory.mkdir()
    client = TestClient(
        create_app(
            static_dir=static_directory,
            sheet_store=SheetStore(sheet_directory),
        )
    )
    empty = generate_control_sheet.build(
        tmp_path / "empty.xlsx", rows=(), row_numbers=()
    )
    older = _upload(client, FIXTURE, "controle junho.xlsx").json()
    newer = _upload(client, empty, "controle julho.xlsx").json()
    now = datetime.now(UTC)
    older_uploaded_at = now - timedelta(hours=1)
    newer_uploaded_at = now
    _set_uploaded_at(
        sheet_directory, older["sheet_id"], older_uploaded_at
    )
    _set_uploaded_at(
        sheet_directory, newer["sheet_id"], newer_uploaded_at
    )

    response = client.get("/api/control-sheets")

    assert response.status_code == 200
    assert response.json() == [
        {
            "sheet_id": newer["sheet_id"],
            "filename": "controle julho.xlsx",
            "uploaded_at": newer_uploaded_at.isoformat(),
            "ready_count": 0,
        },
        {
            "sheet_id": older["sheet_id"],
            "filename": "controle junho.xlsx",
            "uploaded_at": older_uploaded_at.isoformat(),
            "ready_count": 5,
        },
    ]


def test_seven_day_sheet_boundary_is_enforced_from_stored_upload_time(
    tmp_path: Path,
) -> None:
    sheet_directory = tmp_path / "sheets"
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(sheet_directory),
        )
    )
    empty = generate_control_sheet.build(
        tmp_path / "expirada.xlsx", rows=(), row_numbers=()
    )
    # Distinct byte content for the two uploads: content-addressed dedupe
    # would otherwise fold them into a single retained sheet.
    retained = _upload(client, FIXTURE, "ainda-retida.xlsx").json()
    expired = _upload(client, empty, "expirada.xlsx").json()
    now = datetime.now(UTC)
    _set_uploaded_at(
        sheet_directory,
        retained["sheet_id"],
        now - timedelta(days=7) + timedelta(seconds=5),
    )
    _set_uploaded_at(
        sheet_directory,
        expired["sheet_id"],
        now - timedelta(days=7) - timedelta(seconds=5),
    )

    listing = client.get("/api/control-sheets")
    expired_read = client.get(
        f"/api/control-sheet/{expired['sheet_id']}"
    )
    unknown_read = client.get("/api/control-sheet/" + ("0" * 32))

    assert [sheet["sheet_id"] for sheet in listing.json()] == [
        retained["sheet_id"]
    ]
    assert expired_read.status_code == 404
    assert "expirou" in expired_read.json()["detail"].casefold()
    assert unknown_read.status_code == 404
    assert "expirou" in unknown_read.json()["detail"].casefold()
    assert not (sheet_directory / f"{expired['sheet_id']}.xlsx").exists()
    assert not (sheet_directory / f"{expired['sheet_id']}.json").exists()
    assert (sheet_directory / f"{retained['sheet_id']}.xlsx").is_file()


def test_saving_identical_bytes_twice_returns_the_same_sheet_id_and_one_file(
    tmp_path: Path,
) -> None:
    store = SheetStore(tmp_path / "sheets")
    data = FIXTURE.read_bytes()

    first_id, first_path = store.save(data, "planilha.xlsx")
    second_id, second_path = store.save(data, "planilha.xlsx")

    assert first_id == second_id
    assert first_path == second_path
    assert list((tmp_path / "sheets").glob("*.xlsx")) == [first_path]


def test_all_returns_one_entry_after_saving_identical_bytes_twice(
    tmp_path: Path,
) -> None:
    store = SheetStore(tmp_path / "sheets")
    data = FIXTURE.read_bytes()

    store.save(data, "planilha.xlsx")
    store.save(data, "planilha.xlsx")

    assert len(store.all()) == 1


def test_saving_edited_bytes_creates_a_second_distinct_sheet(
    tmp_path: Path,
) -> None:
    store = SheetStore(tmp_path / "sheets")
    original = FIXTURE.read_bytes()
    edited = generate_control_sheet.build(
        tmp_path / "edited.xlsx", rows=(), row_numbers=()
    ).read_bytes()

    original_id, _ = store.save(original, "planilha.xlsx")
    edited_id, _ = store.save(edited, "planilha.xlsx")

    assert original_id != edited_id
    assert len(store.all()) == 2


def test_dedupe_survives_a_sheet_store_restart(tmp_path: Path) -> None:
    sheet_directory = tmp_path / "sheets"
    data = FIXTURE.read_bytes()
    first_store = SheetStore(sheet_directory)
    first_id, _ = first_store.save(data, "planilha.xlsx")

    second_store = SheetStore(sheet_directory)
    second_id, _ = second_store.save(data, "planilha.xlsx")

    assert first_id == second_id
    assert list(sheet_directory.glob("*.xlsx")) == [sheet_directory / f"{first_id}.xlsx"]


def test_missing_or_corrupt_sidecar_does_not_break_save_or_listing(
    tmp_path: Path,
) -> None:
    sheet_directory = tmp_path / "sheets"
    store = SheetStore(sheet_directory)
    data = FIXTURE.read_bytes()

    sheet_id, path = store.save(data, "planilha.xlsx")
    (sheet_directory / f"{sheet_id}.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    # A corrupt sidecar must not crash the listing...
    listed = store.all()
    assert len(listed) == 1
    assert listed[0].sheet_id == sheet_id

    # ...nor the save path: re-saving the same bytes still dedupes, falling
    # back to the file's mtime (as `_metadata` already does) to decide
    # whether the match is still inside the retention window.
    resaved_id, resaved_path = store.save(data, "planilha.xlsx")
    assert resaved_id == sheet_id
    assert resaved_path == path

    # Now remove the sidecar entirely and confirm the same tolerance holds.
    (sheet_directory / f"{sheet_id}.json").unlink()
    assert len(store.all()) == 1
    again_id, _ = store.save(data, "planilha.xlsx")
    assert again_id == sheet_id


def test_same_bytes_under_a_different_filename_dedupe_to_the_same_sheet(
    tmp_path: Path,
) -> None:
    store = SheetStore(tmp_path / "sheets")
    data = FIXTURE.read_bytes()

    first_id, _ = store.save(data, "controle junho.xlsx")
    second_id, _ = store.save(data, "controle junho (1).xlsx")

    assert first_id == second_id


def test_expired_sheet_is_not_matched_by_dedupe(tmp_path: Path) -> None:
    sheet_directory = tmp_path / "sheets"
    store = SheetStore(sheet_directory)
    data = FIXTURE.read_bytes()

    first_id, first_path = store.save(data, "planilha.xlsx")
    _set_uploaded_at(
        sheet_directory, first_id, datetime.now(UTC) - timedelta(days=7, seconds=5)
    )

    second_id, second_path = store.save(data, "planilha.xlsx")

    assert second_id == first_id  # content-addressed: same id, refreshed contents
    assert second_path == first_path
    # The refreshed save must not still read as expired.
    assert store.path(second_id) == second_path
    metadata = json.loads(
        (sheet_directory / f"{second_id}.json").read_text(encoding="utf-8")
    )
    assert datetime.fromisoformat(metadata["uploaded_at"]) > datetime.now(UTC) - timedelta(
        minutes=1
    )


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


def test_batch_runs_sequentially_and_isolates_stop_and_gate_failures(
    tmp_path: Path,
) -> None:
    sheet_store = SheetStore(tmp_path / "sheets")
    app = create_app(
        static_dir=tmp_path / "missing-web",
        sheet_store=sheet_store,
    )
    first_entered = Event()
    release_first = Event()
    active_lock = Lock()
    active = 0
    max_active = 0
    start_order: list[int] = []

    def assemble(master, output_root, engagement, gated_root, **options):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
            start_order.append(engagement.row_number)
        try:
            if len(start_order) == 1:
                first_entered.set()
                release_first.wait(timeout=5)
            if len(start_order) == 2:
                raise StopCondition("Capture Origin indisponível")
            if len(start_order) == 3:
                raise GateRejected("block-integrity recusou o documento")
            progress = options["progress"]
            for stage in STAGES:
                progress(stage, 3 if stage == "derive_pages" else None)
            document = (
                Path(output_root)
                / f"RELATÓRIO TÉCNICO FINAL - {engagement.pasta}_{engagement.razao_social}.docx"
            )
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_bytes(f"document for row {engagement.row_number}".encode())
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
        finally:
            with active_lock:
                active -= 1

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
    uploaded = _upload(client, FIXTURE).json()
    row_numbers = [
        engagement["row"]["row_number"]
        for engagement in uploaded["engagements"][:4]
    ]

    response = client.post(
        "/api/batches",
        json={
            "sheet_id": uploaded["sheet_id"],
            "row_numbers": row_numbers,
        },
    )

    assert response.status_code == 202
    batch = response.json()
    assert response.headers["location"] == f"/api/batches/{batch['batch_id']}"
    assert [run["engagement"]["row_number"] for run in batch["runs"]] == row_numbers
    assert first_entered.wait(timeout=2)
    working = client.get(response.headers["location"]).json()
    assert working["runs"][0]["outcome"] == "running"
    assert [run["outcome"] for run in working["runs"][1:]] == [
        "queued",
        "queued",
        "queued",
    ]

    release_first.set()
    deadline = monotonic() + 3
    finished = working
    while any(
        run["outcome"] in {"queued", "running"} for run in finished["runs"]
    ) and monotonic() < deadline:
        sleep(0.01)
        finished = client.get(response.headers["location"]).json()

    assert [run["outcome"] for run in finished["runs"]] == [
        "finished",
        "stopped",
        "rejected",
        "finished",
    ]
    assert finished["runs"][1]["reason"] == "Capture Origin indisponível"
    assert finished["runs"][2]["reason"] == "block-integrity recusou o documento"
    assert finished["runs"][0]["download_url"]
    assert finished["runs"][3]["download_url"]
    assert start_order == row_numbers
    assert max_active == 1
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


def test_past_runs_lists_finished_reports_and_removes_expired_directories(
    tmp_path: Path,
) -> None:
    app = create_app(
        static_dir=tmp_path / "missing-web",
        sheet_store=SheetStore(tmp_path / "sheets"),
    )
    store = RunStore(tmp_path / "runs")
    output_root = tmp_path / "outputs"
    service = RunService(
        store=store,
        master=tmp_path / "MASTER.docx",
        output_root=output_root,
        gated_drop_root=tmp_path / "gated",
        no_llm=True,
    )
    app.state.run_service = service
    engagement = Engagement(
        row_number=2,
        demanda="011616/2026",
        pasta="40-2026",
        razao_social="DENISE BARROS DE ALMEIDA",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin="https://example.test/",
        published_domain=None,
    )

    def finished_run(name: str, age: timedelta):
        directory = output_root / name
        previews = directory / "previews"
        previews.mkdir(parents=True)
        document = directory / f"{name}.docx"
        document.write_bytes(b"PK report")
        preview_paths = tuple(previews / f"page-{page}.png" for page in (1, 2))
        for preview in preview_paths:
            preview.write_bytes(_TINY_PNG)
        record = store.create(engagement, "retained-sheet")
        record = store.update(
            record.run_id,
            outcome="finished",
            report_status="draft",
            filename=document.name,
            document=str(document),
            previews=tuple(str(path) for path in preview_paths),
        )
        timestamp = datetime.now(UTC) - age
        (directory / "run.json").write_text(
            json.dumps(
                {
                    "pasta": engagement.pasta,
                    "media": [],
                    "boilerplate_links": [],
                    "input_origins": [],
                    "drop_folder": None,
                    "capture_folder": None,
                    "output_paths": [str(document)],
                    "blocks": [],
                    "pendencias": [],
                    "prose_grounding": [],
                }
            ),
            encoding="utf-8",
        )
        (directory / "pendencias.json").write_text(
            json.dumps({"status": "draft", "pendencias": []}),
            encoding="utf-8",
        )
        os.utime(directory, (timestamp.timestamp(), timestamp.timestamp()))
        return record, directory

    retained, retained_directory = finished_run(
        "retained", timedelta(days=6, hours=23)
    )
    latest = store.create(engagement, "retained-sheet")
    retained = store.update(
        latest.run_id,
        outcome="finished",
        report_status="draft",
        filename=retained.filename,
        document=retained.document,
        previews=retained.previews,
    )
    expired, expired_directory = finished_run(
        "expired", timedelta(days=7, minutes=1)
    )

    client = TestClient(app)
    response = client.get("/api/runs")

    assert response.status_code == 200
    assert response.json() == [
        {
            "run_id": retained.run_id,
            "razao_social": "DENISE BARROS DE ALMEIDA",
            "pasta": "40-2026",
            "demanda": "011616/2026",
            "generated_at": response.json()[0]["generated_at"],
            "page_count": 2,
            "status": "draft",
            "filename": "retained.docx",
            "review_url": f"/relatorios/{retained.run_id}",
            "download_url": f"/api/runs/{retained.run_id}/download",
        }
    ]
    assert retained_directory.exists()
    assert client.get(response.json()[0]["download_url"]).content == b"PK report"
    assert not expired_directory.exists()
    assert store.get(expired.run_id) is None
    service.shutdown()


def _finished_run_client(
    tmp_path: Path,
    *,
    gate_report: GateReport,
    pendencias: tuple[Pendencia, ...],
    media_pages: dict[str, int] | None = None,
    text_pages: dict[str, int] | None = None,
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
            preview_render=PreviewRender(
                pages=previews,
                media_pages=media_pages or {},
                text_pages=text_pages or {},
            ),
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
            GateResult(gate="token-residue"),
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
        tmp_path,
        gate_report=gate_report,
        pendencias=pendencias,
        media_pages={"cafefeed": 4},
        text_pages={"[PENDÊNCIA: NÃO FORNECIDO — cnpj_doc]": 2},
    )

    response = client.get(f"/api/runs/{run_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["page_count"] == 5
    assert body["filename"].endswith(".docx")
    assert body["download_url"] == f"/api/runs/{run_id}/download"
    assert [check["passed"] for check in body["checks"]] == [True, False, True]
    check_labels = [check["label"] for check in body["checks"]]
    assert "media-provenance" not in check_labels
    assert "block-integrity" not in check_labels
    assert "Nenhum campo do Master ficou por preencher" in check_labels
    assert len(set(check_labels)) == 3

    by_classification = {
        item["classification"]: item for item in body["pendencias"]
    }
    assert set(by_classification) == {"UNDECLARED", "TOOL_BLOCKED", "GATED"}
    assert by_classification["TOOL_BLOCKED"]["preview_page"] == 4
    assert by_classification["GATED"]["preview_page"] == 2
    assert by_classification["UNDECLARED"]["preview_page"] is None
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
    run = client.get(f"/api/runs/{run_id}").json()

    assert rendered, "the fake assembler rendered no preview pages"
    assert body["page_count"] == len(rendered)
    assert body["page_count"] != run["page_count"]
    served = [
        client.get(f"/api/runs/{run_id}/previews/{page}")
        for page in range(1, body["page_count"] + 1)
    ]
    assert [response.status_code for response in served] == [200] * len(rendered)
    assert (
        client.get(
            f"/api/runs/{run_id}/previews/{body['page_count'] + 1}"
        ).status_code
        == 404
    )
