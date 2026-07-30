from __future__ import annotations

import pytest

from report_generator9000.events import Event, add_sink, remove_sink


class RecordingSink:
    """Collects emitted events so tests assert on objects, not text."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def write(self, event: Event) -> None:
        self.events.append(event)


@pytest.fixture
def recording_sink():
    sink = RecordingSink()
    add_sink(sink)
    try:
        yield sink
    finally:
        remove_sink(sink)
