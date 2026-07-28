from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from report_generator9000.control_sheet import Engagement
from report_generator9000.gated_inputs import (
    GatedInputError,
    load_gated_inputs,
)
from report_generator9000.lista_paginas import (
    AREA_LEGAL,
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    DeclaredPage,
    derive_lista_paginas,
)

FIXTURE_SITE = Path(__file__).parent / "fixtures" / "site"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve_fixture_site() -> Iterator[str]:
    handler = lambda *args, **kwargs: _QuietHandler(
        *args, directory=str(FIXTURE_SITE), **kwargs
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


def test_local_http_fixture_derives_all_three_sources_deterministically() -> None:
    with serve_fixture_site() as origin:
        pages = derive_lista_paginas(origin)

    assert [page.tipo for page in pages] == [
        PAGINA_PRINCIPAL,
        PAGINA_PRINCIPAL,
        PAGINA_PRINCIPAL,
        AREA_LEGAL,
        AREA_LEGAL,
        ELEMENTO_TRANSVERSAL,
        ELEMENTO_TRANSVERSAL,
    ]
    assert [page.titulo_bloco for page in pages] == [
        "PÁGINA HOME",
        "SEÇÃO SERVIÇOS",
        "SEÇÃO CONTATO",
        "POLÍTICA DE PRIVACIDADE",
        "POLÍTICA DE COOKIES",
        "CABEÇALHO",
        "RODAPÉ",
    ]
    assert all("portal.example.test" not in page.url for page in pages)
    assert all("instagram.com" not in page.url for page in pages)
    assert all("AGÊNCIA" not in page.titulo_bloco for page in pages)
    assert [page.titulo_bloco for page in pages].count("SEÇÃO SERVIÇOS") == 1
    assert pages[-2].entra_no_briefing is False
    assert pages[-1].entra_no_briefing is False
    assert all(page.entra_no_briefing for page in pages[:-2])


def test_declared_list_wins_without_contacting_the_capture_origin() -> None:
    declared = (
        DeclaredPage(PAGINA_PRINCIPAL, "Home", "/"),
        DeclaredPage(PAGINA_PRINCIPAL, "Portfólio", "/portfolio/"),
        DeclaredPage(AREA_LEGAL, "Termos de Uso", "/termos/"),
    )

    pages = derive_lista_paginas(
        "http://127.0.0.1:1/",
        declared,
        timeout=0.01,
    )

    assert [page.titulo_bloco for page in pages] == [
        "PÁGINA HOME",
        "SEÇÃO PORTFÓLIO",
        "TERMOS DE USO",
        "CABEÇALHO",
        "RODAPÉ",
    ]


def test_declared_list_cannot_smuggle_in_an_off_host_page() -> None:
    with pytest.raises(ValueError, match="not on the Capture Origin host"):
        derive_lista_paginas(
            "https://cliente.example/",
            (
                DeclaredPage(
                    PAGINA_PRINCIPAL,
                    "Portal",
                    "https://portal.cliente.example/",
                ),
            ),
        )


def _engagement() -> Engagement:
    from datetime import datetime

    return Engagement(
        row_number=2,
        demanda="011616/2026",
        pasta="40-2026",
        razao_social="CLIENTE",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin="https://cliente.example/",
        published_domain=None,
    )


def test_gated_values_load_the_declared_lista_paginas(tmp_path: Path) -> None:
    folder = tmp_path / "40-2026_CLIENTE"
    folder.mkdir()
    (folder / "valores.json").write_text(
        json.dumps(
            {
                "pasta": "40-2026",
                "razao_social": "CLIENTE",
                "lista_paginas": [
                    {
                        "tipo": "pagina_principal",
                        "rotulo": "Home",
                        "url": "/",
                    },
                    {
                        "tipo": "area_legal",
                        "rotulo": "Privacidade",
                        "url": "/privacidade/",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_gated_inputs(tmp_path, _engagement())

    assert loaded.declared_pages == (
        DeclaredPage(PAGINA_PRINCIPAL, "Home", "/"),
        DeclaredPage(AREA_LEGAL, "Privacidade", "/privacidade/"),
    )


def test_malformed_declared_lista_paginas_is_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "40-2026_CLIENTE"
    folder.mkdir()
    (folder / "valores.json").write_text(
        json.dumps(
            {
                "pasta": "40-2026",
                "razao_social": "CLIENTE",
                "lista_paginas": [
                    {
                        "tipo": "elemento_transversal",
                        "rotulo": "Cabeçalho",
                        "url": "/",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GatedInputError, match="pagina_principal or area_legal"):
        load_gated_inputs(tmp_path, _engagement())
