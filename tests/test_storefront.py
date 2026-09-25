from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest

from report_generator9000.assembly import assemble_output_package
from report_generator9000.capture import CaptureConfig, capture_site
from report_generator9000.control_sheet import Engagement
from report_generator9000.docx_package import open_docx_package
from report_generator9000.generate import StopCondition
from report_generator9000.lista_paginas import (
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    PRODUTO_PUBLICADO,
    VISAO_MOBILE,
    VITRINE,
    Pagina,
)
from report_generator9000.prose import (
    GroundedField,
    ProseConfig,
    ProseResponse,
    deterministic_page_paragraph,
)
from report_generator9000.runs import STAGES, RunService, RunStore
from report_generator9000.storefront import (
    StorefrontDiscoveryConfig,
    StorefrontDiscoveryResponse,
    StorefrontProviderCandidate,
    discover_storefront_pages,
)
from report_generator9000.tema import LOJA_VIRTUAL_TEMA, supported_contract
from tests.test_assembly import _FakePreviewRenderer


class _StorefrontHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str]] = []
    api_enabled = True
    customized_only = False
    # A menu page gives the customized store one capturable Página, so a Run
    # has usable evidence even when storefront discovery finds nothing.
    customized_nav = False

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
        conventional_home = """
                <h1>Empório</h1><nav><a href='/sobre/'>Sobre</a></nav>
                <main>
                  <a class='shop-card' href='/loja/'>Conheça a loja</a>
                  <a class='product-card' href='/produto/cafe/'>Café Especial</a>
                  <a href='/categoria-produto/graos/'>Grãos</a>
                  <a class='product-filter' href='/loja/?filter_torra=media'>Torra média</a>
                  <a class='entry' href='/colecao-especial/'>Coleção especial</a>
                  <a class='entry' href='/item/cafe-raro/'>Café raro</a>
                  <a class='entry' href='/item/inventado/'>Inventado</a>
                  <a href='/carrinho/?add-to-cart=10'>Comprar agora</a>
                  <a href='https://outside.example/produto/fora/'>Externo</a>
                  <script>fetch('/checkout/', {method: 'POST'})</script>
                </main>
                <footer>Contato e informações da empresa</footer>
            """
        customized_nav = (
            "<nav><a href='/sobre/'>Sobre</a></nav>"
            if type(self).customized_nav
            else ""
        )
        customized_home = f"""
                <h1>Empório</h1>{customized_nav}
                <main>
                  <a class='entry' href='/colecao-especial/'>Coleção especial</a>
                  <a class='entry' href='/sobre/'>Sobre</a>
                  <p>Catálogo externo: https://outside.example/produtos/</p>
                </main>
                <footer>Contato e informações da empresa</footer>
            """
        pages = {
            "/": customized_home if type(self).customized_only else conventional_home,
            "/loja/": "<h1>Loja</h1><p>Produtos disponíveis para compra pública.</p>",
            "/produto/cafe/": (
                "<h1>Café Especial</h1>"
                "<p>Produto publicado com descrição completa.</p>"
            ),
            "/categoria-produto/graos/": (
                "<h1>Grãos</h1><p>Categoria pública de produtos.</p>"
            ),
            "/colecao-especial/": (
                "<h1>Coleção especial</h1>"
                "<p>Vitrine personalizada com itens publicados.</p>"
                "<a class='entry' href='/item/cafe-raro/'>Café raro</a>"
                "<a class='entry' href='/item/inventado/'>Inventado</a>"
            ),
            "/item/cafe-raro/": (
                "<article class='type-product'><h1>Café raro</h1>"
                "<p>Item publicado com descrição completa.</p></article>"
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
            f"<body{' class=single-product' if parsed.path == '/item/cafe-raro/' else ''}>"
            f"<header>Empório</header>{body}</body></html>"
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
    *,
    api_enabled: bool = True,
    customized_only: bool = False,
    customized_nav: bool = False,
) -> Iterator[tuple[str, type[_StorefrontHandler]]]:
    class Handler(_StorefrontHandler):
        requests: list[tuple[str, str]] = []

    Handler.api_enabled = api_enabled
    Handler.customized_only = customized_only
    Handler.customized_nav = customized_nav
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


class _FakeStorefrontProvider:
    def __init__(
        self,
        response: StorefrontDiscoveryResponse | Exception,
    ) -> None:
        self.response = response
        self.discovery_requests = []

    def discover_storefront(self, request, config):
        self.discovery_requests.append((request, config))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def generate(self, request, config):
        empty = GroundedField(value=None, grounded=False)
        return ProseResponse(empty, empty)


def _candidate(
    *, kind: str, label: str, url: str, source_id: str, excerpt: str
) -> StorefrontProviderCandidate:
    return StorefrontProviderCandidate(
        kind=kind,
        label=label,
        url=url,
        source_id=source_id,
        excerpt=excerpt,
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
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
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


def test_provider_is_not_invoked_when_deterministic_signals_are_sufficient() -> None:
    provider = _FakeStorefrontProvider(StorefrontDiscoveryResponse(()))
    with _serve_storefront() as (origin, _handler):
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert provider.discovery_requests == []
    assert any(page.tipo == VITRINE for page in pages)
    assert any(page.tipo == PRODUTO_PUBLICADO for page in pages)


def test_provider_candidates_need_literal_evidence_and_browser_confirmation() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        listing_source_id = "public-page-1"
        product_source_id = "public-page-2"
        listing_url = origin + "colecao-especial/"
        product_url = origin + "item/cafe-raro/"
        missing_url = origin + "item/inventado/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Coleção especial",
                        url=listing_url,
                        source_id=listing_source_id,
                        excerpt=f"Coleção especial | {listing_url}",
                    ),
                    _candidate(
                        kind=PRODUTO_PUBLICADO,
                        label="Café raro",
                        url=product_url,
                        source_id=product_source_id,
                        excerpt=f"Café raro | {product_url}",
                    ),
                    _candidate(
                        kind=PRODUTO_PUBLICADO,
                        label="Inventado",
                        url=missing_url,
                        source_id=product_source_id,
                        excerpt=f"Inventado | {missing_url}",
                    ),
                )
            )
        )
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert len(provider.discovery_requests) == 1
    request, _config = provider.discovery_requests[0]
    assert len(request.pages) == 3
    assert [page.titulo_bloco for page in pages[1:-2]] == [
        "SEÇÃO PRODUTOS",
        "PRODUTO CAFÉ RARO",
        "VITRINE MOBILE",
    ]


def test_unsupported_provider_evidence_fails_closed() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Coleção especial",
                        url=origin + "colecao-especial/",
                        source_id="public-page-1",
                        excerpt="texto que a página nunca apresentou",
                    ),
                )
            )
        )
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert pages == _base_pages(origin)


def test_provider_label_requires_literal_evidence() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        listing_url = origin + "colecao-especial/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Loja incrível",
                        url=listing_url,
                        source_id="public-page-1",
                        excerpt=f"Coleção especial | {listing_url}",
                    ),
                )
            )
        )
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert pages == _base_pages(origin)


def test_cross_origin_provider_url_fails_closed() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        outside = "https://outside.example/produtos/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Catálogo externo",
                        url=outside,
                        source_id="public-page-1",
                        excerpt=f"Catálogo externo: {outside}",
                    ),
                )
            )
        )
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert pages == _base_pages(origin)


def test_provider_page_type_requires_rendered_storefront_semantics() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        about_url = origin + "sobre/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=PRODUTO_PUBLICADO,
                        label="Sobre",
                        url=about_url,
                        source_id="public-page-1",
                        excerpt=f"Sobre | {about_url}",
                    ),
                )
            )
        )
        request_pages = list(_base_pages(origin))
        request_pages.insert(
            1,
            Pagina(PAGINA_PRINCIPAL, "Sobre", about_url, "SEÇÃO SOBRE"),
        )
        pages = discover_storefront_pages(
            origin,
            tuple(request_pages),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert not any(page.tipo == PRODUTO_PUBLICADO for page in pages)


def test_listing_markup_does_not_confirm_a_product_detail_page() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        listing_url = origin + "colecao-especial/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=PRODUTO_PUBLICADO,
                        label="Coleção especial",
                        url=listing_url,
                        source_id="public-page-1",
                        excerpt=f"Coleção especial | {listing_url}",
                    ),
                )
            )
        )
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert not any(page.tipo == PRODUTO_PUBLICADO for page in pages)


def test_contradictory_provider_candidates_fail_closed() -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        url = origin + "colecao-especial/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Coleção especial",
                        url=url,
                        source_id="public-page-1",
                        excerpt=f"Coleção especial | {url}",
                    ),
                    _candidate(
                        kind=PRODUTO_PUBLICADO,
                        label="Coleção especial",
                        url=url,
                        source_id="public-page-1",
                        excerpt=f"Coleção especial | {url}",
                    ),
                )
            )
        )
        pages = discover_storefront_pages(
            origin,
            _base_pages(origin),
            provider=provider,
            provider_config=ProseConfig(model="fake", output_budget=200),
        )

    assert pages == _base_pages(origin)


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


@pytest.mark.parametrize("failure", ["provider", "invalid-url"])
def test_customized_storefront_run_stops_on_unusable_fallback(
    tmp_path: Path,
    failure: str,
) -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        outside = "https://outside.example/produtos/"
        response: StorefrontDiscoveryResponse | Exception
        if failure == "provider":
            response = RuntimeError("provider unavailable")
        else:
            response = StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Catálogo externo",
                        url=outside,
                        source_id="public-page-1",
                        excerpt=f"Catálogo externo: {outside}",
                    ),
                )
            )
        provider = _FakeStorefrontProvider(response)
        engagement = Engagement(
            row_number=2,
            demanda="013292/2026",
            pasta="51-2026",
            razao_social="EMPORIO CUSTOMIZADO",
            cnpj="52.052.612/0001-21",
            kick_off=datetime(2026, 4, 15),
            especialista="Especialista",
            capture_origin=origin,
            published_domain=None,
            tema=LOJA_VIRTUAL_TEMA,
        )
        contract = supported_contract(engagement.tema)
        assert contract.master is not None
        with pytest.raises(StopCondition, match="nenhuma captura utilizável"):
            assemble_output_package(
                contract.master,
                tmp_path / "outputs",
                engagement,
                tmp_path / "gated",
                prose_provider=provider,
                prose_config=ProseConfig(model="fake", output_budget=200),
                preview_renderer=_FakePreviewRenderer(),
            )

    assert len(provider.discovery_requests) == 1


def test_customized_storefront_run_promotes_only_confirmed_fallback_pages(
    tmp_path: Path,
) -> None:
    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        listing_url = origin + "colecao-especial/"
        product_url = origin + "item/cafe-raro/"
        provider = _FakeStorefrontProvider(
            StorefrontDiscoveryResponse(
                (
                    _candidate(
                        kind=VITRINE,
                        label="Coleção especial",
                        url=listing_url,
                        source_id="public-page-1",
                        excerpt=f"Coleção especial | {listing_url}",
                    ),
                    _candidate(
                        kind=PRODUTO_PUBLICADO,
                        label="Café raro",
                        url=product_url,
                        source_id="public-page-2",
                        excerpt=f"Café raro | {product_url}",
                    ),
                )
            )
        )
        engagement = Engagement(
            row_number=2,
            demanda="013292/2026",
            pasta="51-2026",
            razao_social="EMPORIO CUSTOMIZADO",
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
            prose_provider=provider,
            prose_config=ProseConfig(model="fake", output_budget=200),
            preview_renderer=_FakePreviewRenderer(),
        )

    headings = tuple(page.titulo_bloco for page in package.pages)
    assert "SEÇÃO PRODUTOS" in headings
    assert "PRODUTO CAFÉ RARO" in headings
    assert "VITRINE MOBILE" in headings
    assert not any(
        item.name == "SEÇÃO PRODUTOS"
        for item in package.report.context.pendencias
    )


def _loja_engagement(origin: str, pasta: str, razao_social: str) -> Engagement:
    return Engagement(
        row_number=2,
        demanda="013292/2026",
        pasta=pasta,
        razao_social=razao_social,
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin=origin,
        published_domain=None,
        tema=LOJA_VIRTUAL_TEMA,
    )


def _assemble_loja(engagement: Engagement, root: Path, **options):
    contract = supported_contract(engagement.tema)
    assert contract.master is not None
    return assemble_output_package(
        contract.master,
        root / "outputs",
        engagement,
        root / "gated",
        preview_renderer=_FakePreviewRenderer(),
        **options,
    )


class _RecordingProseProvider(_FakeStorefrontProvider):
    """Records what the Briefing provider is shown, besides storefront calls."""

    def __init__(self, response: StorefrontDiscoveryResponse | Exception) -> None:
        super().__init__(response)
        self.prose_requests = []

    def generate(self, request, config):
        self.prose_requests.append(request)
        return super().generate(request, config)


def _fallback_provider(origin: str) -> _RecordingProseProvider:
    listing_url = origin + "colecao-especial/"
    product_url = origin + "item/cafe-raro/"
    return _RecordingProseProvider(
        StorefrontDiscoveryResponse(
            (
                _candidate(
                    kind=VITRINE,
                    label="Coleção especial",
                    url=listing_url,
                    source_id="public-page-1",
                    excerpt=f"Coleção especial | {listing_url}",
                ),
                _candidate(
                    kind=PRODUTO_PUBLICADO,
                    label="Café raro",
                    url=product_url,
                    source_id="public-page-2",
                    excerpt=f"Café raro | {product_url}",
                ),
            )
        )
    )


def test_conventional_storefront_briefing_reads_the_same_lista_as_the_blocks(
    tmp_path: Path,
) -> None:
    provider = _RecordingProseProvider(StorefrontDiscoveryResponse(()))
    with _serve_storefront() as (origin, _handler):
        package = _assemble_loja(
            _loja_engagement(origin, "50-2026", "EMPORIO TESTE"),
            tmp_path,
            prose_provider=provider,
            prose_config=ProseConfig(model="fake", output_budget=200),
        )

    assert provider.discovery_requests == []
    assert len(provider.prose_requests) == 1
    texts = [page.text for page in provider.prose_requests[0].site_text]
    # Every confirmed storefront Página the Blocks show is text the Briefing
    # provider reads; the mobile duplicate of the listing is not read twice.
    assert sum("Produtos disponíveis para compra pública." in t for t in texts) == 1
    assert any("Produto publicado com descrição completa." in t for t in texts)
    assert any("Categoria pública de produtos." in t for t in texts)
    briefing_pages = [page for page in package.pages if page.entra_no_briefing]
    assert len(texts) <= len(briefing_pages)
    document_text = "\n".join(
        paragraph.text
        for paragraph in open_docx_package(package.report.document).paragraphs
    )
    paragraph = deterministic_page_paragraph(package.pages)
    assert paragraph in document_text
    for page in briefing_pages:
        assert page.rotulo in paragraph


def test_two_pastas_of_one_storefront_never_share_captures(
    tmp_path: Path,
) -> None:
    with _serve_storefront() as (origin, _handler):
        first = _assemble_loja(
            _loja_engagement(origin, "50-2026", "EMPORIO TESTE"),
            tmp_path,
            no_llm=True,
        )
        second = _assemble_loja(
            _loja_engagement(origin, "53-2026", "OUTRO EMPORIO"),
            tmp_path,
            no_llm=True,
        )

    assert first.directory != second.directory
    for package, other in ((first, second), (second, first)):
        sources = [
            Path(item.source)
            for item in package.report.context.artifacts_of("capture")
            if item.source is not None
        ]
        assert sources
        assert all(path.is_relative_to(package.directory) for path in sources)
        assert not any(path.is_relative_to(other.directory) for path in sources)


def test_provider_failure_on_a_usable_customized_store_leaves_a_classified_draft(
    tmp_path: Path, recording_sink
) -> None:
    provider = _RecordingProseProvider(RuntimeError("provider unavailable"))
    with _serve_storefront(
        api_enabled=False, customized_only=True, customized_nav=True
    ) as (origin, _handler):
        package = _assemble_loja(
            _loja_engagement(origin, "51-2026", "EMPORIO CUSTOMIZADO"),
            tmp_path,
            prose_provider=provider,
            prose_config=ProseConfig(model="fake", output_budget=200),
        )

    assert len(provider.discovery_requests) == 1
    assert any(
        event.name == "storefront_provider_failed"
        for event in recording_sink.events
    )
    headings = tuple(page.titulo_bloco for page in package.pages)
    assert "SEÇÃO SOBRE" in headings
    assert not any(page.tipo == PRODUTO_PUBLICADO for page in package.pages)
    assert package.report.status == "draft"
    produtos = [
        item
        for item in package.report.context.pendencias
        if item.name == "SEÇÃO PRODUTOS"
    ]
    assert [item.classification for item in produtos] == ["TOOL_BLOCKED"]


def test_loja_run_with_provider_fallback_reports_nine_stages_in_order(
    tmp_path: Path, recording_sink
) -> None:
    def assemble(master, output_root, engagement, gated_root, **options):
        return assemble_output_package(
            master,
            output_root,
            engagement,
            gated_root,
            preview_renderer=_FakePreviewRenderer(),
            **options,
        )

    with _serve_storefront(
        api_enabled=False, customized_only=True
    ) as (origin, _handler):
        provider = _fallback_provider(origin)
        service = RunService(
            store=RunStore(tmp_path / "runs"),
            master=tmp_path / "MASTER.docx",
            output_root=tmp_path / "outputs",
            gated_drop_root=tmp_path / "gated",
            assembler=assemble,
            prose_provider=provider,
            prose_config=ProseConfig(model="fake", output_budget=200),
        )
        record = service.submit(
            _loja_engagement(origin, "51-2026", "EMPORIO CUSTOMIZADO"),
            sheet_id="sheet-1",
        )
        service.shutdown()

    finished = service.store.get(record.run_id)
    assert finished is not None
    assert finished.outcome == "finished", finished.reason
    assert finished.report_status == "draft"
    assert finished.stage_history == STAGES
    assert len(provider.discovery_requests) == 1
    stage_events = [
        event.name
        for event in recording_sink.events
        if event.kind == "stage" and event.run_id == record.run_id
    ]
    assert stage_events == list(STAGES)
