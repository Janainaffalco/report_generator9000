"""Classify how a public visitor proceeds from a Loja Virtual product page."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError, Page

from . import events
from .browser_session import browser_context
from .capture import NO_CACHE_HEADERS, read_only_purchase_route
from .lista_paginas import (
    CARRINHO_PUBLICO,
    CHECKOUT_PUBLICO,
    ELEMENTO_TRANSVERSAL,
    PRODUTO_PUBLICADO,
    Pagina,
)
from .run_context import Grounding, Pendencia, pendencia_marker


INDICACAO_WHATSAPP = "indicacao_whatsapp"
INDICACAO_EXTERNA = "indicacao_externa"
ROTA_NO_SITE = "rota_no_site"
INCONCLUSIVO = "inconclusivo"
FALHA = "falha"

CARRINHO_HEADING = "SEÇÃO CARRINHO"
CHECKOUT_HEADING = "SEÇÃO CHECKOUT"
SLOT = "caminho_de_compra"
SECTION = "FUNCIONALIDADES DA LOJA"

_CART_SEGMENTS = frozenset({"cart", "carrinho"})
_CHECKOUT_SEGMENTS = frozenset({"checkout", "finalizar-compra"})
_SOCIAL_HOSTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
)
_PURCHASE_WORDS = re.compile(
    r"\b(comprar|compre|compra|adicionar ao carrinho|add to cart|buy|"
    r"encomendar|encomende|fazer pedido|pedir)\b"
)
# A share button often sits beside the purchase action and links to WhatsApp
# too; sharing a product is never a way to buy it.
_SHARE_WORDS = re.compile(
    r"\b(compartilh\w*|share|enviar para|envie para|indicar|indique)\b"
)
_PHONE = re.compile(r"\+?\d{8,15}")
_SPACE = re.compile(r"\s+")

# Everything the product page shows that a visitor could press, plus the
# addresses WooCommerce itself declares for its cart and checkout. Read only:
# nothing here clicks, submits or changes the page. A label is only the text a
# visitor can read -- an icon's aria-label or title is not a visible label.
_OBSERVE_SCRIPT = """
(limit) => {
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 &&
      style.visibility !== 'hidden' && style.display !== 'none';
  };
  const text = (el) => ((el.tagName === 'INPUT' ? el.value : el.innerText) || '')
    .replace(/\\s+/g, ' ').trim().slice(0, 120);
  const productArea = 'div.product, .type-product, .summary, .entry-summary, ' +
    'form.cart, .wp-block-add-to-cart-form, .wc-block-components-product-button';
  const actions = [];
  for (const el of document.querySelectorAll('a[href], button, input[type=submit]')) {
    if (actions.length >= limit) break;
    if (!visible(el)) continue;
    const form = el.closest('form');
    actions.push({
      tag: el.tagName.toLowerCase(),
      type: el.tagName === 'A' ? '' : (el.getAttribute('type') || 'submit').toLowerCase(),
      name: el.getAttribute('name') || '',
      label: text(el),
      href: el.tagName === 'A' ? el.href : '',
      classes: typeof el.className === 'string' ? el.className : '',
      formAction: form ? form.action : '',
      formCart: form ? (form.classList.contains('cart') ||
        !!form.querySelector('[name=add-to-cart]')) : false,
      inProduct: !!el.closest(productArea),
    });
  }
  const links = [];
  for (const el of document.querySelectorAll('a[href]')) {
    if (links.length >= limit) break;
    links.push(el.href);
  }
  const params = window.wc_add_to_cart_params || {};
  const pages = (window.wcSettings && window.wcSettings.storePages) || {};
  return {
    actions,
    links,
    cartUrl: String(params.cart_url || (pages.cart && pages.cart.permalink) || ''),
    checkoutUrl: String((pages.checkout && pages.checkout.permalink) || ''),
  };
}
"""

_MARKUP_SCRIPT = """
(selectors) => !!document.querySelector(selectors)
"""
_CART_MARKUP = (
    "body.woocommerce-cart, .woocommerce-cart-form, .cart-empty, "
    ".wc-empty-cart-message, .wp-block-woocommerce-cart, .wc-block-cart"
)
_CHECKOUT_MARKUP = (
    "body.woocommerce-checkout, form.checkout, form.woocommerce-checkout, "
    ".wp-block-woocommerce-checkout, .wc-block-checkout"
)


class UnexpectedObservation(RuntimeError):
    """The rendered page answered the observation in an unexpected shape."""


@dataclass(frozen=True)
class PurchasePathConfig:
    """Finite budgets for one purchase-path observation."""

    navigation_timeout_ms: int = 20_000
    settle_ms: int = 250
    max_elements: int = 200


@dataclass(frozen=True)
class PurchaseAction:
    """The visible action a visitor presses, and where it leads."""

    label: str
    destination: str


@dataclass(frozen=True)
class PurchaseGap:
    """A cart or checkout Block that public evidence could not show."""

    heading: str
    classification: str
    reason: str


@dataclass(frozen=True)
class PurchasePath:
    """How a visitor proceeds from a published product, as observed.

    ``pages`` are the confirmed empty cart and checkout views to Capture;
    ``gaps`` are the ones that stay classified gaps instead.
    """

    classification: str
    reason: str
    product_url: str | None = None
    action: PurchaseAction | None = None
    pages: tuple[Pagina, ...] = ()
    gaps: tuple[PurchaseGap, ...] = ()


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACE.sub(" ", plain.casefold()).strip()


def _host(url: str) -> str:
    host = urlsplit(url).netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def _segments(url: str) -> frozenset[str]:
    return frozenset(
        segment.casefold() for segment in urlsplit(url).path.split("/") if segment
    )


def _same_origin(base: str, candidate: str, expected_host: str) -> str | None:
    if not candidate:
        return None
    absolute = urljoin(base, candidate)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.casefold() != expected_host or parsed.username or parsed.password:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _is_whatsapp(host: str) -> bool:
    return host == "wa.me" or host == "whatsapp.com" or host.endswith(".whatsapp.com")


def _whatsapp_has_phone(url: str) -> bool:
    """A purchase conversation targets a number; a share link targets nobody."""
    parsed = urlsplit(url)
    if _host(url) == "wa.me":
        return bool(_PHONE.fullmatch(parsed.path.strip("/")))
    phone = dict(parse_qsl(parsed.query)).get("phone", "")
    return bool(_PHONE.fullmatch(phone))


def _is_social(host: str) -> bool:
    return any(host == item or host.endswith("." + item) for item in _SOCIAL_HOSTS)


def _without_query(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _classify_actions(
    actions: list[dict[str, object]], base: str, expected_host: str
) -> tuple[list[PurchaseAction], list[PurchaseAction], list[PurchaseAction]]:
    """Sort visible actions; one without a readable purchase label never counts."""
    whatsapp: list[PurchaseAction] = []
    external: list[PurchaseAction] = []
    on_site: list[PurchaseAction] = []
    own_host = expected_host.removeprefix("www.")
    for item in actions:
        label = _SPACE.sub(" ", str(item.get("label", ""))).strip()
        if not label:
            continue
        folded = _fold(label)
        if _SHARE_WORDS.search(folded):
            continue
        purchase_label = bool(_PURCHASE_WORDS.search(folded))
        classes = _fold(str(item.get("classes", "")))
        href = str(item.get("href", ""))
        host = _host(href) if href else ""
        if host and _is_whatsapp(host):
            if purchase_label and _whatsapp_has_phone(href):
                whatsapp.append(PurchaseAction(label, _without_query(href)))
            continue
        if host and host != own_host and not _is_social(host):
            if (
                purchase_label
                and (bool(item.get("inProduct")) or "add_to_cart" in classes)
                and urlsplit(href).scheme in {"http", "https"}
            ):
                external.append(PurchaseAction(label, _without_query(href)))
            continue
        form_action = _same_origin(base, str(item.get("formAction", "")), expected_host)
        if (
            item.get("formCart")
            and item.get("tag") in {"button", "input"}
            and item.get("type") == "submit"
            and form_action is not None
            and (
                purchase_label
                or item.get("name") == "add-to-cart"
                or "single_add_to_cart_button" in classes
            )
        ):
            on_site.append(PurchaseAction(label, form_action))
            continue
        same_origin_href = _same_origin(base, href, expected_host)
        if (
            same_origin_href is not None
            and "add_to_cart_button" in classes
            and purchase_label
        ):
            on_site.append(PurchaseAction(label, _without_query(same_origin_href)))
    return whatsapp, external, on_site


def _declared(
    declared: str,
    links: list[str],
    segments: frozenset[str],
    base: str,
    expected_host: str,
) -> str | None:
    for candidate in (declared, *links):
        url = _same_origin(base, str(candidate), expected_host)
        if url is not None and _segments(url) & segments and not urlsplit(url).query:
            return url
    return None


def _status_text(status: int | None) -> str:
    return "sem resposta HTTP" if status is None else f"HTTP {status}"


def _technical(status: int | None) -> bool:
    """No response or a server error is the site failing, not an answer."""
    return status is None or status >= 500


def _open(page: Page, url: str, settings: PurchasePathConfig) -> int | None:
    response = page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=settings.navigation_timeout_ms,
    )
    return None if response is None else response.status


def _verify(
    page: Page,
    url: str,
    *,
    name: str,
    markup: str,
    expected_host: str,
    cart_url: str | None,
    settings: PurchasePathConfig,
) -> tuple[str | None, PurchaseGap | None]:
    """Render one public view read-only; return its URL or a classified gap.

    A failed navigation, no response or HTTP 5xx is TOOL_BLOCKED; a 4xx is the
    store answering that the page is absent, so it is INCONCLUSIVO.
    """
    heading = CARRINHO_HEADING if name == "carrinho" else CHECKOUT_HEADING
    try:
        status = _open(page, url, settings)
    except PlaywrightError as error:
        return None, PurchaseGap(
            heading,
            "TOOL_BLOCKED",
            f"a navegação até a página pública de {name} falhou ({type(error).__name__})",
        )
    if _technical(status):
        return None, PurchaseGap(
            heading,
            "TOOL_BLOCKED",
            f"a página pública de {name} declarada pela loja respondeu "
            f"{_status_text(status)}",
        )
    if status is not None and status >= 400:
        return None, PurchaseGap(
            heading,
            "INCONCLUSIVO",
            f"a página pública de {name} declarada pela loja respondeu HTTP {status}",
        )
    final = _same_origin(url, page.url, expected_host)
    if final is None:
        return None, PurchaseGap(
            heading,
            "INCONCLUSIVO",
            f"a página pública de {name} saiu do endereço da loja",
        )
    if name == "checkout" and (
        _segments(final) & _CART_SEGMENTS
        or (cart_url is not None and _without_query(final) == _without_query(cart_url))
    ):
        return None, PurchaseGap(
            heading,
            "INCONCLUSIVO",
            "o checkout público redireciona para o carrinho quando não há itens",
        )
    page.wait_for_timeout(settings.settle_ms)
    if page.evaluate(_MARKUP_SCRIPT, markup) is not True:
        return None, PurchaseGap(
            heading,
            "INCONCLUSIVO",
            f"a página não apresenta a marcação pública de {name} do WooCommerce",
        )
    return final, None


def _observation(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise UnexpectedObservation("observation is not an object")
    actions = value.get("actions")
    links = value.get("links")
    if not isinstance(actions, list) or not all(isinstance(i, dict) for i in actions):
        raise UnexpectedObservation("observation actions are malformed")
    if not isinstance(links, list) or not all(isinstance(i, str) for i in links):
        raise UnexpectedObservation("observation links are malformed")
    if not isinstance(value.get("cartUrl"), str) or not isinstance(
        value.get("checkoutUrl"), str
    ):
        raise UnexpectedObservation("observation declarations are malformed")
    return value


def _blocked(reason: str, product_url: str | None) -> PurchasePath:
    return PurchasePath(
        FALHA,
        reason,
        product_url=product_url,
        gaps=(
            PurchaseGap(CARRINHO_HEADING, "TOOL_BLOCKED", reason),
            PurchaseGap(CHECKOUT_HEADING, "TOOL_BLOCKED", reason),
        ),
    )


def _absent(reason: str, product_url: str | None) -> PurchasePath:
    return PurchasePath(
        INCONCLUSIVO,
        reason,
        product_url=product_url,
        gaps=(
            PurchaseGap(CARRINHO_HEADING, "INCONCLUSIVO", reason),
            PurchaseGap(CHECKOUT_HEADING, "INCONCLUSIVO", reason),
        ),
    )


def classify_purchase_path(
    capture_origin: str,
    pages: tuple[Pagina, ...],
    *,
    config: PurchasePathConfig | None = None,
) -> PurchasePath:
    """Observe the visible purchase action of the confirmed published product.

    The product page, the declared cart and the declared checkout are each
    rendered with GET navigation only; every request that could change a cart,
    place an order or pay is aborted by ``read_only_purchase_route``. Anything
    that fails for a technical reason -- including an unexpected error -- is
    TOOL_BLOCKED; it never becomes INCONCLUSIVO.
    """
    settings = PurchasePathConfig() if config is None else config
    product = next((page for page in pages if page.tipo == PRODUTO_PUBLICADO), None)
    product_url = product.url if product is not None else None
    parsed = urlsplit(capture_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _blocked("Capture Origin inválida para observar a loja", product_url)
    try:
        return _observe(capture_origin, product, parsed.netloc.casefold(), settings)
    except PlaywrightError as error:
        return _blocked(
            f"navegador indisponível ao observar o caminho de compra ({type(error).__name__})",
            product_url,
        )
    except Exception as error:
        events.notice(
            "purchase_path_failed",
            severity="warning",
            error=type(error).__name__,
        )
        return _blocked(
            f"erro inesperado ao observar o caminho de compra ({type(error).__name__})",
            product_url,
        )


def _observe(
    capture_origin: str,
    product: Pagina | None,
    expected_host: str,
    settings: PurchasePathConfig,
) -> PurchasePath:
    product_url = product.url if product is not None else None
    with browser_context(
        viewport={"width": 1600, "height": 900},
        device_scale_factor=1,
        extra_http_headers=NO_CACHE_HEADERS,
    ) as context:
        context.route("**/*", read_only_purchase_route)
        page = context.new_page()
        inspected = capture_origin if product is None else product.url
        subject = "página inicial" if product is None else "página do produto"
        # A product page that answers 4xx is absent, not broken: its purchase
        # action cannot be read, but the store's own cart and checkout
        # declarations can still be read from the home page.
        product_absence: str | None = None
        try:
            status = _open(page, inspected, settings)
        except PlaywrightError as error:
            return _blocked(
                f"a navegação até a {subject} falhou ({type(error).__name__})",
                product_url,
            )
        if _technical(status):
            return _blocked(f"a {subject} respondeu {_status_text(status)}", product_url)
        if status is not None and status >= 400:
            if product is None:
                return _absent(f"a página inicial respondeu HTTP {status}", None)
            product_absence = f"a página do produto respondeu HTTP {status}"
            inspected = capture_origin
            try:
                status = _open(page, inspected, settings)
            except PlaywrightError as error:
                return _blocked(
                    f"a navegação até a página inicial falhou ({type(error).__name__})",
                    product_url,
                )
            if _technical(status):
                return _blocked(
                    f"a página inicial respondeu {_status_text(status)}", product_url
                )
            if status is not None and status >= 400:
                return _absent(product_absence, product_url)
        base = _same_origin(inspected, page.url, expected_host)
        if base is None:
            return _absent(f"a {subject} saiu do endereço da loja", product_url)
        page.wait_for_timeout(settings.settle_ms)
        observed = _observation(page.evaluate(_OBSERVE_SCRIPT, settings.max_elements))
        actions = (
            list(observed["actions"])
            if product is not None and product_absence is None
            else []
        )
        links = list(observed["links"])
        whatsapp, external, on_site = _classify_actions(actions, base, expected_host)

        cart_url = _declared(
            str(observed["cartUrl"]), links, _CART_SEGMENTS, base, expected_host
        )
        checkout_url = _declared(
            str(observed["checkoutUrl"]), links, _CHECKOUT_SEGMENTS, base, expected_host
        )
        confirmed: list[Pagina] = []
        gaps: list[PurchaseGap] = []
        confirmed_cart: str | None = None
        if cart_url is None:
            gaps.append(
                PurchaseGap(
                    CARRINHO_HEADING,
                    "INCONCLUSIVO",
                    "a loja não declara publicamente o endereço do carrinho",
                )
            )
        else:
            confirmed_cart, gap = _verify(
                page,
                cart_url,
                name="carrinho",
                markup=_CART_MARKUP,
                expected_host=expected_host,
                cart_url=None,
                settings=settings,
            )
            if confirmed_cart is not None:
                confirmed.append(
                    Pagina(CARRINHO_PUBLICO, "Carrinho", confirmed_cart, CARRINHO_HEADING)
                )
            elif gap is not None:
                gaps.append(gap)
        if checkout_url is None:
            gaps.append(
                PurchaseGap(
                    CHECKOUT_HEADING,
                    "INCONCLUSIVO",
                    "a loja não declara publicamente o endereço do checkout",
                )
            )
        else:
            confirmed_checkout, gap = _verify(
                page,
                checkout_url,
                name="checkout",
                markup=_CHECKOUT_MARKUP,
                expected_host=expected_host,
                cart_url=confirmed_cart,
                settings=settings,
            )
            if confirmed_checkout is not None:
                confirmed.append(
                    Pagina(CHECKOUT_PUBLICO, "Checkout", confirmed_checkout, CHECKOUT_HEADING)
                )
            elif gap is not None:
                gaps.append(gap)

    if on_site and confirmed_cart is not None:
        classification, action, reason = (
            ROTA_NO_SITE,
            on_site[0],
            "a ação de compra pertence ao carrinho do próprio site, cuja página "
            "pública foi verificada",
        )
    elif whatsapp:
        classification, action, reason = (
            INDICACAO_WHATSAPP,
            whatsapp[0],
            "a ação de compra direciona a uma conversa no WhatsApp",
        )
    elif external:
        classification, action, reason = (
            INDICACAO_EXTERNA,
            external[0],
            "a ação de compra direciona a um endereço fora do site",
        )
    elif product_absence is not None:
        classification, action, reason = (INCONCLUSIVO, None, product_absence)
    elif on_site and (
        cart_gap := next(
            (
                gap
                for gap in gaps
                if gap.heading == CARRINHO_HEADING
                and gap.classification == "TOOL_BLOCKED"
            ),
            None,
        )
    ):
        # The action is visible but the cart that would settle it failed to
        # load: the answer was blocked, so it is not merely inconclusive.
        classification, action, reason = (
            FALHA,
            None,
            f"a verificação do carrinho falhou: {cart_gap.reason}",
        )
    elif on_site:
        classification, action, reason = (
            INCONCLUSIVO,
            None,
            "a ação de adicionar ao carrinho está visível, mas a página pública "
            "do carrinho não foi verificada",
        )
    elif product is None:
        classification, action, reason = (
            INCONCLUSIVO,
            None,
            "nenhum produto publicado foi confirmado na vitrine pública",
        )
    else:
        classification, action, reason = (
            INCONCLUSIVO,
            None,
            "a página do produto não apresenta uma ação de compra visível e verificável",
        )
    return PurchasePath(
        classification,
        reason,
        product_url=product_url,
        action=action,
        pages=tuple(confirmed),
        gaps=tuple(gaps),
    )


def with_purchase_pages(
    pages: tuple[Pagina, ...], path: PurchasePath
) -> tuple[Pagina, ...]:
    """Place confirmed cart and checkout views before Cabeçalho and Rodapé."""
    if not path.pages:
        return pages
    split = next(
        (
            index
            for index, page in enumerate(pages)
            if page.tipo == ELEMENTO_TRANSVERSAL
        ),
        len(pages),
    )
    return (*pages[:split], *path.pages, *pages[split:])


@dataclass(frozen=True)
class PurchaseStatement:
    """What the report says about the purchase path, and its evidence."""

    text: str
    is_gap: bool
    pendencia: Pendencia | None = None
    grounding: Grounding | None = None


def describe_purchase_path(
    path: PurchasePath | None, capture_origin: str
) -> PurchaseStatement:
    """Return the fixed sentence for one observed path, and nothing more.

    Each sentence states the visible label and where the action points, which
    is all a read-only observation shows. None says what happens after the
    visitor presses it: no sale, payment, shipping, stock or security claim.
    """
    if path is None:
        path = PurchasePath(
            INCONCLUSIVO, "o caminho de compra não foi observado nesta geração"
        )
    if path.action is not None and path.classification in {
        INDICACAO_WHATSAPP,
        INDICACAO_EXTERNA,
        ROTA_NO_SITE,
    }:
        label = path.action.label
        if path.classification == INDICACAO_WHATSAPP:
            text = (
                f"Na página pública do produto, a ação “{label}” direciona o "
                "visitante a uma conversa no WhatsApp, fora do site. Este "
                "relatório não observa o que ocorre após esse direcionamento "
                "nem registra transações."
            )
        elif path.classification == INDICACAO_EXTERNA:
            text = (
                f"Na página pública do produto, a ação “{label}” direciona o "
                "visitante a um endereço fora do site. Este relatório não "
                "observa o que ocorre após esse direcionamento nem registra "
                "transações."
            )
        else:
            text = (
                f"Na página pública do produto, a ação “{label}” pertence ao "
                "carrinho do próprio site, cuja página pública foi aberta sem "
                "inclusão de itens. Este relatório não aciona essa ação e não "
                "registra pedidos, pagamentos ou transações."
            )
        return PurchaseStatement(
            text,
            False,
            grounding=Grounding(
                field=SLOT,
                capture_origin=capture_origin,
                excerpt=(
                    f"{path.product_url} | {label} -> {path.action.destination}"
                ),
            ),
        )
    classification = "TOOL_BLOCKED" if path.classification == FALHA else "INCONCLUSIVO"
    marker = pendencia_marker(classification, "caminho de compra")
    return PurchaseStatement(
        marker,
        True,
        pendencia=Pendencia(
            slot=SLOT,
            classification=classification,
            reason=path.reason,
            evidence=marker,
            name="caminho de compra",
            page=SECTION,
            required_action=(
                "Investigar a automação e refazer a geração"
                if classification == "TOOL_BLOCKED"
                else "Confirmar na loja pública como o visitante conclui a "
                "compra e revisar no Word"
            ),
        ),
    )


__all__ = [
    "CARRINHO_HEADING",
    "CHECKOUT_HEADING",
    "FALHA",
    "INCONCLUSIVO",
    "INDICACAO_EXTERNA",
    "INDICACAO_WHATSAPP",
    "PurchaseAction",
    "PurchaseGap",
    "PurchasePath",
    "PurchasePathConfig",
    "PurchaseStatement",
    "ROTA_NO_SITE",
    "UnexpectedObservation",
    "classify_purchase_path",
    "describe_purchase_path",
    "with_purchase_pages",
]
