from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import report_generator9000.assembly as assembly_module
import report_generator9000.browser_session as browser_session_module


class _FakeContext:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[_FakeContext] = []
        self.closed = False

    def new_context(self, **_options: Any) -> _FakeContext:
        context = _FakeContext()
        self.contexts.append(context)
        return context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.launches = 0

    def launch(self, *, headless: bool) -> _FakeBrowser:
        assert headless is True
        self.launches += 1
        return self.browser


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.chromium = _FakeChromium(browser)
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _FakePlaywrightManager:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self.playwright = playwright
        self.starts = 0

    def start(self) -> _FakePlaywright:
        self.starts += 1
        return self.playwright


def test_run_launches_once_and_cleans_up_after_a_stage_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _FakeBrowser()
    playwright = _FakePlaywright(browser)
    manager = _FakePlaywrightManager(playwright)
    monkeypatch.setattr(
        browser_session_module,
        "sync_playwright",
        lambda: manager,
    )

    def failing_stages(*_args: Any, **_kwargs: Any) -> None:
        for stage in range(4):
            with browser_session_module.browser_context(stage=stage):
                pass
        raise RuntimeError("stage failed")

    monkeypatch.setattr(
        assembly_module,
        "_assemble_staged_package",
        failing_stages,
    )
    monkeypatch.setattr(
        assembly_module,
        "engagement_artifact_key",
        lambda _engagement: "test-run",
    )

    with pytest.raises(RuntimeError, match="stage failed"):
        assembly_module.assemble_output_package(
            "master.docx",
            tmp_path,
            object(),
            tmp_path / "gated",
        )

    assert manager.starts == 1
    assert playwright.chromium.launches == 1
    assert len(browser.contexts) == 4
    assert all(context.closed for context in browser.contexts)
    assert browser.closed is True
    assert playwright.stopped is True
