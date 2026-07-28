from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from PIL import Image

from report_generator9000.capture import (
    CaptureConfig,
    capture_site,
    fitted_emu_dimensions,
)
from report_generator9000.lista_paginas import (
    AREA_LEGAL,
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    Pagina,
)
from tests.test_lista_paginas import serve_fixture_site


def _pagina(
    origin: str,
    path: str = "",
    *,
    tipo: str = PAGINA_PRINCIPAL,
    rotulo: str = "Home",
    titulo: str = "PÁGINA HOME",
) -> Pagina:
    return Pagina(
        tipo=tipo,
        rotulo=rotulo,
        url=f"{origin}{path}",
        titulo_bloco=titulo,
    )


def _capture_config(**changes: int) -> CaptureConfig:
    values = {
        "viewport_width": 800,
        "viewport_height": 500,
        "device_scale_factor": 2,
        "navigation_timeout_ms": 10_000,
        "network_idle_timeout_ms": 2_000,
        "lazy_settle_ms": 150,
        "embedding_max_width": 600,
        "minimum_color_count": 64,
    }
    values.update(changes)
    return CaptureConfig(**values)


class _RedirectHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/external":
            content = b"<html><body>wrong host</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        port = self.server.server_port
        self.send_response(302)
        self.send_header("Location", f"http://localhost:{port}/external")
        self.end_headers()


@contextmanager
def _serve_cross_host_redirect() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_browser_renders_lazy_content_declines_and_downscales(
    tmp_path: Path,
) -> None:
    with serve_fixture_site() as origin:
        result = capture_site(
            (_pagina(origin),),
            tmp_path / "40-2026_CLIENTE" / "capturas",
            config=_capture_config(),
        )

    assert result.failures == ()
    assert result.pendencias == ()
    capture = result.captures[0]
    assert capture.raw_path.parent == result.folder
    assert capture.embedding_path.parent == result.folder / "embutir"
    assert capture.raw_width == 1600
    assert capture.embedding_width == 600
    assert capture.embedding_height == round(
        capture.raw_height * 600 / capture.raw_width
    )
    assert capture.embedding_height / capture.embedding_width == pytest.approx(
        capture.raw_height / capture.raw_width,
        abs=0.002,
    )
    assert capture.raw_digest != capture.embedding_digest
    assert capture.artifact.origin == "capture"
    assert capture.artifact.source == str(capture.embedding_path.resolve())

    with Image.open(capture.raw_path) as image:
        colors = set(
            image.convert("RGB").resize((200, 200)).get_flattened_data()
        )
    assert any(g > 120 and r < 120 for r, g, _b in colors)
    assert not any(r > 245 and 180 < g < 235 and b < 80 for r, g, b in colors)


def test_undismissable_banner_is_visible_and_flagged(tmp_path: Path) -> None:
    with serve_fixture_site() as origin:
        result = capture_site(
            (_pagina(origin, "banner.html", titulo="SEÇÃO BANNER"),),
            tmp_path / "40-2026_CLIENTE" / "capturas",
            config=_capture_config(),
        )

    assert result.failures == ()
    capture = result.captures[0]
    assert capture.consent_warning is True
    assert len(result.pendencias) == 1
    assert result.pendencias[0].classification == "TOOL_BLOCKED"
    assert result.pendencias[0].evidence == capture.embedding_digest
    with Image.open(capture.raw_path) as image:
        colors = set(
            image.convert("RGB").resize((200, 200)).get_flattened_data()
        )
    assert any(r > 170 and g < 90 and b < 100 for r, g, b in colors)


def test_blank_capture_is_kept_raw_but_never_offered_for_embedding(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "40-2026_CLIENTE" / "capturas"
    stale_embedding = folder / "embutir" / "01-secao-vazia.png"
    stale_removed_page = folder / "09-secao-antiga.png"
    stale_embedding.parent.mkdir(parents=True)
    stale_embedding.write_bytes(b"capture from an earlier run")
    stale_removed_page.write_bytes(b"capture from an earlier Lista")
    with serve_fixture_site() as origin:
        result = capture_site(
            (_pagina(origin, "blank.html", titulo="SEÇÃO VAZIA"),),
            folder,
            config=_capture_config(minimum_color_count=2),
        )

    assert result.captures == ()
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.raw_path is not None
    assert failure.raw_path.exists()
    assert failure.raw_path.parent == result.folder
    assert not stale_embedding.exists()
    assert not stale_removed_page.exists()
    assert result.pendencias[0].classification == "TOOL_BLOCKED"
    assert "branco" in result.pendencias[0].reason


def test_transversal_capture_clips_the_real_landmark(tmp_path: Path) -> None:
    with serve_fixture_site() as origin:
        header = _pagina(
            origin,
            tipo=ELEMENTO_TRANSVERSAL,
            rotulo="Cabeçalho",
            titulo="CABEÇALHO",
        )
        footer = _pagina(
            origin,
            tipo=ELEMENTO_TRANSVERSAL,
            rotulo="Rodapé",
            titulo="RODAPÉ",
        )
        result = capture_site(
            (header, footer),
            tmp_path / "40-2026_CLIENTE" / "capturas",
            config=_capture_config(minimum_color_count=8),
        )

    assert result.failures == ()
    assert len(result.captures) == 2
    assert all(capture.raw_width == 1600 for capture in result.captures)
    assert all(capture.raw_height < 400 for capture in result.captures)


def test_word_slot_height_is_derived_from_capture_ratio() -> None:
    assert fitted_emu_dimensions(5_000_000, 1600, 900) == (
        5_000_000,
        2_812_500,
    )


def test_capture_url_cannot_carry_credentials(tmp_path: Path) -> None:
    page = Pagina(
        tipo=AREA_LEGAL,
        rotulo="Privacidade",
        url="https://usuario:segredo@example.test/privacidade",
        titulo_bloco="PRIVACIDADE",
    )

    result = capture_site(
        (page,),
        tmp_path / "40-2026_CLIENTE" / "capturas",
        config=_capture_config(),
    )

    assert result.captures == ()
    assert len(result.failures) == 1
    assert "credentials" in result.failures[0].reason
    assert result.pendencias[0].classification == "TOOL_BLOCKED"


def test_cross_host_redirect_is_never_captured(tmp_path: Path) -> None:
    with _serve_cross_host_redirect() as origin:
        result = capture_site(
            (_pagina(origin),),
            tmp_path / "40-2026_CLIENTE" / "capturas",
            config=_capture_config(),
        )

    assert result.captures == ()
    assert len(result.failures) == 1
    assert "left the declared page host" in result.failures[0].reason
    assert result.failures[0].raw_path is None
