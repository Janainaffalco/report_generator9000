from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from datetime import datetime
from zipfile import ZipFile

from PIL import Image

from report_generator9000.control_sheet import Engagement
from report_generator9000.generate import generate_report
from report_generator9000.logo import (
    CLIENT_LOGO_PART,
    LogoCapture,
    LogoFailure,
    capture_client_logo,
    resolve_declared_logo,
)
from report_generator9000.master import build_master
from tests.test_master_build import approved_source


FIXTURES = Path(__file__).parent / "fixtures" / "logo"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/redirect-off-host.html":
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://localhost:{self.server.server_port}/rendered-dark.html",
            )
            self.end_headers()
            return
        super().do_GET()


@contextmanager
def serve_logo_fixtures() -> Iterator[str]:
    handler = lambda *args, **kwargs: _QuietHandler(
        *args, directory=str(FIXTURES), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_json_ld_organization_logo_wins_over_unrelated_logo_images() -> None:
    html = """
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Organization",
        "logo": {"url": "/declared.svg", "width": 320, "height": 120}
      }
    </script>
    <img src="/Logo_Pao_Acucar.png" alt="Logo Pao de Acucar">
    <img src="/Logo_Oxxo.png" alt="Logo Oxxo">
    <a class="custom-logo-link"><img class="custom-logo" src="/wordpress.png"></a>
    """

    resolved = resolve_declared_logo(html, "https://cliente.example/")

    assert resolved is not None
    assert resolved.url == "https://cliente.example/declared.svg"
    assert resolved.declaration == "json-ld:Organization.logo"
    assert (resolved.intrinsic_width, resolved.intrinsic_height) == (320, 120)


def test_json_ld_logo_array_can_reference_an_image_object_by_id() -> None:
    resolved = resolve_declared_logo(
        """
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@graph": [
              {
                "@type": "Organization",
                "logo": [{"@id": "#client-mark"}]
              },
              {
                "@id": "#client-mark",
                "@type": "ImageObject",
                "contentUrl": "/declared.svg",
                "width": 640,
                "height": 240
              }
            ]
          }
        </script>
        <a class="custom-logo-link"><img src="/wordpress.png"></a>
        """,
        "https://cliente.example/",
    )

    assert resolved is not None
    assert resolved.url == "https://cliente.example/declared.svg"
    assert resolved.declaration == "json-ld:Organization.logo"
    assert (resolved.intrinsic_width, resolved.intrinsic_height) == (640, 240)


def test_custom_logo_is_used_when_json_ld_does_not_declare_one() -> None:
    resolved = resolve_declared_logo(
        """
        <header>
          <a class="custom-logo-link" href="/">
            <img class="custom-logo" src="/wp-content/uploads/client.png">
          </a>
        </header>
        """,
        "https://cliente.example/site/",
    )

    assert resolved is not None
    assert resolved.url == "https://cliente.example/wp-content/uploads/client.png"
    assert resolved.declaration == "wordpress:custom_logo"


def test_elementor_site_logo_is_the_last_declaration_source() -> None:
    resolved = resolve_declared_logo(
        """
        <div class="elementor-widget elementor-widget-theme-site-logo"
             data-widget_type="theme-site-logo.default">
          <img src="../client.webp">
        </div>
        """,
        "https://cliente.example/current/page/",
    )

    assert resolved is not None
    assert resolved.url == "https://cliente.example/current/client.webp"
    assert resolved.declaration == "elementor:site-logo"


def test_images_that_only_look_like_logos_are_never_resolved() -> None:
    resolved = resolve_declared_logo(
        """
        <header><img src="/client-logo.png" alt="Logo do cliente"></header>
        <img src="/partner-logo.png" width="500" height="200">
        """,
        "https://cliente.example/",
    )

    assert resolved is None


def test_empty_custom_logo_container_does_not_claim_a_later_image() -> None:
    resolved = resolve_declared_logo(
        """
        <a class="custom-logo-link" href="/"><img alt="No source"></a>
        <img src="/partner-logo.png" alt="Partner logo">
        """,
        "https://cliente.example/",
    )

    assert resolved is None


def test_rendered_logo_on_dark_header_keeps_its_contrast(
    tmp_path: Path,
) -> None:
    with serve_logo_fixtures() as origin:
        result = capture_client_logo(
            origin + "rendered-dark.html",
            tmp_path,
            slot_pixel_size=(600, 300),
        )

    assert isinstance(result, LogoCapture)
    assert result.declared.declaration == "json-ld:Organization.logo"
    with Image.open(result.path) as image:
        assert image.format == "PNG"
        assert image.size == (600, 300)
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000)
    assert colors is not None
    assert any(
        count > 100 and blue > 80 and red < 40
        for count, (red, _green, blue) in colors
    )
    assert any(
        count > 100 and min(red, green, blue) > 230
        for count, (red, green, blue) in colors
    )


def test_declared_svg_without_rendered_match_uses_raster_fallback(
    tmp_path: Path,
) -> None:
    with serve_logo_fixtures() as origin:
        result = capture_client_logo(
            origin + "fallback.html",
            tmp_path,
            slot_pixel_size=(600, 300),
        )

    assert isinstance(result, LogoCapture)
    assert result.acquisition == "download-rasterized"
    with Image.open(result.path) as image:
        assert image.format == "PNG"
        assert image.size == (600, 300)
        assert len(image.convert("RGB").getcolors(maxcolors=1_000_000) or ()) > 1


def test_no_logo_declaration_returns_undeclared_pendencia(
    tmp_path: Path,
) -> None:
    with serve_logo_fixtures() as origin:
        result = capture_client_logo(origin + "undeclared.html", tmp_path)

    assert isinstance(result, LogoFailure)
    assert result.pendencia.slot == "logo_cliente"
    assert result.pendencia.classification == "UNDECLARED"
    assert result.pendencia.required_action == "Anexar o logo do cliente"
    assert not list(tmp_path.glob("*.png"))


def test_continuous_network_activity_does_not_hide_undeclared_result(
    tmp_path: Path,
) -> None:
    with serve_logo_fixtures() as origin:
        result = capture_client_logo(
            origin + "undeclared-active.html", tmp_path
        )

    assert isinstance(result, LogoFailure)
    assert result.classification == "UNDECLARED"


def test_redirect_off_capture_origin_host_is_tool_blocked(
    tmp_path: Path,
) -> None:
    with serve_logo_fixtures() as origin:
        result = capture_client_logo(
            origin + "redirect-off-host.html", tmp_path
        )

    assert isinstance(result, LogoFailure)
    assert result.classification == "TOOL_BLOCKED"
    assert "host" in result.reason


def _engagement() -> Engagement:
    return Engagement(
        row_number=2,
        demanda="011616/2026",
        pasta="40-2026",
        razao_social="CLIENTE",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin="https://capture.example/",
        published_domain=None,
    )


def test_declared_logo_fills_the_master_slot_with_capture_provenance(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "master"
    ).master
    content = (FIXTURES / "client-logo.svg").read_bytes()
    capture_folder = tmp_path / "40-2026_CLIENTE" / "capturas"
    with serve_logo_fixtures() as origin:
        captured = capture_client_logo(
            origin + "fallback.html", capture_folder
        )
    assert isinstance(captured, LogoCapture)

    generated = generate_report(
        master,
        tmp_path / "reports",
        _engagement(),
        tmp_path / "gated",
        pages=(),
        no_llm=True,
        client_logo=captured,
        capture_folder=capture_folder,
    )

    with ZipFile(generated.document) as archive:
        assert archive.read(CLIENT_LOGO_PART) == captured.path.read_bytes()
        assert archive.read(CLIENT_LOGO_PART) != content
    artifact = next(
        item
        for item in generated.context.media
        if item.label == "logo_cliente"
    )
    assert artifact.origin == "capture"
    assert artifact.digest == captured.digest
    assert not any(
        item.slot == "logo_cliente"
        for item in generated.context.pendencias
    )


def test_missing_logo_fills_undeclared_placeholder_and_pendencia(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "master"
    ).master

    generated = generate_report(
        master,
        tmp_path / "reports",
        _engagement(),
        tmp_path / "gated",
        pages=(),
        no_llm=True,
    )

    pendencia = next(
        item
        for item in generated.context.pendencias
        if item.slot == "logo_cliente"
    )
    placeholder = next(
        item
        for item in generated.context.media
        if item.label == "logo_cliente"
    )
    assert pendencia.classification == "UNDECLARED"
    assert pendencia.required_action == "Anexar o logo do cliente"
    assert placeholder.origin == "placeholder"
    assert pendencia.evidence == placeholder.digest
