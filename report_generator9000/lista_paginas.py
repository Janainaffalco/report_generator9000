"""Derive the ordered Lista de Páginas for one Capture Origin."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

PAGINA_PRINCIPAL = "pagina_principal"
AREA_LEGAL = "area_legal"
ELEMENTO_TRANSVERSAL = "elemento_transversal"
VITRINE = "vitrine"
PRODUTO_PUBLICADO = "produto_publicado"
CATEGORIA_PRODUTO = "categoria_produto"
FILTRO_PRODUTO = "filtro_produto"
VISAO_MOBILE = "visao_mobile"
CARRINHO_PUBLICO = "carrinho_publico"
CHECKOUT_PUBLICO = "checkout_publico"
EVIDENCIA_AUSENTE = "evidencia_ausente"
_DECLARABLE_TYPES = frozenset({PAGINA_PRINCIPAL, AREA_LEGAL})
_SOCIAL_HOSTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "wa.me",
    "whatsapp.com",
)
_ATTRIBUTION_MARKERS = (
    "desenvolvido por",
    "desenvolvimento por",
    "criado por",
    "powered by",
    "site por",
)
_MAIN_NAV_MARKERS = ("main", "principal", "primary")
_LEGAL_AREA_MARKERS = (
    "cookie",
    "dados pessoais",
    "data protection",
    "legal",
    "lgpd",
    "privacidade",
    "privacy",
    "terms",
    "termos",
)


class ListaPaginasError(ValueError):
    """The Capture Origin cannot yield a trustworthy Lista de Páginas."""


@dataclass(frozen=True)
class DeclaredPage:
    """One consultant-controlled page declaration from the Gated Drop Folder."""

    tipo: str
    rotulo: str
    url: str

    def __post_init__(self) -> None:
        if self.tipo not in _DECLARABLE_TYPES:
            raise ValueError(
                "tipo must be pagina_principal or area_legal"
            )
        if not self.rotulo.strip():
            raise ValueError("rotulo must be non-empty")
        if not self.url.strip():
            raise ValueError("url must be non-empty")


@dataclass(frozen=True)
class Pagina:
    """One ordered item that will earn a Block."""

    tipo: str
    rotulo: str
    url: str
    titulo_bloco: str
    visualizacao: str = "desktop"

    def __post_init__(self) -> None:
        if self.visualizacao not in {"desktop", "mobile"}:
            raise ValueError("visualizacao must be desktop or mobile")

    @property
    def entra_no_briefing(self) -> bool:
        # The empty cart and checkout prove only that the page exists; naming
        # them in the Briefing would read as a claim that the store sells there.
        return self.tipo not in {
            ELEMENTO_TRANSVERSAL,
            EVIDENCIA_AUSENTE,
            VISAO_MOBILE,
            CARRINHO_PUBLICO,
            CHECKOUT_PUBLICO,
        }


@dataclass(frozen=True)
class _Link:
    href: str
    label: str
    nav_id: int | None
    in_explicit_main_menu: bool
    in_footer: bool


class _SourceLinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._nav_counter = 0
        self._nav_stack: list[tuple[int, bool]] = []
        self._footer_depth = 0
        self._anchor_href = ""
        self._anchor_text: list[str] | None = None
        self._anchor_nav_id: int | None = None
        self._anchor_in_explicit_main_menu = False
        self._anchor_in_footer = False
        self.links: list[_Link] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "nav":
            self._nav_counter += 1
            descriptor = " ".join(
                value
                for key in ("aria-label", "id", "class")
                if (value := attributes.get(key))
            )
            explicit_main = (
                self._footer_depth == 0
                and any(
                    marker in _fold(descriptor)
                    for marker in _MAIN_NAV_MARKERS
                )
            )
            self._nav_stack.append((self._nav_counter, explicit_main))
        if tag == "footer":
            self._footer_depth += 1
        if tag == "a":
            self._anchor_href = attributes.get("href") or ""
            self._anchor_text = []
            self._anchor_nav_id = (
                self._nav_stack[-1][0]
                if self._nav_stack and self._footer_depth == 0
                else None
            )
            self._anchor_in_explicit_main_menu = bool(
                self._nav_stack
                and self._nav_stack[-1][1]
                and self._footer_depth == 0
            )
            self._anchor_in_footer = self._footer_depth > 0
        elif tag == "img" and self._anchor_text is not None:
            alt = attributes.get("alt")
            if alt:
                self._anchor_text.append(alt)

    def handle_data(self, data: str) -> None:
        if self._anchor_text is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_text is not None:
            label = " ".join("".join(self._anchor_text).split())
            self.links.append(
                _Link(
                    href=self._anchor_href,
                    label=label,
                    nav_id=self._anchor_nav_id,
                    in_explicit_main_menu=(
                        self._anchor_in_explicit_main_menu
                    ),
                    in_footer=self._anchor_in_footer,
                )
            )
            self._anchor_text = None
        if tag == "nav" and self._nav_stack:
            self._nav_stack.pop()
        if tag == "footer" and self._footer_depth:
            self._footer_depth -= 1


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    ).casefold()


def _canonical_url(base: str, href: str, expected_host: str) -> str | None:
    if not href.strip():
        return None
    joined = urlsplit(urljoin(base, href.strip()))
    if joined.scheme not in {"http", "https"}:
        return None
    if joined.netloc.casefold() != expected_host:
        return None
    path = joined.path or "/"
    return urlunsplit(
        (joined.scheme.casefold(), joined.netloc.casefold(), path, joined.query, "")
    )


def _is_social(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    return any(
        hostname == social or hostname.endswith("." + social)
        for social in _SOCIAL_HOSTS
    )


def _is_attribution(label: str) -> bool:
    folded = _fold(label)
    return any(marker in folded for marker in _ATTRIBUTION_MARKERS)


def _is_legal_area(label: str, url: str) -> bool:
    candidate = _fold(f"{label} {urlsplit(url).path}")
    return any(marker in candidate for marker in _LEGAL_AREA_MARKERS)


def _block_title(tipo: str, label: str, url: str, home_url: str) -> str:
    if tipo == PAGINA_PRINCIPAL:
        return (
            "PÁGINA HOME"
            if url == home_url
            else f"SEÇÃO {label.upper()}"
        )
    return label.upper()


def _page(
    tipo: str, label: str, url: str, home_url: str
) -> Pagina:
    return Pagina(
        tipo=tipo,
        rotulo=label,
        url=url,
        titulo_bloco=_block_title(tipo, label, url, home_url),
    )


def _transversals(home_url: str) -> tuple[Pagina, Pagina]:
    return (
        Pagina(
            tipo=ELEMENTO_TRANSVERSAL,
            rotulo="Cabeçalho",
            url=home_url,
            titulo_bloco="CABEÇALHO",
        ),
        Pagina(
            tipo=ELEMENTO_TRANSVERSAL,
            rotulo="Rodapé",
            url=home_url,
            titulo_bloco="RODAPÉ",
        ),
    )


def _from_declared(
    capture_origin: str, declared: tuple[DeclaredPage, ...]
) -> tuple[Pagina, ...]:
    origin = urlsplit(capture_origin)
    if origin.scheme not in {"http", "https"} or not origin.netloc:
        raise ListaPaginasError("Capture Origin is not an HTTP(S) URL")
    home_url = _canonical_url(
        capture_origin, capture_origin, origin.netloc.casefold()
    )
    assert home_url is not None
    pages: list[Pagina] = []
    seen: set[str] = set()
    for position, item in enumerate(declared, start=1):
        url = _canonical_url(capture_origin, item.url, origin.netloc.casefold())
        if url is None:
            raise ListaPaginasError(
                f"declared page {position} is not on the Capture Origin host"
            )
        if url in seen:
            continue
        seen.add(url)
        pages.append(_page(item.tipo, item.rotulo.strip(), url, home_url))
    return (*pages, *_transversals(home_url))


def derive_lista_paginas(
    capture_origin: str,
    declared: tuple[DeclaredPage, ...] | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[Pagina, ...]:
    """Derive all Block-bearing items once, preserving source order."""
    if declared is not None:
        return _from_declared(capture_origin, declared)

    request = Request(
        capture_origin,
        headers={
            "User-Agent": "report-generator9000/0.1",
            # Derive the Lista de Páginas from the live nav, not an
            # intermediary's stored copy -- see `capture.NO_CACHE_HEADERS`.
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            if content_type != "text/html":
                raise ListaPaginasError(
                    f"Capture Origin returned {content_type}, not text/html"
                )
            charset = response.headers.get_content_charset() or "utf-8"
            markup = response.read().decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ListaPaginasError(
            f"could not read Capture Origin: {error}"
        ) from error

    origin = urlsplit(final_url)
    expected_host = origin.netloc.casefold()
    home_url = _canonical_url(final_url, final_url, expected_host)
    assert home_url is not None
    parser = _SourceLinksParser()
    parser.feed(markup)
    main_nav_ids = {
        link.nav_id
        for link in parser.links
        if link.in_explicit_main_menu and link.nav_id is not None
    }
    if not main_nav_ids:
        first_nav_id = next(
            (
                link.nav_id
                for link in parser.links
                if link.nav_id is not None and not link.in_footer
            ),
            None,
        )
        if first_nav_id is not None:
            main_nav_ids.add(first_nav_id)

    pages: list[Pagina] = []
    seen: set[str] = set()
    for source, tipo in (
        ("main", PAGINA_PRINCIPAL),
        ("footer", AREA_LEGAL),
    ):
        for link in parser.links:
            belongs = (
                link.nav_id in main_nav_ids
                if source == "main"
                else link.in_footer
            )
            if not belongs or not link.label:
                continue
            resolved = urljoin(final_url, link.href)
            if _is_social(resolved) or _is_attribution(link.label):
                continue
            url = _canonical_url(final_url, link.href, expected_host)
            if url is None or url in seen:
                continue
            if tipo == AREA_LEGAL and not _is_legal_area(link.label, url):
                continue
            seen.add(url)
            pages.append(_page(tipo, link.label, url, home_url))
    return (*pages, *_transversals(home_url))


__all__ = [
    "AREA_LEGAL",
    "CATEGORIA_PRODUTO",
    "EVIDENCIA_AUSENTE",
    "ELEMENTO_TRANSVERSAL",
    "FILTRO_PRODUTO",
    "PAGINA_PRINCIPAL",
    "PRODUTO_PUBLICADO",
    "VISAO_MOBILE",
    "VITRINE",
    "DeclaredPage",
    "ListaPaginasError",
    "Pagina",
    "derive_lista_paginas",
]
