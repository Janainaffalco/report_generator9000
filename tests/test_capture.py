from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from zipfile import ZipFile
from xml.etree import ElementTree

import pytest
from PIL import Image, ImageDraw

from report_generator9000.capture import (
    PARTIAL_CAPTURE_BADGE_TEXT,
    CaptureConfig,
    build_embedding_derivative,
    capture_config_from_master,
    capture_site,
    extract_site_text,
    fitted_emu_dimensions,
)
from report_generator9000.lista_paginas import (
    AREA_LEGAL,
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    Pagina,
)
from report_generator9000.master import build_master
from tests.test_lista_paginas import serve_fixture_site
from tests.test_master_build import approved_source


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
    assert capture.cropped is False
    assert capture.cropped_from_width is None
    assert capture.cropped_from_height is None
    assert capture.artifact.origin == "capture"
    assert capture.artifact.source == str(capture.embedding_path.resolve())

    with Image.open(capture.raw_path) as image:
        colors = set(
            image.convert("RGB").resize((200, 200)).get_flattened_data()
        )
    assert any(g > 120 and r < 120 for r, g, _b in colors)
    assert not any(r > 245 and 180 < g < 235 and b < 80 for r, g, b in colors)


class _EdgeCacheHandler(BaseHTTPRequestHandler):
    """A host behind a CDN, announcing which layer answered."""

    received: list[dict[str, str]] = []

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        type(self).received.append(dict(self.headers))
        content = (
            "<html><body style='background:#1b7f3b'>"
            "<h1 style='color:#f2c14e'>CLINICA EXEMPLO</h1>"
            "<p style='color:#3b5bdb'>Atendimento especializado.</p>"
            "</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("x-hcdn-cache-status", "HIT")
        self.end_headers()
        self.wfile.write(content)


@contextmanager
def _serve_edge_cached_site() -> Iterator[str]:
    _EdgeCacheHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EdgeCacheHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_capture_asks_intermediaries_to_revalidate_and_records_who_answered(
    tmp_path: Path,
    recording_sink,
) -> None:
    """A Capture must depict the site now, not a maintenance page from before.

    Nothing here caches -- every Run launches a fresh browser profile -- so a
    stale Capture can only come from an intermediary. We ask it to revalidate,
    and we record what it says it served, so the next stale Capture is
    evidence rather than a guess.
    """
    with _serve_edge_cached_site() as origin:
        result = capture_site(
            (_pagina(origin),),
            tmp_path / "40-2026_CLIENTE" / "capturas",
            config=_capture_config(minimum_color_count=2),
        )

    assert result.failures == ()
    document_request = _EdgeCacheHandler.received[0]
    assert document_request["Cache-Control"] == "no-cache"
    assert document_request["Pragma"] == "no-cache"

    responses = [
        event
        for event in recording_sink.events
        if event.name == "capture_page_response"
    ]
    assert len(responses) == 1
    assert responses[0].fields["url"] == origin
    assert responses[0].fields["status"] == 200
    assert responses[0].fields["x_hcdn_cache_status"] == "HIT"


class _RestlessHandler(BaseHTTPRequestHandler):
    """A site that never goes network-idle, the way Wix and Hostinger do not."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/beacon":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        content = (
            "<html><body>"
            "<h1>CLINICA EXEMPLO</h1>"
            "<p>Atendimento especializado em toda a regiao.</p>"
            "<script>setInterval(() => fetch('/beacon'), 100)</script>"
            "</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


@contextmanager
def _serve_restless_site() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RestlessHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_site_that_never_goes_network_idle_is_still_captured(
    tmp_path: Path,
) -> None:
    """Network quiet is a settle hint, not a precondition for a usable page.

    Site builders keep beacons and chat sockets open indefinitely, so waiting
    for `networkidle` before capturing throws away pages that finished
    rendering seconds earlier.
    """
    with _serve_restless_site() as origin:
        result = capture_site(
            (_pagina(origin, titulo="SEÇÃO HOME"),),
            tmp_path / "40-2026_CLIENTE" / "capturas",
            config=_capture_config(),
        )

    assert result.failures == ()
    assert len(result.captures) == 1


def test_site_that_never_goes_network_idle_still_yields_prose_text(
    tmp_path: Path,
) -> None:
    with _serve_restless_site() as origin:
        extracted = extract_site_text(
            (_pagina(origin, titulo="SEÇÃO HOME"),),
            config=_capture_config(),
        )

    assert len(extracted) == 1
    assert "CLINICA EXEMPLO" in extracted[0].text


def test_one_unreachable_page_does_not_lose_the_other_pages_prose() -> None:
    """A single bad page costs its own text, never the whole extraction."""
    with serve_fixture_site() as origin:
        extracted = extract_site_text(
            (
                _pagina("http://127.0.0.1:9/", titulo="SEÇÃO MORTA"),
                _pagina(origin, titulo="SEÇÃO HOME"),
            ),
            config=_capture_config(),
        )

    assert len(extracted) == 1
    assert extracted[0].capture_origin.startswith(origin)


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


def test_embedding_derivative_crops_only_the_bottom_and_preserves_raw(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.png"
    embedding_path = tmp_path / "embedding.png"
    raw = Image.new("RGB", (400, 1200), "red")
    draw = ImageDraw.Draw(raw)
    draw.rectangle((0, 400, 399, 799), fill="green")
    draw.rectangle((0, 800, 399, 1199), fill="blue")
    raw.save(raw_path)
    raw_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()

    derivative = build_embedding_derivative(
        raw_path,
        embedding_path,
        max_width=200,
        slot_width_emu=4_000_000,
        max_height_emu=4_000_000,
    )

    assert derivative.cropped is True
    assert derivative.cropped_from_width == 400
    assert derivative.cropped_from_height == 1200
    assert derivative.width == 200
    assert derivative.height == 200
    assert Image.open(raw_path).size == (400, 1200)
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == raw_digest
    with Image.open(embedding_path) as embedded:
        assert embedded.getpixel((190, 10)) == (255, 0, 0)
        badge_region = embedded.crop((0, 140, 190, 200))
        colors = set(badge_region.get_flattened_data())
    assert any(max(color) < 80 for color in colors)
    assert any(min(color) > 220 for color in colors)
    assert PARTIAL_CAPTURE_BADGE_TEXT == "captura parcial da página"


def test_short_embedding_keeps_natural_ratio_without_badge(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.png"
    embedding_path = tmp_path / "embedding.png"
    Image.new("RGB", (400, 100), "white").save(raw_path)

    derivative = build_embedding_derivative(
        raw_path,
        embedding_path,
        max_width=200,
        slot_width_emu=4_000_000,
        max_height_emu=4_000_000,
    )

    assert derivative.cropped is False
    assert derivative.cropped_from_width is None
    assert derivative.cropped_from_height is None
    assert (derivative.width, derivative.height) == (200, 50)
    with Image.open(embedding_path) as embedded:
        assert set(embedded.get_flattened_data()) == {(255, 255, 255)}


@pytest.mark.parametrize("raw_height", [10, 100, 400, 2_000])
def test_embedding_height_never_exceeds_configured_word_cap(
    tmp_path: Path,
    raw_height: int,
) -> None:
    raw_path = tmp_path / f"raw-{raw_height}.png"
    embedding_path = tmp_path / f"embedding-{raw_height}.png"
    Image.new("RGB", (200, raw_height), "purple").save(raw_path)

    derivative = build_embedding_derivative(
        raw_path,
        embedding_path,
        max_width=100,
        slot_width_emu=5_000_000,
        max_height_emu=4_000_000,
    )

    _width, embedded_height_emu = fitted_emu_dimensions(
        5_000_000,
        derivative.width,
        derivative.height,
    )
    assert embedded_height_emu <= 4_000_000


def test_capture_height_cap_comes_from_master_page_geometry(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master

    config = capture_config_from_master(
        master,
        CaptureConfig(embedding_max_width=600),
    )

    assert config.embedding_slot_width_emu == 5_400_000
    # The raw geometric reservation (12876 twips of heading) still leaves
    # more than the 22.5 cm ceiling, so the ceiling -- not the geometry --
    # is what binds here.
    assert config.embedding_max_height_emu == 8_100_000

    with ZipFile(master) as archive:
        parts = {
            item.filename: archive.read(item.filename)
            for item in archive.infolist()
        }
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b'w:top="1701"',
        b'w:top="2500"',
    )
    changed_master = tmp_path / "changed-margins.docx"
    with ZipFile(changed_master, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)

    changed = capture_config_from_master(changed_master)
    assert changed.embedding_max_height_emu == (12876 - 799) * 635

    with ZipFile(master) as archive:
        styled_parts = {
            item.filename: archive.read(item.filename)
            for item in archive.infolist()
        }
    word_namespace = (
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    )
    w = f"{{{word_namespace}}}"
    document = ElementTree.fromstring(styled_parts["word/document.xml"])
    heading = next(
        paragraph
        for paragraph in document.iter(f"{w}p")
        if paragraph.find(
            f"{w}bookmarkStart[@{w}name='MASTER_BLOCK_STAMP']"
        )
        is not None
    )
    properties = heading.find(f"{w}pPr")
    assert properties is not None
    properties.insert(
        0,
        ElementTree.Element(f"{w}pStyle", {f"{w}val": "Normal"}),
    )
    styles = ElementTree.fromstring(styled_parts["word/styles.xml"])
    normal = ElementTree.SubElement(
        styles,
        f"{w}style",
        {f"{w}type": "paragraph", f"{w}styleId": "Normal"},
    )
    run_properties = ElementTree.SubElement(normal, f"{w}rPr")
    ElementTree.SubElement(
        run_properties,
        f"{w}sz",
        {f"{w}val": "40"},
    )
    styled_parts["word/document.xml"] = ElementTree.tostring(document)
    styled_parts["word/styles.xml"] = ElementTree.tostring(styles)
    styled_master = tmp_path / "styled-heading.docx"
    with ZipFile(styled_master, "w") as archive:
        for name, content in styled_parts.items():
            archive.writestr(name, content)

    styled = capture_config_from_master(styled_master)
    assert styled.embedding_max_height_emu == (12876 - 160) * 635

    child = ElementTree.SubElement(
        styles,
        f"{w}style",
        {f"{w}type": "paragraph", f"{w}styleId": "CaptureHeading"},
    )
    ElementTree.SubElement(
        child,
        f"{w}basedOn",
        {f"{w}val": "Normal"},
    )
    child_run_properties = ElementTree.SubElement(child, f"{w}rPr")
    ElementTree.SubElement(
        child_run_properties,
        f"{w}sz",
        {f"{w}val": "24"},
    )
    properties.find(f"{w}pStyle").set(f"{w}val", "CaptureHeading")
    styled_parts["word/document.xml"] = ElementTree.tostring(document)
    styled_parts["word/styles.xml"] = ElementTree.tostring(styles)
    inherited_master = tmp_path / "inherited-heading-style.docx"
    with ZipFile(inherited_master, "w") as archive:
        for name, content in styled_parts.items():
            archive.writestr(name, content)

    inherited = capture_config_from_master(inherited_master)
    # Same geometry as the base case above -- the ceiling binds again.
    assert inherited.embedding_max_height_emu == 8_100_000


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
