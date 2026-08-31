from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from report_generator9000.sheet_store import SheetStore
from report_generator9000.web import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"
PASSWORD = "shared-test-password"
ROOT = Path(__file__).resolve().parents[1]


def _upload(client: TestClient):
    with FIXTURE.open("rb") as handle:
        return client.post(
            "/api/control-sheet",
            files={
                "file": (
                    "planilha.xlsx",
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )


def test_unauthenticated_requests_to_planilha_and_run_endpoints_are_rejected(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )

    assert client.get("/api/control-sheets").status_code == 401
    assert _upload(client).status_code == 401
    assert client.get("/api/runs").status_code == 401
    assert client.post(
        "/api/runs", json={"sheet_id": "x", "row_number": 2}
    ).status_code == 401
    assert client.post(
        "/api/batches", json={"sheet_id": "x", "row_numbers": [2]}
    ).status_code == 401
    assert client.get("/api/runs/missing").status_code == 401
    assert client.get("/api/runs/missing/download").status_code == 401
    assert client.get("/api/runs/missing/report").status_code == 401
    assert client.get("/api/runs/missing/previews/1").status_code == 401
    assert client.get("/api/batches/missing").status_code == 401
    assert client.post("/api/runs/missing/attachments").status_code == 401
    assert client.get("/api/session").status_code == 401


def test_correct_password_issues_a_session_that_restores_current_behaviour(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )

    login = client.post("/api/login", json={"password": PASSWORD})

    assert login.status_code == 204
    listing = client.get("/api/control-sheets")
    assert listing.status_code == 200
    assert listing.json() == []
    uploaded = _upload(client)
    assert uploaded.status_code == 200
    assert uploaded.json()["engagements"]
    assert client.get("/api/session").status_code == 200


def test_wrong_password_is_rejected_and_does_not_issue_a_session(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )

    login = client.post("/api/login", json={"password": "not-the-password"})

    assert login.status_code == 401
    assert client.get("/api/control-sheets").status_code == 401
    assert client.get("/api/session").status_code == 401


def test_health_and_robots_remain_reachable_without_a_session(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )

    health = client.get("/api/health")
    robots = client.get("/robots.txt")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert robots.status_code == 200
    assert "Disallow: /" in robots.text


def test_crawler_headers_still_appear_on_login_and_data_responses(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )

    login = client.post("/api/login", json={"password": PASSWORD})
    listing = client.get("/api/control-sheets")
    denied = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    ).get("/api/control-sheets")

    for response in (login, listing, denied):
        assert "noindex" in response.headers["x-robots-tag"]
        assert "nofollow" in response.headers["x-robots-tag"]
        assert response.headers["referrer-policy"] == "no-referrer"


def test_missing_shared_password_fails_closed(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password="",
        )
    )

    login = client.post("/api/login", json={"password": "anything"})
    listing = client.get("/api/control-sheets")

    assert login.status_code == 401
    assert listing.status_code == 401


def test_login_does_not_write_the_password_to_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )
    distinctive = "s3cret-PASSWORD-must-not-appear"

    with caplog.at_level(logging.DEBUG):
        client.post("/api/login", json={"password": distinctive})

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert distinctive not in combined


def test_logout_ends_the_session(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            static_dir=tmp_path / "missing-web",
            sheet_store=SheetStore(tmp_path / "sheets"),
            app_password=PASSWORD,
        )
    )
    client.post("/api/login", json={"password": PASSWORD})

    logout = client.post("/api/logout")

    assert logout.status_code == 204
    assert client.get("/api/control-sheets").status_code == 401
    assert client.get("/api/session").status_code == 401


def test_deploy_docs_name_the_runtime_password_secret() -> None:
    deploy = (ROOT / "deploy.md").read_text(encoding="utf-8")

    assert "REPORT_APP_PASSWORD=" in deploy
    assert "GEMINI_API_KEY" in deploy
