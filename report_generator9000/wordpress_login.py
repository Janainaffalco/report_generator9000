"""Capture the public WordPress login screen without ever authenticating."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import (
    Error as PlaywrightError,
    Route,
    TimeoutError as PlaywrightTimeoutError,
)

from .browser_session import browser_context
from .capture import NO_CACHE_HEADERS
from .run_context import Artifact

LOGIN_SLOT = "login"
LOGIN_FILENAME = "login.png"
LOGIN_VIEWPORT_WIDTH = 1280
LOGIN_PIXEL_SIZE = (1280, 800)
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class LoginCapture:
    """The public login screen photographed from this run's Capture Origin."""

    path: Path
    digest: str
    final_url: str

    @property
    def artifact(self) -> Artifact:
        return Artifact(
            digest=self.digest,
            origin="capture",
            label=LOGIN_SLOT,
            source=str(self.path.resolve()),
        )


@dataclass(frozen=True)
class LoginCaptureFailure:
    """The login screen could not honestly be captured; the Slot stays GATED."""

    reason: str


def _is_safe_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def wordpress_login_url(capture_origin: str) -> str:
    """Return the `/wp-admin/` entry point on *capture_origin*'s host."""
    if not _is_safe_http_url(capture_origin):
        raise ValueError(
            "Capture Origin must be an HTTP(S) URL without credentials"
        )
    parsed = urlsplit(capture_origin)
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), "/wp-admin/", "", "")
    )


def _same_host(url: str, host: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.netloc.casefold() == host
        and parsed.username is None
        and parsed.password is None
    )


def _read_only(route: Route) -> None:
    """Abort anything but a read: no form, login or AJAX write ever leaves."""
    if route.request.method not in _READ_METHODS:
        route.abort()
        return
    route.continue_()


def _viewport(slot_pixel_size: tuple[int, int]) -> dict[str, int]:
    # Shooting at the Slot's own aspect ratio lets the Master show the page
    # undistorted without resampling or cropping the evidence afterwards.
    width, height = slot_pixel_size
    return {
        "width": LOGIN_VIEWPORT_WIDTH,
        "height": max(1, round(LOGIN_VIEWPORT_WIDTH * height / width)),
    }


def capture_wordpress_login(
    capture_origin: str,
    output_folder: str | Path,
    *,
    slot_pixel_size: tuple[int, int] = LOGIN_PIXEL_SIZE,
) -> LoginCapture | LoginCaptureFailure:
    """Open `/wp-admin/` by GET only and photograph where WordPress lands.

    Nothing is typed, clicked or submitted: an unauthenticated visitor is
    redirected to the login screen (``wp-login.php`` or a custom login URL),
    and that public screen is the evidence. Every hop must stay on the
    Capture Origin's host and the final page must not answer an HTTP error.
    """
    try:
        url = wordpress_login_url(capture_origin)
    except ValueError:
        return LoginCaptureFailure("Capture Origin inválida para a página de login")
    if min(slot_pixel_size) <= 0:
        raise ValueError("login Slot dimensions must be positive")
    host = urlsplit(url).netloc
    folder = Path(output_folder)
    output = folder / LOGIN_FILENAME
    output.unlink(missing_ok=True)
    try:
        with browser_context(
            viewport=_viewport(slot_pixel_size),
            device_scale_factor=1,
            extra_http_headers=NO_CACHE_HEADERS,
        ) as context:
            page = context.new_page()
            page.route("**/*", _read_only)
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            if response is None:
                return LoginCaptureFailure("página de login não respondeu")
            hop = response.request
            while hop is not None:
                if not _same_host(hop.url, host):
                    return LoginCaptureFailure(
                        "página de login deixou o host do Capture Origin"
                    )
                hop = hop.redirected_from
            if not _same_host(page.url, host):
                return LoginCaptureFailure(
                    "página de login deixou o host do Capture Origin"
                )
            if response.status >= 400:
                return LoginCaptureFailure(
                    f"página de login respondeu HTTP {response.status}"
                )
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                pass
            final_url = page.url
            content = page.screenshot(
                full_page=False,
                animations="disabled",
                scale="device",
            )
    except (OSError, PlaywrightError) as error:
        return LoginCaptureFailure(
            f"página de login não pôde ser capturada: {error}"
        )
    folder.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return LoginCapture(
        path=output.resolve(),
        digest=hashlib.sha256(content).hexdigest(),
        final_url=final_url,
    )


__all__ = [
    "LOGIN_FILENAME",
    "LOGIN_PIXEL_SIZE",
    "LOGIN_SLOT",
    "LoginCapture",
    "LoginCaptureFailure",
    "capture_wordpress_login",
    "wordpress_login_url",
]
