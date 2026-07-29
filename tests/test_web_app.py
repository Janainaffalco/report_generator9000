from pathlib import Path

from fastapi.testclient import TestClient

from report_generator9000.web import DEFAULT_STATIC_DIR, create_app


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
