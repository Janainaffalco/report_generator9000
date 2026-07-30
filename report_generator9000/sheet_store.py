"""Disk-derived storage for uploaded control spreadsheets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .retention import RETENTION


@dataclass(frozen=True)
class StoredSheet:
    sheet_id: str
    path: Path
    filename: str
    uploaded_at: datetime


@dataclass
class SheetStore:
    """Retains uploaded workbooks without a process-local index."""

    directory: Path

    def save(
        self, data: bytes, filename: str = "planilha.xlsx"
    ) -> tuple[str, Path]:
        """Write *data* to disk, returning the sheet_id it is retained under and its path."""
        self.directory.mkdir(parents=True, exist_ok=True)
        sheet_id = uuid4().hex
        path = self.directory / f"{sheet_id}.xlsx"
        path.write_bytes(data)
        self._metadata_path(sheet_id).write_text(
            json.dumps({"filename": filename}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return sheet_id, path

    def path(self, sheet_id: str) -> Path | None:
        """Return the retained workbook's path, or None if *sheet_id* is unknown."""
        if not self._valid_id(sheet_id):
            return None
        path = self.directory / f"{sheet_id}.xlsx"
        if not path.is_file():
            return None
        if self._is_expired(path):
            self.discard(sheet_id)
            return None
        return path

    def filename(self, sheet_id: str) -> str:
        """Return the workbook's original upload filename."""
        try:
            payload = json.loads(
                self._metadata_path(sheet_id).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return "planilha.xlsx"
        filename = payload.get("filename")
        return filename if isinstance(filename, str) else "planilha.xlsx"

    def all(self) -> tuple[StoredSheet, ...]:
        """List the workbooks found on disk, most recent first."""
        self.directory.mkdir(parents=True, exist_ok=True)
        sheets: list[StoredSheet] = []
        for path in self.directory.glob("*.xlsx"):
            if not self._valid_id(path.stem):
                continue
            if self._is_expired(path):
                self.discard(path.stem)
                continue
            sheets.append(
                StoredSheet(
                    sheet_id=path.stem,
                    path=path,
                    filename=self.filename(path.stem),
                    uploaded_at=datetime.fromtimestamp(
                        path.stat().st_mtime, UTC
                    ),
                )
            )
        return tuple(
            sorted(sheets, key=lambda sheet: sheet.uploaded_at, reverse=True)
        )

    def discard(self, sheet_id: str) -> None:
        """Remove a sheet that turned out to be unreadable."""
        if not self._valid_id(sheet_id):
            return
        (self.directory / f"{sheet_id}.xlsx").unlink(missing_ok=True)
        self._metadata_path(sheet_id).unlink(missing_ok=True)

    def _metadata_path(self, sheet_id: str) -> Path:
        return self.directory / f"{sheet_id}.json"

    @staticmethod
    def _is_expired(path: Path) -> bool:
        uploaded_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return uploaded_at < datetime.now(UTC) - RETENTION

    @staticmethod
    def _valid_id(sheet_id: str) -> bool:
        return len(sheet_id) == 32 and all(
            character in "0123456789abcdef" for character in sheet_id
        )


def default_sheet_store() -> SheetStore:
    """Use the same persistent VPS data root as retained Runs."""
    data_root = Path(os.environ.get("REPORT_DATA_ROOT", "/app/data"))
    return SheetStore(data_root / "sheets")
