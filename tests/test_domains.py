from __future__ import annotations

import pytest

from report_generator9000.domains import (
    derive_published_domain,
    domain_of,
    is_provisional_domain,
)


# Every provisional host below is the shape the control spreadsheet actually
# carries: Hostinger hands out `<colour>-<animal>-<digits>.hostingersite.com`
# while the client's own domain is still being pointed at the site.
@pytest.mark.parametrize(
    "domain",
    (
        "teal-duck-363012.hostingersite.com",
        "lightpink-wolverine-396545.hostingersite.com",
        "cliente.hostinger.site",
        "cliente.wpcomstaging.com",
        "cliente.temp.domains",
    ),
)
def test_provider_preview_hosts_are_provisional(domain: str) -> None:
    assert is_provisional_domain(domain)


@pytest.mark.parametrize(
    "domain",
    (
        "sanfrio.com.br",
        "emporionaturelo.com.br",
        "argelresistencia.com.br",
        "nothostingersite.com",
        "hostingersite.com.br",
    ),
)
def test_a_client_owned_domain_is_not_provisional(domain: str) -> None:
    assert not is_provisional_domain(domain)


def test_the_capture_origin_supplies_the_domain_when_nothing_declares_one() -> None:
    derived = derive_published_domain(
        "https://teal-duck-363012.hostingersite.com/"
    )

    assert derived is not None
    assert derived.domain == "teal-duck-363012.hostingersite.com"
    assert derived.provisional
    assert derived.display == (
        "teal-duck-363012.hostingersite.com [DOMÍNIO PROVISÓRIO]"
    )
    assert derived.wp_admin_url == (
        "https://teal-duck-363012.hostingersite.com/wp-admin/"
    )


def test_a_declared_final_domain_wins_over_the_preview_host() -> None:
    derived = derive_published_domain(
        "https://midnightblue-jellyfish-121804.hostingersite.com/",
        "sanfrio.com.br",
    )

    assert derived is not None
    assert not derived.provisional
    assert derived.display == "sanfrio.com.br"
    assert derived.wp_admin_url == "https://sanfrio.com.br/wp-admin/"


@pytest.mark.parametrize(
    "capture_origin",
    (
        "http://127.0.0.1:8000/",
        "http://localhost:8000/",
        "https://[::1]/",
        "not a url",
        "",
    ),
)
def test_an_address_or_single_label_host_stays_a_gated_input(
    capture_origin: str,
) -> None:
    assert domain_of(capture_origin) is None
    assert derive_published_domain(capture_origin) is None


def test_www_and_a_trailing_dot_are_not_part_of_the_domain() -> None:
    derived = derive_published_domain("https://WWW.Cliente.com.br./")

    assert derived is not None
    assert derived.domain == "cliente.com.br"
