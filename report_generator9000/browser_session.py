"""Own the single Chromium process used by one Run."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright


@dataclass
class _RunBrowserSession:
    playwright: Playwright | None = None
    browser: Browser | None = None

    def new_context(self, **options: Any) -> BrowserContext:
        if self.browser is None:
            self.playwright = sync_playwright().start()
            try:
                self.browser = self.playwright.chromium.launch(headless=True)
            except BaseException:
                self.playwright.stop()
                self.playwright = None
                raise
        return self.browser.new_context(**options)

    def close(self) -> None:
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            if self.playwright is not None:
                self.playwright.stop()


_ACTIVE_SESSION: ContextVar[_RunBrowserSession | None] = ContextVar(
    "active_browser_session",
    default=None,
)


@contextmanager
def run_browser_session() -> Iterator[None]:
    """Keep one lazily launched Chromium process alive for a whole Run."""
    active = _ACTIVE_SESSION.get()
    if active is not None:
        yield
        return

    session = _RunBrowserSession()
    token = _ACTIVE_SESSION.set(session)
    try:
        yield
    finally:
        try:
            session.close()
        finally:
            _ACTIVE_SESSION.reset(token)


@contextmanager
def browser_context(**options: Any) -> Iterator[BrowserContext]:
    """Create one stage-local context in the active Run's Chromium process."""
    active = _ACTIVE_SESSION.get()
    if active is None:
        with run_browser_session():
            with browser_context(**options) as context:
                yield context
        return

    context = active.new_context(**options)
    try:
        yield context
    finally:
        context.close()


__all__ = ["browser_context", "run_browser_session"]
