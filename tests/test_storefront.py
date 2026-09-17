from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from report_generator9000.assembly import assemble_output_package
from report_generator9000.capture import CaptureConfig, capture_site
from report_generator9000.control_sheet import Engagement
from report_generator9000.lista_paginas import (
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    PRODUTO_PUBLICADO,
    VISAO_MOBILE,
    VITRINE,
    Pagina,
)
from report_generator9000.storefront import (
    StorefrontDiscoveryConfig,
    discover_storefront_pages,
)
from report_generator9000.tema import LOJA_VIRTUAL_TEMA, supported_contract
from tests.test_assembly import _FakePreviewRenderer


class _StorefrontHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str]] = []
    api_enabled = True

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        type(self).requests.append(("POST", self.path))
        self.send_error(405)

    def do_GET(self) -> None:
        type(self).requests.append(("GET", self.path))
        parsed = urlsplit(self.path)
        if parsed.path == "/wp-json/wc/store/v1/products":
            if not type(self).api_enabled:
                self.send_error(404)
                return
            host = self.headers["Host"]
            payload = json.dumps(
                [
                    {
                        "name": "Produto externo",
                        "permalink": "https://outside.example/produto/fora/",
                        "status": "publish",
                    },
                    {
                        "name": "Rascunho",
                        "permalink": f"http://{host}/produto/rascunho/",
                        "status": "draft",
                    },
                    {
                        "name": "Café Especial",
                        "permalink": f"http://{host}/produto/cafe/",
                        "status": "publish",
                    },
                ]
            ).encode()
            self._send(payload, "application/json")
            return
        pages = {
            "/": """
                <h1>Empório</h1><nav><a href='/sobre/'>Sobre</a></nav>
                <main>
                  <a class='shop-card' href='/loja/'>Conheça a loja</a>
                  <a class='product-card' href='/produto/cafe/'>Café Especial</a>
                  <a href='/categoria-produto/graos/'>Grãos</a>
                  <a class='product-filter' href='/loja/?filter_torra=media'>Torra média</a>
                  <a href='/carrinho/?add-to-cart=10'>Comprar agora</a>
                  <a href='https://outside.example/produto/fora/'>Externo</a>
                  <script>fetch('/checkout/', {method: 'POST'})</script>
                </main>
                <footer>Contato e informações da empresa</footer>
            """,
            "/loja/": "<h1>Loja</h1><p>Produtos disponíveis para compra pública.</p>",
            "/produto/cafe/": (
                "<h1>Café Especial</h1>"
                "<p>Produto publicado com descrição completa.</p>"
            ),
            "/categoria-produto/graos/": (
                "<h1>Grãos</h1><p>Categoria pública de produtos.</p>"
            ),
            "/sobre/": "<h1>Sobre</h1><p>História completa do empório.</p>",
        }
        if parsed.path == "/loja/" and parsed.query:
            body = "<h1>Torra média</h1><p>Filtro público aplicado à vitrine.</p>"
        else:
            body = pages.get(parsed.path)
        if body is None or parsed.path == "/produto/rascunho/":
            self.send_error(404)
            return
        markup = (
            "<html><head><style>:root{--brand-primary:#7a2f1f;"
            "--brand-secondary:#d68c45}body{background:#f7e7ce;color:#23160f}"
            "main{min-height:700px}a{display:block;padding:12px}</style></head>"
            f"<body><header>Empório</header>{body}</body></html>"
        ).encode()
        self._send(markup, "text/html; charset=utf-8")

    def _send(self, content: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


@contextmanager
def _serve_storefront(
    *, api_enabled: bool = True
) -> Iterator[tuple[str, type[_StorefrontHandler]]]:
    class Handler(_StorefrontHandler):
        requests: list[tuple[str, str]] = []

    Handler.api_enabled = api_enabled
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _base_pages(origin: str) -> tuple[Pagina, ...]:
    return (
        Pagina(PAGINA_PRINCIPAL, "Home", origin, "PÁGINA HOME"),
        Pagina(ELEMENTO_TRANSVERSAL, "Cabeçalho", origin, "CABEÇALHO"),
        Pagina(ELEMENTO_TRANSVERSAL, "Rodapé", origin, "RODAPÉ"),
    )


def test_discovery_confirms_a_public_storefront_without_using_the_menu() -> None:
    with _serve_storefront() as (origin, handler):
        pages = discover_storefront_pages(origin, _base_pages(origin))

    headings = [page.titulo_bloco for page in pages]
    assert headings == [
        "PÁGINA HOME",
        "SEÇÃO PRODUTOS",
        "PRODUTO CAFÉ ESPECIAL",
        "CATEGORIA GRÃOS",
        "FILTRO TORRA MÉDIA",
        "VITRINE MOBILE",
        "CABEÇALHO",
        "RODAPÉ",
    ]
    storefront = pages[1:-2]
    assert all(
        urlsplit(page.url).netloc == urlsplit(origin).netloc
        for page in storefront
    )
    assert [page.tipo for page in storefront].count(PRODUTO_PUBLICADO) == 1
    assert any(page.tipo == VITRINE for page in storefront)
    assert any(page.tipo == VISAO_MOBILE for page in storefront)
    assert any(
        path.startswith("/wp-json/wc/store/v1/products")
        for _method, path in handler.requests
    )
    assert not any(method != "GET" for method, _path in handler.requests)
    assert not any(
        marker in path
        for _method, path in handler.requests
        for marker in ("add-to-cart", "/carrinho", "/checkout", "/wp-admin")
    )


def test_absent_public_signals_return_the_original_lista() -> None:
    with _serve_storefront(api_enabled=False) as (origin, _handler):
        original = (
            Pagina(PAGINA_PRINCIPAL, "Sobre", origin + "sobre/", "SEÇÃO SOBRE"),
            Pagina(ELEMENTO_TRANSVERSAL, "Rodapé", origin, "RODAPÉ"),
        )
        pages = discover_storefront_pages(
            origin + "sobre/",
            original,
            config=StorefrontDiscoveryConfig(max_confirmations=2),
        )

    assert pages == original


def test_confirmation_budget_is_finite() -> None:
    with _serve_storefront() as (origin, handler):
        discover_storefront_pages(
            origin,
            _base_pages(origin),
            config=StorefrontDiscoveryConfig(
                max_candidates=20,
                max_confirmations=2,
                max_taxonomies=2,
            ),
        )

    page_requests = [
        path
        for _method, path in handler.requests
        if not path.startswith("/wp-json/")
    ]
    assert len(page_requests) <= 3  # the origin plus two confirmations


def test_capture_uses_distinct_desktop_and_mobile_viewports(tmp_path: Path) -> None:
    with _serve_storefront() as (origin, _handler):
        pages = discover_storefront_pages(origin, _base_pages(origin))
        selected = tuple(
            page for page in pages if page.tipo in {VITRINE, VISAO_MOBILE}
        )
        result = capture_site(
            selected,
            tmp_path / "50-2026_LOJA" / "capturas",
            config=CaptureConfig(
                device_scale_factor=1,
                minimum_color_count=2,
                lazy_settle_ms=0,
            ),
        )

    assert result.failures == ()
    by_type = {capture.pagina.tipo: capture for capture in result.captures}
    assert by_type[VITRINE].raw_width == 1600
    assert by_type[VISAO_MOBILE].raw_width == 390


def test_conventional_storefront_run_uses_one_lista_for_blocks_and_briefing(
    tmp_path: Path,
) -> None:
    with _serve_storefront() as (origin, _handler):
        engagement = Engagement(
            row_number=2,
            demanda="013292/2026",
            pasta="50-2026",
            razao_social="EMPORIO TESTE",
            cnpj="52.052.612/0001-21",
            kick_off=datetime(2026, 4, 15),
            especialista="Especialista",
            capture_origin=origin,
            published_domain=None,
            tema=LOJA_VIRTUAL_TEMA,
        )
        contract = supported_contract(engagement.tema)
        assert contract.master is not None
        package = assemble_output_package(
            contract.master,
            tmp_path / "outputs",
            engagement,
            tmp_path / "gated",
            no_llm=True,
            preview_renderer=_FakePreviewRenderer(),
        )

    headings = tuple(page.titulo_bloco for page in package.pages)
    assert package.report.context.blocks == headings
    assert "SEÇÃO PRODUTOS" in headings
    assert "PRODUTO CAFÉ ESPECIAL" in headings
    assert "CATEGORIA GRÃOS" in headings
    assert "VITRINE MOBILE" in headings
    assert any(
        item.slot == "produtos-admin" and item.classification == "GATED"
        for item in package.report.context.pendencias
    )
    assert all(
        Path(item.source).is_relative_to(package.directory)
        for item in package.report.context.artifacts_of("capture")
        if item.source is not None
    )
