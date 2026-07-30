"""Ambient event logging: one typed event source, two sinks."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Literal, Mapping, Protocol

Scalar = str | int | float | bool | None
Severity = Literal["info", "warning", "error"]
EventKind = Literal["stage", "operation_start", "operation_end", "notice"]

OperationName = Literal[
    "capture_site",
    "extract_site_text",
    "gemini_call",
    "assemble_docx",
    "gate_run",
]
OPERATIONS: tuple[OperationName, ...] = (
    "capture_site",
    "extract_site_text",
    "gemini_call",
    "assemble_docx",
    "gate_run",
)

_DENYLISTED_TERMS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "credential",
    "authorization",
)


def _check_key(key: str) -> None:
    lowered = key.lower()
    for term in _DENYLISTED_TERMS:
        if term in lowered:
            raise ValueError(f"disallowed field/detail key: {key!r}")


def _check_scalar(key: str, value: object) -> None:
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        raise ValueError(
            f"field {key!r} has non-scalar value of type "
            f"{type(value).__name__}"
        )


@dataclass(frozen=True)
class Event:
    kind: EventKind
    name: str
    severity: Severity
    run_id: str | None
    timestamp: str
    fields: Mapping[str, Scalar]
    detail: Mapping[str, str] = field(default_factory=dict)
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        for key, value in self.fields.items():
            _check_key(key)
            _check_scalar(key, value)
        for key, text in self.detail.items():
            _check_key(key)
            if not isinstance(text, str):
                raise ValueError(
                    f"detail {key!r} must be text, not "
                    f"{type(text).__name__}"
                )


class Sink(Protocol):
    def write(self, event: Event) -> None: ...


_sinks: list[Sink] = []
_sinks_lock = threading.Lock()


def add_sink(sink: Sink) -> None:
    with _sinks_lock:
        _sinks.append(sink)


def remove_sink(sink: Sink) -> None:
    with _sinks_lock:
        if sink in _sinks:
            _sinks.remove(sink)


def _emit(event: Event) -> None:
    with _sinks_lock:
        sinks = list(_sinks)
    for sink in sinks:
        try:
            sink.write(event)
        except Exception:
            continue


_current_run_id: ContextVar[str | None] = ContextVar(
    "_current_run_id", default=None
)


def current_run_id() -> str | None:
    return _current_run_id.get()


@contextmanager
def run_scope(run_id: str) -> Iterator[None]:
    token = _current_run_id.set(run_id)
    try:
        yield
    finally:
        _current_run_id.reset(token)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def stage(name: str, **fields: Scalar) -> None:
    _emit(
        Event(
            kind="stage",
            name=name,
            severity="info",
            run_id=current_run_id(),
            timestamp=_now(),
            fields=fields,
        )
    )


def notice(
    name: str,
    *,
    severity: Severity = "info",
    detail: Mapping[str, str] | None = None,
    **fields: Scalar,
) -> None:
    _emit(
        Event(
            kind="notice",
            name=name,
            severity=severity,
            run_id=current_run_id(),
            timestamp=_now(),
            fields=fields,
            detail=detail or {},
        )
    )


@contextmanager
def operation(
    name: OperationName, **fields: Scalar
) -> Iterator[dict[str, Scalar]]:
    if name not in OPERATIONS:
        raise ValueError(f"unknown operation: {name!r}")
    run_id = current_run_id()
    _emit(
        Event(
            kind="operation_start",
            name=name,
            severity="info",
            run_id=run_id,
            timestamp=_now(),
            fields=fields,
        )
    )
    result: dict[str, Scalar] = {}
    start = time.perf_counter()
    try:
        yield result
    except Exception as error:
        duration_ms = (time.perf_counter() - start) * 1000
        _emit(
            Event(
                kind="operation_end",
                name=name,
                severity="error",
                run_id=run_id,
                timestamp=_now(),
                fields={
                    **fields,
                    **result,
                    "error": type(error).__name__,
                },
                detail={"traceback": traceback.format_exc()},
                duration_ms=duration_ms,
            )
        )
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        _emit(
            Event(
                kind="operation_end",
                name=name,
                severity="info",
                run_id=run_id,
                timestamp=_now(),
                fields={**fields, **result},
                duration_ms=duration_ms,
            )
        )


class RunLogSink:
    """Appends one JSON object per line to `<directory>/<run_id>.log`.

    Events with no run_id (emitted outside any Run) are dropped: this
    sink is Run-log storage, not a general log. The Run log is not
    Provenance and must never become a source of truth for the report
    itself — see docs/adr/0002.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()

    def write(self, event: Event) -> None:
        if event.run_id is None:
            return
        payload = {
            "kind": event.kind,
            "name": event.name,
            "severity": event.severity,
            "run_id": event.run_id,
            "timestamp": event.timestamp,
            "fields": dict(event.fields),
            "detail": dict(event.detail),
            "duration_ms": event.duration_ms,
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{event.run_id}.log"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


_LOGGER_NAME = "report_generator9000"
_LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class _StdlibSink:
    """Formats one terse human line; `detail` is never rendered here."""

    def write(self, event: Event) -> None:
        logger = logging.getLogger(_LOGGER_NAME)
        parts = [event.name]
        if event.run_id is not None:
            parts.append(f"run={event.run_id[:8]}")
        if event.duration_ms is not None:
            parts.append(f"duration_ms={event.duration_ms:.1f}")
        for key, value in event.fields.items():
            parts.append(f"{key}={value}")
        logger.log(_LEVELS[event.severity], " ".join(parts))


_configured = False
_run_log_sink: RunLogSink | None = None
_stdlib_sink: _StdlibSink | None = None


def configure_logging(*, run_log_directory: Path | None = None) -> None:
    """Wire the stdlib logger sink and (optionally) the Run-log sink.

    The handler is a plain `logging.StreamHandler()`, which writes to
    stderr. That is deliberate: the bare `print()` calls in `cli.py`
    and `generate_cli.py` are a machine-readable stdout contract that
    must stay byte-identical, so nothing this module does may touch
    stdout.

    `httpx` and `google-genai` are held above DEBUG on purpose: at
    DEBUG they log full request bodies, and the request bodies here
    are the Gemini prompts.
    """
    global _configured, _run_log_sink, _stdlib_sink
    level_name = os.environ.get("REPORT_LOG_LEVEL", "INFO").strip().upper()
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level_name)
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    if not _configured:
        logger.addHandler(logging.StreamHandler())
        _stdlib_sink = _StdlibSink()
        add_sink(_stdlib_sink)
        _configured = True
    if run_log_directory is not None:
        if _run_log_sink is not None:
            remove_sink(_run_log_sink)
        _run_log_sink = RunLogSink(run_log_directory)
        add_sink(_run_log_sink)


__all__ = [
    "Event",
    "EventKind",
    "OPERATIONS",
    "OperationName",
    "RunLogSink",
    "Scalar",
    "Severity",
    "Sink",
    "add_sink",
    "configure_logging",
    "current_run_id",
    "notice",
    "operation",
    "remove_sink",
    "run_scope",
    "stage",
]
