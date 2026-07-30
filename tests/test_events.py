from __future__ import annotations

import json
import logging

import pytest

from conftest import RecordingSink
from report_generator9000 import events
from report_generator9000.events import (
    OPERATIONS,
    Event,
    RunLogSink,
    add_sink,
    configure_logging,
    current_run_id,
    notice,
    operation,
    remove_sink,
    run_scope,
    stage,
)
from report_generator9000.gemini_provider import GeminiSettings


class _RaisingSink:
    def write(self, event: Event) -> None:
        raise RuntimeError("sink boom")


def _make_event(**overrides: object) -> Event:
    base = dict(
        kind="notice",
        name="something",
        severity="info",
        run_id=None,
        timestamp="2026-07-30T00:00:00+00:00",
        fields={},
    )
    base.update(overrides)
    return Event(**base)


def test_event_rejects_non_scalar_field_value() -> None:
    settings = GeminiSettings(api_key="secret-value")
    with pytest.raises(ValueError):
        _make_event(fields={"settings": settings})


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API_KEY",
        "apikey",
        "secret",
        "SECRET_TOKEN_HOLDER",
        "password",
        "credential",
        "authorization",
        "Authorization",
    ],
)
def test_event_rejects_denylisted_field_key(key: str) -> None:
    with pytest.raises(ValueError):
        _make_event(fields={key: "x"})


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "secret",
        "password",
        "credential",
        "authorization",
    ],
)
def test_event_rejects_denylisted_detail_key(key: str) -> None:
    with pytest.raises(ValueError):
        _make_event(detail={key: "x"})


def test_event_accepts_token_count_field() -> None:
    event = _make_event(fields={"token_count": 42})
    assert event.fields["token_count"] == 42


def test_notice_propagates_scalar_guard() -> None:
    settings = GeminiSettings(api_key="secret-value")
    with pytest.raises(ValueError):
        notice("bad", model=settings)


def test_notice_propagates_denylist_guard() -> None:
    with pytest.raises(ValueError):
        notice("bad", api_key="x")


def test_run_scope_sets_run_id_on_emitted_events(recording_sink) -> None:
    with run_scope("run-1"):
        stage("read_row")
    assert recording_sink.events[-1].run_id == "run-1"


def test_events_outside_scope_have_no_run_id(recording_sink) -> None:
    stage("read_row")
    assert recording_sink.events[-1].run_id is None
    assert current_run_id() is None


def test_run_scope_nesting_restores_outer_value(recording_sink) -> None:
    with run_scope("outer"):
        with run_scope("inner"):
            stage("a")
        assert current_run_id() == "outer"
        stage("b")
    assert current_run_id() is None
    assert recording_sink.events[-2].run_id == "inner"
    assert recording_sink.events[-1].run_id == "outer"


def test_run_scope_resets_contextvar_even_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with run_scope("boom"):
            raise RuntimeError("kaboom")
    assert current_run_id() is None


def test_operation_emits_start_then_end(recording_sink) -> None:
    with operation("capture_site"):
        pass
    kinds = [event.kind for event in recording_sink.events]
    assert kinds == ["operation_start", "operation_end"]


def test_operation_duration_only_on_end(recording_sink) -> None:
    with operation("capture_site"):
        pass
    start, end = recording_sink.events
    assert start.duration_ms is None
    assert end.duration_ms is not None
    assert end.duration_ms >= 0


def test_operation_yielded_fields_reach_end_event(recording_sink) -> None:
    with operation("capture_site") as result:
        result["page_count"] = 7
    end = recording_sink.events[-1]
    assert end.fields["page_count"] == 7


def test_operation_on_exception_emits_error_end_and_reraises(
    recording_sink,
) -> None:
    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with operation("capture_site"):
            raise _Boom("bad site")

    end = recording_sink.events[-1]
    assert end.kind == "operation_end"
    assert end.severity == "error"
    assert end.fields["error"] == "_Boom"
    assert "traceback" in end.detail
    assert "_Boom" in end.detail["traceback"]


def test_operation_rejects_unknown_name() -> None:
    with pytest.raises(ValueError):
        with operation("not_a_real_operation"):  # type: ignore[arg-type]
            pass


def test_operations_tuple_contains_expected_names() -> None:
    assert OPERATIONS == (
        "capture_site",
        "extract_site_text",
        "gemini_call",
        "assemble_docx",
        "gate_run",
    )


def test_run_log_sink_writes_one_json_line_per_event(tmp_path) -> None:
    sink = RunLogSink(tmp_path)
    with run_scope("run-a"):
        event = Event(
            kind="notice",
            name="thing",
            severity="info",
            run_id=current_run_id(),
            timestamp="2026-07-30T00:00:00+00:00",
            fields={"x": 1},
            detail={"traceback": "some trace"},
        )
        sink.write(event)
    path = tmp_path / "run-a.log"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["detail"]["traceback"] == "some trace"
    assert payload["fields"]["x"] == 1


def test_run_log_sink_drops_events_with_no_run_id(tmp_path) -> None:
    sink = RunLogSink(tmp_path)
    event = Event(
        kind="notice",
        name="thing",
        severity="info",
        run_id=None,
        timestamp="2026-07-30T00:00:00+00:00",
        fields={},
    )
    sink.write(event)
    assert list(tmp_path.iterdir()) == []


def test_run_log_sink_separates_run_ids_into_different_files(
    tmp_path,
) -> None:
    sink = RunLogSink(tmp_path)
    for run_id in ("run-a", "run-b"):
        sink.write(
            Event(
                kind="notice",
                name="thing",
                severity="info",
                run_id=run_id,
                timestamp="2026-07-30T00:00:00+00:00",
                fields={},
            )
        )
    assert (tmp_path / "run-a.log").exists()
    assert (tmp_path / "run-b.log").exists()


def test_raising_sink_does_not_break_emit_to_other_sinks() -> None:
    raising = _RaisingSink()
    recording = RecordingSink()
    add_sink(raising)
    add_sink(recording)
    try:
        stage("survive")
    finally:
        remove_sink(raising)
        remove_sink(recording)
    assert len(recording.events) == 1
    assert recording.events[0].name == "survive"


def test_event_from_a_callee_carries_the_ambient_run_id(recording_sink) -> None:
    def fake_capture_site() -> str | None:
        stage("capture")
        return current_run_id()

    with run_scope("run-thread"):
        seen_run_id = fake_capture_site()

    assert seen_run_id == "run-thread"
    stage_events = [
        event for event in recording_sink.events if event.name == "capture"
    ]
    assert stage_events
    assert stage_events[-1].run_id == "run-thread"


@pytest.fixture
def _clean_logging_state():
    logger = logging.getLogger("report_generator9000")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    root = logging.getLogger()
    original_root_level = root.level
    original_configured = events._configured
    original_run_log_sink = events._run_log_sink
    original_stdlib_sink = events._stdlib_sink
    original_sinks = list(events._sinks)
    try:
        yield
    finally:
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)
        root.setLevel(original_root_level)
        events._configured = original_configured
        events._run_log_sink = original_run_log_sink
        events._stdlib_sink = original_stdlib_sink
        events._sinks[:] = original_sinks


def test_configure_logging_is_idempotent(_clean_logging_state) -> None:
    configure_logging()
    handler_count_after_first = len(
        logging.getLogger("report_generator9000").handlers
    )
    configure_logging()
    handler_count_after_second = len(
        logging.getLogger("report_generator9000").handlers
    )
    assert handler_count_after_first == handler_count_after_second


def test_configure_logging_honours_env_level(
    monkeypatch, _clean_logging_state
) -> None:
    monkeypatch.setenv("REPORT_LOG_LEVEL", "DEBUG")
    configure_logging()
    logger = logging.getLogger("report_generator9000")
    assert logger.level == logging.DEBUG


def test_configure_logging_defaults_to_info(
    monkeypatch, _clean_logging_state
) -> None:
    monkeypatch.delenv("REPORT_LOG_LEVEL", raising=False)
    configure_logging()
    logger = logging.getLogger("report_generator9000")
    assert logger.level == logging.INFO


def test_configure_logging_sets_root_to_warning(
    _clean_logging_state,
) -> None:
    configure_logging()
    assert logging.getLogger().level == logging.WARNING
