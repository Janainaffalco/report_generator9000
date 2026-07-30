"""Decide which domain a report may publish, and whether it is provisional.

Section 2.3's ``Domínio:`` used to be a Gated Input: absent a `valores.json`
entry the report shipped a Pendência marker even though the run had just
captured the live site. The control sheet's Link cell always names the host the
report was built from, and for a site still on its hosting provider's
throwaway preview host that host is honest information the consultant needs --
as long as the document says so out loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit


PROVISIONAL_TAG = "[DOMÍNIO PROVISÓRIO]"

# Preview/staging hosts that hosting providers hand out before a client's own
# domain is pointed at the site. Hostinger's `<colour>-<animal>-<digits>`
# preview host is the one this pipeline meets in the control sheet; the rest
# are the equivalents for the other providers used in this market.
PROVISIONAL_HOST_SUFFIXES = (
    "hostingersite.com",
    "hostinger.site",
    "temp.domains",
    "wpcomstaging.com",
    "instawp.xyz",
    "cloudwaysapps.com",
    "kinsta.cloud",
    "myftpupload.com",
    "wpsandbox.pro",
)


@dataclass(frozen=True)
class PublishedDomain:
    """The domain section 2.3 will state, and how it must be read."""

    domain: str
    provisional: bool

    @property
    def display(self) -> str:
        """The domain as the report states it, tagged when provisional."""
        return (
            f"{self.domain} {PROVISIONAL_TAG}"
            if self.provisional
            else self.domain
        )

    @property
    def wp_admin_url(self) -> str:
        return f"https://{self.domain}/wp-admin/"


def is_provisional_domain(domain: str) -> bool:
    """True when *domain* is a hosting provider's throwaway preview host."""
    host = domain.casefold().strip().rstrip(".")
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in PROVISIONAL_HOST_SUFFIXES
    )


def _is_domain_name(host: str) -> bool:
    """True when *host* is a name a client could own, not an address or label.

    A bare IP or a single-label host (`localhost`, a container name, the
    loopback a test fixture serves from) is never a published domain, so it
    must stay a Gated Input rather than be stated as one.
    """
    if "." not in host:
        return False
    try:
        ip_address(host)
    except ValueError:
        return True
    return False


def domain_of(url: str) -> str | None:
    """Return *url*'s bare domain name, or None when it names none."""
    host = urlsplit(url.strip()).hostname
    if host is None:
        return None
    host = host.casefold().rstrip(".").removeprefix("www.")
    return host if host and _is_domain_name(host) else None


def derive_published_domain(
    capture_origin: str, declared_domain: str | None = None
) -> PublishedDomain | None:
    """Return the domain this run built the report from, or None if it has none.

    A domain the control sheet declares alongside a preview host wins: the
    consultant wrote it there precisely because it is the final one.
    """
    declared = (declared_domain or "").casefold().strip().rstrip(".")
    domain = (
        declared
        if declared and _is_domain_name(declared)
        else domain_of(capture_origin)
    )
    if not domain:
        return None
    return PublishedDomain(
        domain=domain, provisional=is_provisional_domain(domain)
    )


__all__ = [
    "PROVISIONAL_HOST_SUFFIXES",
    "PROVISIONAL_TAG",
    "PublishedDomain",
    "derive_published_domain",
    "domain_of",
    "is_provisional_domain",
]
