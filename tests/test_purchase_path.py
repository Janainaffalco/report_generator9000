"""The Loja Virtual purchase path is classified from public evidence only."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from fixtures.docx_builder import build_docx, paragraph
from report_generator9000 import purchase_path as purchase_path_module
from report_generator9000.assembly import assemble_output_package
from report_generator9000.capture import read_only_purchase_route
from report_generator9000.control_sheet import Engagement
from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates import run_gates
from report_generator9000.gates.loja_purchase import check_loja_purchase_claims
from report_generator9000.lista_paginas import (
    CARRINHO_PUBLICO,
    CHECKOUT_PUBLICO,
    PRODUTO_PUBLICADO,
    Pagina,
)
from report_generator9000.purchase_path import (
    FALHA,
    INCONCLUSIVO,
    INDICACAO_EXTERNA,
    INDICACAO_WHATSAPP,
    ROTA_NO_SITE,
    PurchaseAction,
    PurchasePath,
    classify_purchase_path,
    describe_purchase_path,
)
from report_generator9000.run_context import RunContext
from report_generator9000.tema import LOJA_VIRTUAL_TEMA, supported_contract
from tests.test_assembly import _FakePreviewRenderer


_STYLE = (
    "<style>:root{--brand-primary:#7a2f1f;--brand-secondary:#d68c45}"
    "body{background:#f7e7ce;color:#23160f}main{min-height:700px}"
    "a,button{display:block;padding:12px}</style>"
)
# Every public cart or checkout view fires the same background POST a real
# WooCommerce page sends; the read-only guard must stop it in the browser.
_FRAGMENTS = (
    "<script>fetch('/?wc-ajax=get_refreshed_fragments', {method: 'POST'})"
    "</script>"
)
_PRODUCT_TEXT = "<h1>Café Especial</h1><p>Produto publicado com descrição completa.</p>"

_PRODUCT_ACTION = {
    "whatsapp": (
        "<a class='button' href='https://wa.me/5511999999999?text=Quero%20comprar'>"
        "Comprar pelo WhatsApp</a>"
    ),
    "on_site": (
        "<form class='cart' action='/produto/cafe/' method='post'>"
        "<button type='submit' name='add-to-cart' value='10' "
        "class='single_add_to_cart_button button alt'>Adicionar ao carrinho</button>"
        "</form>"
    ),
    "external": (
        "<a class='single_add_to_cart_button button' "
        "href='https://marketplace.example/oferta/123?ref=loja'>"
        "Comprar no marketplace</a>"
    ),
    "inconclusive": "<p>Consulte disponibilidade pelo telefone da loja.</p>",
    "js_only": "<button type='button' onclick='void 0'>Comprar</button>",
    "chat_bubble": "<p>Consulte disponibilidade pelo telefone da loja.</p>",
    "share": (
        "<a class='share-whatsapp' "
        "href='https://api.whatsapp.com/send?text=Veja%20este%20produto'>"
        "Compartilhar no WhatsApp</a>"
    ),
    "share_as_buy": (
        "<a href='https://api.whatsapp.com/send?text=Veja%20este%20produto'>"
        "Comprar pelo WhatsApp</a>"
    ),
    "icon_only": (
        "<a class='wa-icon' href='https://wa.me/5511999999999' "
        "aria-label='Comprar pelo WhatsApp'>"
        "<svg width='32' height='32'><circle cx='16' cy='16' r='14'/></svg></a>"
        "<form class='cart' action='/produto/cafe/' method='post'>"
        "<button type='submit' name='add-to-cart' value='10' "
        "class='single_add_to_cart_button' aria-label='Adicionar ao carrinho'>"
        "<svg width='32' height='32'><rect width='28' height='28'/></svg></button></form>"
    ),
    "quantity_only": (
        "<form class='cart' action='/produto/cafe/' method='post'>"
        "<button type='button' class='minus'>-</button>"
        "<button type='button' class='plus'>+</button></form>"
    ),
}
for _variant in ("cart_5xx", "product_404", "product_5xx"):
    _PRODUCT_ACTION[_variant] = _PRODUCT_ACTION["on_site"]
# Stores that declare both pages through WooCommerce Blocks settings.
_ON_SITE_LIKE = frozenset(
    {"on_site", "icon_only", "quantity_only", "cart_5xx", "product_404", "product_5xx"}
)
_BLOCK_SETTINGS = (
    "<script>var wcSettings = {storePages: {cart: {permalink: '/carrinho/'},"
    " checkout: {permalink: '/finalizar-compra/'}}};</script>"
)
_DECLARATIONS = {
    "whatsapp": "<script>var wc_add_to_cart_params = {cart_url: '/carrinho/'};</script>",
    "inconclusive": "<script>var wc_add_to_cart_params = {cart_url: '/carrinho/'};</script>",
    **{variant: _BLOCK_SETTINGS for variant in _ON_SITE_LIKE},
}
_SERVER_ERROR = {"cart_5xx": {"/carrinho/", "/finalizar-compra/"}, "product_5xx": {"/produto/cafe/"}}


class _PurchaseHandler(BaseHTTPRequestHandler):
    variant = "whatsapp"
    requests: list[tuple[str, str]] = []

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        type(self).requests.append(("POST", self.path))
        self.send_error(405)

    def do_GET(self) -> None:
        type(self).requests.append(("GET", self.path))
        variant = type(self).variant
        path = urlsplit(self.path).path
        header = (
            "<header>Empório <a href='/finalizar-compra/'>Finalizar compra</a></header>"
            if variant == "whatsapp"
            else "<header>Empório</header>"
        )
        bubble = (
            "<a class='whatsapp-float' href='https://wa.me/5511999999999'>Fale conosco</a>"
            if variant == "chat_bubble"
            else ""
        )
        body_class = ""
        if path in _SERVER_ERROR.get(variant, ()):
            self.send_error(503)
            return
        if path == "/produto/cafe/" and variant == "product_404":
            self.send_error(404)
            return
        if path == "/":
            body = (
                "<h1>Empório</h1><nav><a href='/sobre/'>Sobre</a></nav><main>"
                "<a class='shop-card' href='/loja/'>Conheça a loja</a>"
                "<a class='product-card' href='/produto/cafe/'>Café Especial</a>"
                "</main><footer>Contato e informações da empresa</footer>"
            )
        elif path == "/loja/":
            body = "<h1>Loja</h1><p>Produtos disponíveis para visitantes.</p>"
        elif path == "/sobre/":
            body = "<h1>Sobre</h1><p>História completa do empório.</p>"
        elif path == "/produto/cafe/":
            body_class = "single-product"
            body = (
                "<main><div class='product type-product'><div class='summary entry-summary'>"
                f"{_PRODUCT_TEXT}{_PRODUCT_ACTION[variant]}</div></div></main>{bubble}"
            )
        elif path == "/carrinho/" and (variant == "whatsapp" or variant in _ON_SITE_LIKE):
            body_class = "woocommerce-cart"
            body = (
                "<main><h1>Carrinho</h1><div class='woocommerce'>"
                "<p class='cart-empty woocommerce-info'>Seu carrinho está vazio.</p>"
                "<a href='/loja/'>Voltar para a loja</a></div></main>" + _FRAGMENTS
            )
        elif path == "/finalizar-compra/" and variant == "whatsapp":
            self.send_response(302)
            self.send_header("Location", "/carrinho/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        elif path == "/finalizar-compra/" and variant in _ON_SITE_LIKE:
            body_class = "woocommerce-checkout"
            body = (
                "<main><h1>Finalizar compra</h1>"
                "<form class='checkout woocommerce-checkout'>"
                "<h3>Detalhes de cobrança</h3><p>Preencha seus dados.</p>"
                "</form></main>" + _FRAGMENTS
            )
        else:
            self.send_error(404)
            return
        markup = (
            f"<html><head>{_STYLE}{_DECLARATIONS.get(variant, '')}</head>"
            f"<body class='{body_class}'>{header}{body}</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(markup)))
        self.end_headers()
        self.wfile.write(markup)


@contextmanager
def _serve(variant: str) -> Iterator[tuple[str, type[_PurchaseHandler]]]:
    class Handler(_PurchaseHandler):
        requests: list[tuple[str, str]] = []

    Handler.variant = variant
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _product(origin: str) -> Pagina:
    return Pagina(
        PRODUTO_PUBLICADO,
        "Café Especial",
        origin + "produto/cafe/",
        "PRODUTO CAFÉ ESPECIAL",
    )


def _engagement(origin: str) -> Engagement:
    return Engagement(
        row_number=2,
        demanda="013292/2026",
        pasta="52-2026",
        razao_social="EMPORIO COMPRA",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin=origin,
        published_domain=None,
        tema=LOJA_VIRTUAL_TEMA,
    )


def _run(variant: str, tmp_path: Path):
    with _serve(variant) as (origin, handler):
        contract = supported_contract(LOJA_VIRTUAL_TEMA)
        assert contract.master is not None
        package = assemble_output_package(
            contract.master,
            tmp_path / "outputs",
            _engagement(origin),
            tmp_path / "gated",
            no_llm=True,
            preview_renderer=_FakePreviewRenderer(),
        )
    return package, handler


def _document_text(package) -> str:
    return "\n".join(
        item.text for item in open_docx_package(package.report.document).paragraphs
    )


def _pendencias_by_name(package) -> dict[str, object]:
    return {item.name: item for item in package.report.context.pendencias}


def _assert_read_only(handler: type[_PurchaseHandler]) -> None:
    assert not any(method != "GET" for method, _path in handler.requests)
    for _method, path in handler.requests:
        assert "add-to-cart" not in path
        assert "wc-ajax" not in path


def test_whatsapp_referral_is_reported_as_off_site_completion(tmp_path: Path) -> None:
    package, handler = _run("whatsapp", tmp_path)

    text = _document_text(package)
    assert (
        "a ação “Comprar pelo WhatsApp” direciona o visitante a uma conversa "
        "no WhatsApp, fora do site" in text
    )
    assert "não observa o que ocorre após esse direcionamento" in text
    assert "pertence ao carrinho do próprio site" not in text
    pendencias = _pendencias_by_name(package)
    assert "caminho de compra" not in pendencias
    # The cart page exists and is shown; the empty checkout falls back to the
    # cart, so it proves nothing and stays INCONCLUSIVO -- never the cart print.
    assert any(page.tipo == CARRINHO_PUBLICO for page in package.pages)
    assert "SEÇÃO CARRINHO" not in pendencias
    assert not any(page.tipo == CHECKOUT_PUBLICO for page in package.pages)
    checkout = pendencias["SEÇÃO CHECKOUT"]
    assert checkout.classification == "INCONCLUSIVO"
    assert "redireciona para o carrinho" in checkout.reason
    grounding = [
        item for item in package.report.context.prose_grounding
        if item.field == "caminho_de_compra"
    ]
    assert len(grounding) == 1
    assert "https://wa.me/5511999999999" in grounding[0].excerpt
    assert "text=" not in grounding[0].excerpt
    assert run_gates(
        open_docx_package(package.report.document),
        package.report.context,
        tema=LOJA_VIRTUAL_TEMA,
    ).passed
    _assert_read_only(handler)
    assert ("GET", "/carrinho/") in handler.requests


def test_on_site_route_is_verified_without_changing_the_cart(tmp_path: Path) -> None:
    package, handler = _run("on_site", tmp_path)

    text = _document_text(package)
    assert "a ação “Adicionar ao carrinho” pertence ao carrinho do próprio site" in text
    assert "não aciona essa ação e não registra pedidos, pagamentos ou transações" in text
    pendencias = _pendencias_by_name(package)
    assert "caminho de compra" not in pendencias
    assert "SEÇÃO CARRINHO" not in pendencias
    assert "SEÇÃO CHECKOUT" not in pendencias
    headings = [page.titulo_bloco for page in package.pages]
    assert headings.index("SEÇÃO CARRINHO") < headings.index("SEÇÃO CHECKOUT")
    captured = {
        capture.pagina.tipo for capture in package.capture_run.captures
    }
    assert {CARRINHO_PUBLICO, CHECKOUT_PUBLICO} <= captured
    assert not any(
        page.entra_no_briefing
        for page in package.pages
        if page.tipo in {CARRINHO_PUBLICO, CHECKOUT_PUBLICO}
    )
    assert package.report.status == "draft"
    _assert_read_only(handler)
    assert ("GET", "/finalizar-compra/") in handler.requests


def test_inconclusive_purchase_path_is_marked_not_guessed(tmp_path: Path) -> None:
    package, handler = _run("inconclusive", tmp_path)

    text = _document_text(package)
    assert "[PENDÊNCIA: INCONCLUSIVO — caminho de compra]" in text
    for claim in ("pertence ao carrinho", "WhatsApp", "fora do site"):
        assert claim not in text
    pendencias = _pendencias_by_name(package)
    path = pendencias["caminho de compra"]
    assert path.classification == "INCONCLUSIVO"
    assert path.page == "FUNCIONALIDADES DA LOJA"
    cart = pendencias["SEÇÃO CARRINHO"]
    assert cart.classification == "INCONCLUSIVO"
    assert "HTTP 404" in cart.reason
    checkout = pendencias["SEÇÃO CHECKOUT"]
    assert checkout.classification == "INCONCLUSIVO"
    assert "não declara" in checkout.reason
    assert not any(
        item.classification == "TOOL_BLOCKED"
        and item.name in {"SEÇÃO CARRINHO", "SEÇÃO CHECKOUT", "caminho de compra"}
        for item in package.report.context.pendencias
    )
    assert package.report.status == "draft"
    _assert_read_only(handler)


def test_an_external_purchase_action_is_a_referral_without_its_query() -> None:
    with _serve("external") as (origin, handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == INDICACAO_EXTERNA
    assert path.action == PurchaseAction(
        "Comprar no marketplace", "https://marketplace.example/oferta/123"
    )
    assert {gap.heading for gap in path.gaps} == {"SEÇÃO CARRINHO", "SEÇÃO CHECKOUT"}
    assert all(gap.classification == "INCONCLUSIVO" for gap in path.gaps)
    _assert_read_only(handler)


@pytest.mark.parametrize("variant", ["js_only", "chat_bubble"])
def test_an_unverifiable_action_is_inconclusive(variant: str) -> None:
    with _serve(variant) as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == INCONCLUSIVO
    assert path.action is None
    assert "não apresenta uma ação de compra" in path.reason


def test_no_confirmed_product_is_inconclusive() -> None:
    with _serve("on_site") as (origin, _handler):
        path = classify_purchase_path(origin, ())

    assert path.classification == INCONCLUSIVO
    assert "nenhum produto publicado" in path.reason
    # The cart and checkout are still public pages the store declares.
    assert {page.tipo for page in path.pages} == {CARRINHO_PUBLICO, CHECKOUT_PUBLICO}


def test_an_unreachable_product_page_is_tool_blocked() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}/"
    path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == FALHA
    assert {gap.classification for gap in path.gaps} == {"TOOL_BLOCKED"}
    statement = describe_purchase_path(path, origin)
    assert statement.is_gap
    assert statement.pendencia is not None
    assert statement.pendencia.classification == "TOOL_BLOCKED"


@pytest.mark.parametrize(
    "path",
    [
        PurchasePath(
            INDICACAO_WHATSAPP, "", "https://loja.example/produto/x/",
            PurchaseAction("Comprar pelo WhatsApp", "https://wa.me/5511999999999"),
        ),
        PurchasePath(
            INDICACAO_EXTERNA, "", "https://loja.example/produto/x/",
            PurchaseAction("Comprar", "https://marketplace.example/x"),
        ),
        PurchasePath(
            ROTA_NO_SITE, "", "https://loja.example/produto/x/",
            PurchaseAction("Adicionar ao carrinho", "https://loja.example/produto/x/"),
        ),
    ],
)
def test_every_purchase_statement_passes_the_purchase_claims_gate(
    tmp_path: Path, path: PurchasePath
) -> None:
    statement = describe_purchase_path(path, "https://loja.example/")
    assert not statement.is_gap and statement.pendencia is None
    assert f"“{path.action.label}”" in statement.text
    # The observation never presses the action, so no sentence may say what
    # pressing it does or that a purchase is finished anywhere. The quoted
    # label is the store's own visible text, not the report's claim.
    folded = statement.text.replace(f"“{path.action.label}”", "").casefold()
    for overclaim in ("finaliza", "conclu", "adiciona", "assistida", "compra ocorre"):
        assert overclaim not in folded
    document = tmp_path / "statement.docx"
    build_docx(document, paragraphs=(paragraph(statement.text),))
    assert check_loja_purchase_claims(open_docx_package(document), RunContext()).passed


@pytest.mark.parametrize(
    "claim",
    [
        "A loja processa pagamentos online com segurança.",
        "As vendas online foram concluídas no período.",
        "O pagamento está configurado com o gateway contratado.",
        "O frete é calculado automaticamente para todo o Brasil.",
        "O controle de estoque está ativado.",
        "Compra 100% segura em nosso site.",
        "O checkout no próprio site foi testado.",
    ],
)
def test_unevidenced_sale_or_setting_claims_are_rejected(
    tmp_path: Path, claim: str
) -> None:
    document = tmp_path / "claim.docx"
    build_docx(document, paragraphs=(paragraph(claim),))
    assert not check_loja_purchase_claims(open_docx_package(document), RunContext()).passed


def test_the_loja_master_carries_no_sale_or_setting_claims() -> None:
    contract = supported_contract(LOJA_VIRTUAL_TEMA)
    assert contract.master is not None
    assert check_loja_purchase_claims in contract.gates
    package = open_docx_package(contract.master)
    assert check_loja_purchase_claims(package, RunContext()).passed
    text = "\n".join(item.text for item in package.paragraphs)
    assert "Caminho de compra observado na loja pública: {{EVIDENCIA_CHECKOUT}}" in text


@pytest.mark.parametrize("variant", ["share", "share_as_buy"])
def test_a_whatsapp_share_link_is_never_a_purchase_action(variant: str) -> None:
    with _serve(variant) as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == INCONCLUSIVO
    assert path.action is None


def test_an_icon_without_visible_text_is_never_given_a_label() -> None:
    with _serve("icon_only") as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    # Both actions carry only an aria-label; neither is read as visible text,
    # so no sentence can quote a label the visitor never sees.
    assert path.classification == INCONCLUSIVO
    assert path.action is None
    statement = describe_purchase_path(path, origin)
    assert statement.is_gap
    assert "“" not in statement.text


def test_quantity_buttons_are_not_purchase_actions() -> None:
    with _serve("quantity_only") as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == INCONCLUSIVO
    assert path.action is None
    assert "não apresenta uma ação de compra" in path.reason


def test_server_errors_on_cart_and_checkout_are_tool_blocked(tmp_path: Path) -> None:
    package, handler = _run("cart_5xx", tmp_path)

    pendencias = _pendencias_by_name(package)
    for heading in ("SEÇÃO CARRINHO", "SEÇÃO CHECKOUT"):
        assert pendencias[heading].classification == "TOOL_BLOCKED"
        assert "HTTP 503" in pendencias[heading].reason
    # The add-to-cart submit is visible, but the cart that would settle it
    # failed: a blocked answer, never merely inconclusive.
    path = pendencias["caminho de compra"]
    assert path.classification == "TOOL_BLOCKED"
    assert "[PENDÊNCIA: FALHA NA AUTOMAÇÃO — caminho de compra]" in _document_text(package)
    _assert_read_only(handler)


def test_a_missing_product_page_is_inconclusive_and_the_cart_is_still_read() -> None:
    with _serve("product_404") as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == INCONCLUSIVO
    assert "HTTP 404" in path.reason
    assert path.action is None
    assert {page.tipo for page in path.pages} == {CARRINHO_PUBLICO, CHECKOUT_PUBLICO}


def test_a_failing_product_page_is_tool_blocked() -> None:
    with _serve("product_5xx") as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == FALHA
    assert "HTTP 503" in path.reason
    assert {gap.classification for gap in path.gaps} == {"TOOL_BLOCKED"}


def test_an_unexpected_error_is_tool_blocked_not_inconclusive(
    monkeypatch: pytest.MonkeyPatch, recording_sink
) -> None:
    def broken(*_args, **_kwargs):
        raise ValueError("unexpected")

    monkeypatch.setattr(purchase_path_module, "_classify_actions", broken)
    with _serve("on_site") as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == FALHA
    assert "ValueError" in path.reason
    assert {gap.classification for gap in path.gaps} == {"TOOL_BLOCKED"}
    assert any(
        event.name == "purchase_path_failed" for event in recording_sink.events
    )
    statement = describe_purchase_path(path, origin)
    assert statement.pendencia is not None
    assert statement.pendencia.classification == "TOOL_BLOCKED"


def test_a_malformed_page_observation_is_tool_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(purchase_path_module, "_OBSERVE_SCRIPT", "(limit) => 42")
    with _serve("on_site") as (origin, _handler):
        path = classify_purchase_path(origin, (_product(origin),))

    assert path.classification == FALHA
    assert "UnexpectedObservation" in path.reason


class _FakeRoute:
    def __init__(self, method: str, url: str) -> None:
        self.request = SimpleNamespace(method=method, url=url)
        self.outcome: str | None = None

    def abort(self) -> None:
        self.outcome = "abort"

    def continue_(self) -> None:
        self.outcome = "continue"


@pytest.mark.parametrize(
    ("method", "url", "outcome"),
    [
        ("GET", "https://loja.example/carrinho/", "continue"),
        ("GET", "https://loja.example/finalizar-compra/", "continue"),
        ("HEAD", "https://loja.example/carrinho/", "continue"),
        ("POST", "https://loja.example/carrinho/", "abort"),
        ("POST", "https://loja.example/?wc-ajax=get_refreshed_fragments", "abort"),
        ("GET", "https://loja.example/?add-to-cart=10", "abort"),
        ("GET", "https://loja.example/checkout/order-pay/123/", "abort"),
        ("GET", "https://loja.example/finalizar-compra/order-pay/123/?key=x", "abort"),
        ("GET", "https://loja.example/checkout/?pay_for_order=true", "abort"),
        ("GET", "https://loja.example/checkout/order-received/123/", "abort"),
        ("GET", "https://loja.example/minha-conta/", "abort"),
        ("GET", "https://loja.example/wp-admin/", "abort"),
    ],
)
def test_the_purchase_route_guard_allows_only_reads(
    method: str, url: str, outcome: str
) -> None:
    route = _FakeRoute(method, url)
    read_only_purchase_route(route)
    assert route.outcome == outcome
