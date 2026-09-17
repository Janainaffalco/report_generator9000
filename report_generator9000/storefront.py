"""Discover a bounded, public, read-only Loja Virtual storefront."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError, Page, Route

from . import events
from .browser_session import browser_context
from .capture import NO_CACHE_HEADERS
from .lista_paginas import (
    CATEGORIA_PRODUTO,
    ELEMENTO_TRANSVERSAL,
    FILTRO_PRODUTO,
    PRODUTO_PUBLICADO,
    VISAO_MOBILE,
    VITRINE,
    Pagina,
)
from .prose import ProseConfig


@dataclass(frozen=True)
class StorefrontDiscoveryConfig:
    """Finite budgets for one storefront discovery pass."""

    max_rendered_links: int = 120
    max_store_api_products: int = 10
    max_candidates: int = 24
    max_confirmations: int = 10
    max_taxonomies: int = 2
    max_provider_candidates: int = 6
    max_provider_confirmations: int = 4
    max_evidence_pages: int = 4
    max_evidence_chars: int = 8_000
    navigation_timeout_ms: int = 20_000
    settle_ms: int = 250

    def __post_init__(self) -> None:
        values = (
            self.max_rendered_links,
            self.max_store_api_products,
            self.max_candidates,
            self.max_confirmations,
            self.max_provider_candidates,
            self.max_provider_confirmations,
            self.max_evidence_pages,
            self.max_evidence_chars,
            self.navigation_timeout_ms,
        )
        if any(value <= 0 for value in values) or self.max_taxonomies < 0:
            raise ValueError("storefront discovery budgets must be positive")


@dataclass(frozen=True)
class StorefrontEvidencePage:
    """One bounded rendered public page shown to the discovery provider."""

    source_id: str
    url: str
    text: str


@dataclass(frozen=True)
class StorefrontDiscoveryRequest:
    """The complete public-evidence surface available to the provider."""

    pages: tuple[StorefrontEvidencePage, ...]


@dataclass(frozen=True)
class StorefrontProviderCandidate:
    """A provider suggestion that still requires deterministic validation."""

    kind: str
    label: str
    url: str
    source_id: str
    excerpt: str


@dataclass(frozen=True)
class StorefrontDiscoveryResponse:
    candidates: tuple[StorefrontProviderCandidate, ...]
    output_budget_exhausted: bool = False


class StorefrontDiscoveryProvider(Protocol):
    def discover_storefront(
        self,
        request: StorefrontDiscoveryRequest,
        config: ProseConfig,
    ) -> StorefrontDiscoveryResponse: ...


@dataclass(frozen=True)
class _Candidate:
    kind: str
    label: str
    url: str
    source: str


_LISTING_SEGMENTS = frozenset(
    {"shop", "loja", "products", "produtos", "catalog", "catalogo"}
)
_PRODUCT_SEGMENTS = frozenset({"product", "produto"})
_CATEGORY_SEGMENTS = frozenset(
    {"product-category", "categoria-produto", "categoria-de-produto"}
)
_FORBIDDEN_SEGMENTS = frozenset(
    {
        "cart",
        "carrinho",
        "checkout",
        "finalizar-compra",
        "my-account",
        "minha-conta",
        "order",
        "pedido",
        "payment",
        "pagamento",
        "wp-admin",
        "wp-login.php",
    }
)
_FORBIDDEN_QUERY_KEYS = frozenset(
    {
        "add-to-cart",
        "add_to_cart",
        "cart",
        "checkout",
        "remove_item",
        "wc-ajax",
        "order",
        "order-pay",
        "payment",
        "pay_for_order",
    }
)
_SPACE = re.compile(r"\s+")


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    ).casefold()


def _canonical(base: str, candidate: str, expected_host: str) -> str | None:
    parsed = urlsplit(urljoin(base, candidate.strip()))
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.casefold() != expected_host
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    path = parsed.path or "/"
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, "")
    )


def _segments(url: str) -> tuple[str, ...]:
    return tuple(
        segment for segment in _fold(urlsplit(url).path).split("/") if segment
    )


def _is_forbidden(url: str) -> bool:
    if _FORBIDDEN_SEGMENTS.intersection(_segments(url)):
        return True
    keys = {_fold(key) for key, _value in parse_qsl(urlsplit(url).query)}
    return bool(keys & _FORBIDDEN_QUERY_KEYS)


def _link_kind(url: str, label: str, descriptor: str) -> str | None:
    segments = set(_segments(url))
    query_keys = {_fold(key) for key, _value in parse_qsl(urlsplit(url).query)}
    hint = _fold(f"{label} {descriptor}")
    if segments & _CATEGORY_SEGMENTS or "product-category" in hint:
        return CATEGORIA_PRODUTO
    if any(key.startswith("filter_") for key in query_keys) or any(
        marker in hint for marker in ("product-filter", "filtro-produto")
    ):
        return FILTRO_PRODUTO
    if segments & _PRODUCT_SEGMENTS or any(
        marker in hint
        for marker in ("type-product", "product-card", "wc-block-grid__product")
    ):
        return PRODUTO_PUBLICADO
    if segments & _LISTING_SEGMENTS or any(
        marker in hint for marker in ("shop", "loja", "catalogo", "catálogo")
    ):
        return VITRINE
    return None


def _rendered_links(page: Page, limit: int) -> list[dict[str, str]]:
    return page.locator("a[href]").evaluate_all(
        """(nodes, limit) => nodes.slice(0, limit).filter((node) => {
          const box = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          return box.width > 0 && box.height > 0 && style.visibility !== 'hidden'
            && style.display !== 'none';
        }).map((node) => ({
          href: node.href,
          label: (node.innerText || node.getAttribute('aria-label') || '').trim(),
          descriptor: [
            node.className,
            node.getAttribute('rel'),
            node.parentElement?.className
          ]
            .filter(Boolean).join(' ')
        }))""",
        limit,
    )


def _provider_evidence(
    page: Page,
    page_url: str,
    links: list[dict[str, str]],
    expected_host: str,
    max_chars: int,
    source_id: str = "public-page-1",
) -> StorefrontEvidencePage:
    body = page.locator("body")
    visible_text = body.inner_text().strip() if body.count() else ""
    link_lines: list[str] = []
    for item in links:
        url = _canonical(page_url, item.get("href", ""), expected_host)
        label = _clean_label(item.get("label", ""), "Link")
        if url is not None and not _is_forbidden(url):
            link_lines.append(f"{label} | {url}")
    evidence = "\n".join((visible_text, *link_lines))[:max_chars]
    return StorefrontEvidencePage(source_id, page_url, evidence)


def _provider_evidence_pages(
    page: Page,
    home: str,
    expected_host: str,
    settings: StorefrontDiscoveryConfig,
) -> tuple[StorefrontEvidencePage, ...]:
    try:
        response = page.goto(
            home,
            wait_until="domcontentloaded",
            timeout=settings.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            return ()
        page.wait_for_timeout(settings.settle_ms)
        home_links = _rendered_links(page, settings.max_rendered_links)
    except PlaywrightError:
        return ()
    pages = [
        _provider_evidence(
            page,
            home,
            home_links,
            expected_host,
            settings.max_evidence_chars,
        )
    ]
    seen = {home}
    for item in home_links:
        if len(pages) >= settings.max_evidence_pages:
            break
        candidate = _canonical(home, item.get("href", ""), expected_host)
        if candidate is None or candidate in seen or _is_forbidden(candidate):
            continue
        seen.add(candidate)
        try:
            response = page.goto(
                candidate,
                wait_until="domcontentloaded",
                timeout=settings.navigation_timeout_ms,
            )
            if response is not None and response.status >= 400:
                continue
            page.wait_for_timeout(settings.settle_ms)
            final = _canonical(candidate, page.url, expected_host)
            body = page.locator("body")
            if (
                final is None
                or not body.count()
                or not body.is_visible()
                or len(body.inner_text().strip()) < 20
            ):
                continue
            links = _rendered_links(page, settings.max_rendered_links)
            pages.append(
                _provider_evidence(
                    page,
                    final,
                    links,
                    expected_host,
                    settings.max_evidence_chars,
                    source_id=f"public-page-{len(pages) + 1}",
                )
            )
        except PlaywrightError:
            continue
    return tuple(pages)


def _validated_provider_candidates(
    response: StorefrontDiscoveryResponse,
    request: StorefrontDiscoveryRequest,
    origin: str,
    expected_host: str,
    limit: int,
) -> list[_Candidate] | None:
    if response.output_budget_exhausted or len(response.candidates) > limit:
        return None
    sources = {page.source_id: page.text for page in request.pages}
    seen_urls: dict[str, str] = {}
    validated: list[_Candidate] = []
    allowed = {VITRINE, PRODUTO_PUBLICADO, CATEGORIA_PRODUTO, FILTRO_PRODUTO}
    for candidate in response.candidates:
        url = _canonical(origin, candidate.url, expected_host)
        source = sources.get(candidate.source_id)
        if (
            candidate.kind not in allowed
            or not candidate.label.strip()
            or candidate.label.strip() not in candidate.excerpt
            or url is None
            or _is_forbidden(url)
            or source is None
            or not candidate.excerpt.strip()
            or candidate.excerpt not in source
            or url not in candidate.excerpt
        ):
            return None
        previous_kind = seen_urls.get(url)
        if previous_kind is not None and previous_kind != candidate.kind:
            return None
        seen_urls[url] = candidate.kind
        validated.append(
            _Candidate(candidate.kind, candidate.label, url, "gemini")
        )
    return validated


def _store_api_candidates(
    page: Page,
    origin: str,
    expected_host: str,
    limit: int,
    timeout_ms: int,
) -> list[_Candidate]:
    endpoint = urljoin(origin, f"/wp-json/wc/store/v1/products?per_page={limit}")
    try:
        response = page.request.get(endpoint, timeout=timeout_ms)
        if not response.ok:
            return []
        final = _canonical(origin, response.url, expected_host)
        if final is None:
            return []
        payload = response.json()
    except (PlaywrightError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    candidates: list[_Candidate] = []
    for item in payload[:limit]:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in {None, "publish"}:
            continue
        permalink = item.get("permalink")
        name = item.get("name")
        if not isinstance(permalink, str) or not isinstance(name, str):
            continue
        url = _canonical(origin, permalink, expected_host)
        if url is None or _is_forbidden(url):
            continue
        candidates.append(_Candidate(PRODUTO_PUBLICADO, name, url, "store-api"))
    return candidates


def _clean_label(label: str, fallback: str) -> str:
    cleaned = _SPACE.sub(" ", label).strip(" -–—|\t\r\n")
    return cleaned[:80] or fallback


def _title(candidate: _Candidate) -> str:
    label = _clean_label(candidate.label, "PRODUTO")
    if candidate.kind == VITRINE:
        return "SEÇÃO PRODUTOS"
    if candidate.kind == PRODUTO_PUBLICADO:
        return f"PRODUTO {label.upper()}"
    if candidate.kind == CATEGORIA_PRODUTO:
        return f"CATEGORIA {label.upper()}"
    return f"FILTRO {label.upper()}"


def _rendered_candidate(
    page: Page,
    candidate: _Candidate,
    config: StorefrontDiscoveryConfig,
) -> str | None:
    try:
        response = page.goto(
            candidate.url,
            wait_until="domcontentloaded",
            timeout=config.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            return None
        page.wait_for_timeout(config.settle_ms)
        final = _canonical(
            candidate.url,
            page.url,
            urlsplit(candidate.url).netloc.casefold(),
        )
        if final is None or _is_forbidden(final):
            return None
        body = page.locator("body")
        if not body.count() or not body.is_visible():
            return None
        if len(body.inner_text().strip()) < 20:
            return None
        return final
    except PlaywrightError:
        return None


def _provider_semantics_confirmed(
    page: Page,
    candidate: _Candidate,
    final_url: str,
    confirmed_product_urls: set[str],
) -> bool:
    """Confirm Gemini's page type from rendered public facts."""
    if candidate.kind == PRODUTO_PUBLICADO:
        return page.locator(
            "body.single-product, "
            "meta[property='og:type'][content='product']"
        ).count() > 0
    if candidate.kind in {VITRINE, CATEGORIA_PRODUTO, FILTRO_PRODUTO}:
        if not confirmed_product_urls:
            return False
        expected_host = urlsplit(final_url).netloc.casefold()
        for item in _rendered_links(page, 120):
            url = _canonical(final_url, item.get("href", ""), expected_host)
            if url in confirmed_product_urls:
                return True
        return False
    return False


def _dedupe(candidates: list[_Candidate], limit: int) -> list[_Candidate]:
    seen: set[tuple[str, str]] = set()
    result: list[_Candidate] = []
    for candidate in candidates:
        key = (candidate.kind, candidate.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def _read_only(route: Route) -> None:
    """Abort mutation-shaped background traffic during discovery."""
    request = route.request
    if request.method not in {"GET", "HEAD", "OPTIONS"} or _is_forbidden(
        request.url
    ):
        route.abort()
        return
    route.continue_()


def discover_storefront_pages(
    capture_origin: str,
    existing_pages: tuple[Pagina, ...],
    *,
    config: StorefrontDiscoveryConfig | None = None,
    provider: StorefrontDiscoveryProvider | None = None,
    provider_config: ProseConfig | None = None,
) -> tuple[Pagina, ...]:
    """Return one ordered Lista enriched with confirmed public storefront views.

    Discovery performs bounded GET/navigation work only. Missing optional signals
    return the original Lista; they never fabricate a Block or stop the Run.
    """
    settings = StorefrontDiscoveryConfig() if config is None else config
    parsed_origin = urlsplit(capture_origin)
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc:
        return existing_pages
    expected_host = parsed_origin.netloc.casefold()
    candidates: list[_Candidate] = []
    confirmed: list[Pagina] = []
    provider_request: StorefrontDiscoveryRequest | None = None

    try:
        with browser_context(
            viewport={"width": 1600, "height": 900},
            device_scale_factor=1,
            extra_http_headers=NO_CACHE_HEADERS,
        ) as context:
            context.route("**/*", _read_only)
            page = context.new_page()
            response = page.goto(
                capture_origin,
                wait_until="domcontentloaded",
                timeout=settings.navigation_timeout_ms,
            )
            if response is not None and response.status >= 400:
                return existing_pages
            home = _canonical(capture_origin, page.url, expected_host)
            if home is None:
                return existing_pages
            page.wait_for_timeout(settings.settle_ms)
            links = _rendered_links(page, settings.max_rendered_links)
            product_links = 0
            for item in links:
                url = _canonical(home, item.get("href", ""), expected_host)
                if url is None or _is_forbidden(url):
                    continue
                kind = _link_kind(
                    url,
                    item.get("label", ""),
                    item.get("descriptor", ""),
                )
                if kind is None:
                    continue
                if kind == PRODUTO_PUBLICADO:
                    product_links += 1
                candidates.append(
                    _Candidate(
                        kind,
                        item.get("label", ""),
                        url,
                        "rendered-link",
                    )
                )
            if product_links:
                candidates.append(
                    _Candidate(VITRINE, "Produtos", home, "rendered-grid")
                )
            candidates.extend(
                _store_api_candidates(
                    page,
                    home,
                    expected_host,
                    settings.max_store_api_products,
                    settings.navigation_timeout_ms,
                )
            )
            for existing in existing_pages:
                kind = _link_kind(
                    existing.url,
                    existing.rotulo,
                    existing.titulo_bloco,
                )
                if kind is not None and not _is_forbidden(existing.url):
                    candidates.insert(
                        0,
                        _Candidate(
                            kind,
                            existing.rotulo,
                            existing.url,
                            "lista",
                        ),
                    )

            chosen_kinds: set[str] = set()
            chosen_titles: set[str] = set()
            taxonomy_count = 0
            confirmations = 0
            for candidate in _dedupe(candidates, settings.max_candidates):
                if confirmations >= settings.max_confirmations:
                    break
                if (
                    candidate.kind in {VITRINE, PRODUTO_PUBLICADO}
                    and candidate.kind in chosen_kinds
                ):
                    continue
                if (
                    candidate.kind in {CATEGORIA_PRODUTO, FILTRO_PRODUTO}
                    and taxonomy_count >= settings.max_taxonomies
                ):
                    continue
                confirmations += 1
                final = _rendered_candidate(page, candidate, settings)
                if final is None:
                    continue
                title = _title(candidate)
                if title in chosen_titles:
                    continue
                confirmed.append(
                    Pagina(
                        candidate.kind,
                        _clean_label(candidate.label, "Produto"),
                        final,
                        title,
                    )
                )
                chosen_kinds.add(candidate.kind)
                chosen_titles.add(title)
                if candidate.kind in {CATEGORIA_PRODUTO, FILTRO_PRODUTO}:
                    taxonomy_count += 1

            deterministic_sufficient = {VITRINE, PRODUTO_PUBLICADO}.issubset(
                chosen_kinds
            )
            discover = getattr(provider, "discover_storefront", None)
            if (
                not deterministic_sufficient
                and callable(discover)
                and provider_config is not None
            ):
                provider_request = StorefrontDiscoveryRequest(
                    _provider_evidence_pages(
                        page,
                        home,
                        expected_host,
                        settings,
                    )
                )
                if not provider_request.pages:
                    provider_candidates = None
                else:
                    try:
                        response = discover(provider_request, provider_config)
                        provider_candidates = _validated_provider_candidates(
                            response,
                            provider_request,
                            home,
                            expected_host,
                            settings.max_provider_candidates,
                        )
                    except Exception as error:
                        events.notice(
                            "storefront_provider_failed",
                            severity="warning",
                            error=type(error).__name__,
                        )
                        provider_candidates = None
                if provider_candidates is None:
                    events.notice(
                        "storefront_provider_rejected",
                        severity="warning",
                    )
                else:
                    provider_confirmations = 0
                    provider_confirmed: list[Pagina] = []
                    confirmed_product_urls = {
                        item.url
                        for item in confirmed
                        if item.tipo == PRODUTO_PUBLICADO
                    }
                    provider_candidates = sorted(
                        _dedupe(
                            provider_candidates,
                            settings.max_provider_candidates,
                        ),
                        key=lambda item: (
                            item.kind != PRODUTO_PUBLICADO,
                            item.kind != VITRINE,
                        ),
                    )
                    for candidate in provider_candidates:
                        if (
                            provider_confirmations
                            >= settings.max_provider_confirmations
                        ):
                            break
                        if (
                            candidate.kind in {VITRINE, PRODUTO_PUBLICADO}
                            and candidate.kind in chosen_kinds
                        ):
                            continue
                        if (
                            candidate.kind
                            in {CATEGORIA_PRODUTO, FILTRO_PRODUTO}
                            and taxonomy_count >= settings.max_taxonomies
                        ):
                            continue
                        provider_confirmations += 1
                        final = _rendered_candidate(page, candidate, settings)
                        if final is None or not _provider_semantics_confirmed(
                            page,
                            candidate,
                            final,
                            confirmed_product_urls,
                        ):
                            continue
                        title = _title(candidate)
                        if title in chosen_titles:
                            continue
                        provider_confirmed.append(
                            Pagina(
                                candidate.kind,
                                _clean_label(candidate.label, "Produto"),
                                final,
                                title,
                            )
                        )
                        chosen_kinds.add(candidate.kind)
                        chosen_titles.add(title)
                        if candidate.kind == PRODUTO_PUBLICADO:
                            confirmed_product_urls.add(final)
                        if candidate.kind in {
                            CATEGORIA_PRODUTO,
                            FILTRO_PRODUTO,
                        }:
                            taxonomy_count += 1
                    provider_order = {
                        VITRINE: 0,
                        PRODUTO_PUBLICADO: 1,
                        CATEGORIA_PRODUTO: 2,
                        FILTRO_PRODUTO: 3,
                    }
                    confirmed.extend(
                        sorted(
                            provider_confirmed,
                            key=lambda item: provider_order[item.tipo],
                        )
                    )
    except PlaywrightError:
        return existing_pages

    listing = next((item for item in confirmed if item.tipo == VITRINE), None)
    if listing is not None:
        confirmed.append(
            Pagina(
                VISAO_MOBILE,
                "Vitrine mobile",
                listing.url,
                "VITRINE MOBILE",
                visualizacao="mobile",
            )
        )

    selected_urls = {item.url for item in confirmed}
    transversals = [
        item for item in existing_pages if item.tipo == ELEMENTO_TRANSVERSAL
    ]
    base = [
        item
        for item in existing_pages
        if item.tipo != ELEMENTO_TRANSVERSAL
        and (
            item.titulo_bloco == "PÁGINA HOME"
            or item.url not in selected_urls
        )
        and item.titulo_bloco != "SEÇÃO PRODUTOS"
    ]
    home_pages = [item for item in base if item.titulo_bloco == "PÁGINA HOME"]
    other_pages = [item for item in base if item.titulo_bloco != "PÁGINA HOME"]
    return tuple([*home_pages, *confirmed, *other_pages, *transversals])


__all__ = [
    "StorefrontDiscoveryConfig",
    "StorefrontDiscoveryRequest",
    "StorefrontDiscoveryResponse",
    "StorefrontEvidencePage",
    "StorefrontProviderCandidate",
    "discover_storefront_pages",
]
