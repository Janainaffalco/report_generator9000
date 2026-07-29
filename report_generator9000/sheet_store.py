"""Session-scoped storage for uploaded control spreadsheets."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass
class SheetStore:
    """Retains uploaded workbooks on disk, keyed by sheet_id, for the app's lifetime."""

    directory: Path
    _paths: dict[str, Path] = field(default_factory=dict, init=False, repr=False)

    def save(self, data: bytes) -> tuple[str, Path]:
        """Write *data* to disk, returning the sheet_id it is retained under and its path."""
        self.directory.mkdir(parents=True, exist_ok=True)
        sheet_id = uuid4().hex
        path = self.directory / f"{sheet_id}.xlsx"
        path.write_bytes(data)
        self._paths[sheet_id] = path
        return sheet_id, path

    def path(self, sheet_id: str) -> Path | None:
        """Return the retained workbook's path, or None if *sheet_id* is unknown."""
        return self._paths.get(sheet_id)

    def discard(self, sheet_id: str) -> None:
        """Forget a sheet that turned out to be unreadable."""
        path = self._paths.pop(sheet_id, None)
        if path is not None:
            path.unlink(missing_ok=True)


def default_sheet_store() -> SheetStore:
    """A SheetStore writing under the OS temp directory, for production use."""
    return SheetStore(Path(tempfile.gettempdir()) / "report_generator9000" / "sheets")
