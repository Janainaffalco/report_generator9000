"""The public WordPress login screen is captured by GET only, never logged into."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from zipfile import ZipFile

import pytest
from PIL import Image

from report_generator9000.artifact_paths import engagement_artifact_key
from report_generator9000.gated_inputs import gated_drop_folder
from report_generator9000.generate import generate_report
from report_generator9000.tema import supported_contract
from report_generator9000.wordpress_login import (
    LOGIN_FILENAME,
    LoginCapture,
    LoginCaptureFailure,
    capture_wordpress_login,
    wordpress_login_url,
)
from tests.test_loja_gated_inputs import (
    _identity,
    _loja_engagement,
    _write_values,
)

LOGIN_PART = "word/media/image13.png"
_LOGIN_PAGE = b"""<!doctype html>
<html><body style="background:#f0f0f1">
<form id="loginform" method="post" action="/wp-login.php">
  <label>Nome de usuario <input name="log"></label>
  <label>Senha <input name="pwd" type="password"></label>
  <button type="submit">Entrar</button>
</form>
<script>fetch('/wp-admin/admin-ajax.php', {method: 'POST', body: 'x=1'})</script>
</body></html>"""


class _WordPressHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def _record(self) -> None:
        self.server.requests.append((self.command, self.path))  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        self._record()
        mode = self.server.mode  # type: ignore[attr-defined]
        port = self.server.server_port
        if self.path == "/wp-admin/":
            location = (
                f"http://localhost:{port}/wp-login.php"
                if mode == "off-host"
                else "/wp-login.php?redirect_to=%2Fwp-admin%2F&reauth=1"
            )
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()
            return
        if self.path.startswith("/wp-login.php"):
            self.send_response(403 if mode == "forbidden" else 200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_LOGIN_PAGE)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        self._record()
        self.send_response(200)
        self.end_headers()


@contextmanager
def _serve_wordpress(mode: str = "ok") -> Iterator[tuple[str, list]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WordPressHandler)
    server.mode = mode  # type: ignore[attr-defined]
    server.requests = []  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", server.requests  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_wp_admin_url_is_built_on_the_capture_origin_host() -> None:
    assert (
        wordpress_login_url("https://Loja.Example/produtos/?x=1#top")
        == "https://loja.example/wp-admin/"
    )
    assert (
        wordpress_login_url("http://loja.example:8080")
        == "http://loja.example:8080/wp-admin/"
    )


@pytest.mark.parametrize(
    "origin",
    [
        "https://admin:secret@loja.example/",
        "https://admin@loja.example/",
        "ftp://loja.example/",
        "loja.example",
    ],
)
def test_an_unsafe_capture_origin_is_refused_without_a_browser(
    origin: str, tmp_path: Path
) -> None:
    with pytest.raises(ValueError):
        wordpress_login_url(origin)

    result = capture_wordpress_login(origin, tmp_path)

    assert isinstance(result, LoginCaptureFailure)
    assert not (tmp_path / LOGIN_FILENAME).exists()


def test_a_same_host_redirect_to_wp_login_is_captured_by_get_only(
    tmp_path: Path,
) -> None:
    with _serve_wordpress() as (origin, requests):
        result = capture_wordpress_login(origin, tmp_path)

    assert isinstance(result, LoginCapture), result
    assert result.path == (tmp_path / LOGIN_FILENAME).resolve()
    assert result.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert result.digest == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert "/wp-login.php" in result.final_url
    assert result.artifact.origin == "capture"
    assert result.artifact.label == "login"
    # Nothing but reads reached the site: the page's own POST was aborted and
    # the login form was never submitted.
    assert requests[0] == ("GET", "/wp-admin/")
    assert {method for method, _path in requests} == {"GET"}


def test_a_redirect_to_another_host_is_refused(tmp_path: Path) -> None:
    with _serve_wordpress("off-host") as (origin, _requests):
        result = capture_wordpress_login(origin, tmp_path)

    assert isinstance(result, LoginCaptureFailure)
    assert "host" in result.reason
    assert not (tmp_path / LOGIN_FILENAME).exists()


def test_an_http_error_on_the_final_page_is_refused(tmp_path: Path) -> None:
    with _serve_wordpress("forbidden") as (origin, _requests):
        result = capture_wordpress_login(origin, tmp_path)

    assert isinstance(result, LoginCaptureFailure)
    assert "403" in result.reason
    assert not (tmp_path / LOGIN_FILENAME).exists()


def _capture_folder(tmp_path: Path) -> Path:
    return tmp_path / engagement_artifact_key(_loja_engagement()) / "capturas"


def _captured_login(folder: Path) -> LoginCapture:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOGIN_FILENAME
    Image.new("RGB", (1280, 800), "#f0f0f1").save(path)
    return LoginCapture(
        path=path.resolve(),
        digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        final_url="https://loja.example/wp-login.php",
    )


def _generate(tmp_path: Path, gated: Path, captured: LoginCapture):
    engagement = _loja_engagement()
    master = supported_contract(engagement.tema).master
    assert master is not None
    return generate_report(
        master,
        tmp_path / "outputs",
        engagement,
        gated,
        pages=(),
        no_llm=True,
        capture_folder=captured.path.parent,
        captured_login=captured,
    )


def test_a_supplied_login_png_wins_over_the_automatic_capture(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    gated = tmp_path / "gated"
    folder = gated_drop_folder(gated, engagement)
    _write_values(folder, _identity(engagement))
    Image.new("RGB", (640, 360), "red").save(folder / "login.png")
    captured = _captured_login(_capture_folder(tmp_path))

    report = _generate(tmp_path, gated, captured)

    with ZipFile(report.document) as archive:
        embedded = archive.read(LOGIN_PART)
    assert embedded == (folder / "login.png").read_bytes()
    assert embedded != captured.path.read_bytes()
    login = [item for item in report.context.media if item.label == "login"]
    assert [item.origin for item in login] == ["gated"]
    assert not any(item.slot == "login" for item in report.context.pendencias)


def test_the_automatic_capture_fills_the_slot_when_no_login_png_is_supplied(
    tmp_path: Path,
) -> None:
    captured = _captured_login(_capture_folder(tmp_path))

    report = _generate(tmp_path, tmp_path / "gated", captured)

    with ZipFile(report.document) as archive:
        assert archive.read(LOGIN_PART) == captured.path.read_bytes()
    login = [item for item in report.context.media if item.label == "login"]
    assert login == [captured.artifact]
    assert login[0].source == str(captured.path)
    assert not any(item.slot == "login" for item in report.context.pendencias)
    # Every other administrative Slot keeps its GATED Pendência.
    assert any(item.slot == "painel" for item in report.context.pendencias)


def test_without_any_login_evidence_the_gated_pendencia_remains(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    master = supported_contract(engagement.tema).master
    assert master is not None

    report = generate_report(
        master,
        tmp_path / "outputs",
        engagement,
        tmp_path / "gated",
        pages=(),
        no_llm=True,
    )

    pendencia = next(
        item for item in report.context.pendencias if item.slot == "login"
    )
    assert pendencia.classification == "GATED"
    assert pendencia.name == "PÁGINA DE LOGIN"
