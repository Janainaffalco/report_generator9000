"""Read engagement rows from SEBRAETEC's control spreadsheet."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypeAlias
from urllib.parse import urlparse
from xml.etree import ElementTree
from zipfile import ZipFile


from .tema import WEBSITE_TEMA, contract_for

IN_SCOPE_TEMA = WEBSITE_TEMA
CONTROL_SHEET_NAME = "LV e Site"
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATIONSHIPS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_WORKBOOK_RELATIONSHIPS = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
)
_DATE_NUMBER_FORMATS = frozenset(
    (14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
     45, 46, 47)
)
_CONCATENATED_DOMAIN = re.compile(
    r"^(?P<origin>https?://[a-z0-9-]+\.hostingersite\.com/)"
    r"(?P<domain>[a-z0-9-]+(?:\.[a-z0-9-]+)+)/?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Engagement:
    """A row that can enter the report-generation pipeline."""

    row_number: int
    demanda: str
    pasta: str
    razao_social: str
    cnpj: str
    kick_off: datetime
    especialista: str
    capture_origin: str
    published_domain: str | None
    report_ready_text: str = ""
    tema: str = WEBSITE_TEMA

    @property
    def kick_off_br(self) -> str:
        """Kick off formatted for the Portuguese-language report."""
        return self.kick_off.strftime("%d/%m/%Y")

    @property
    def output_key(self) -> str:
        """The collision-proof directory key for this engagement."""
        return f"{self.pasta}_{self.razao_social}"


@dataclass(frozen=True)
class UnsupportedRow:
    """A real engagement whose Tema has no supported Master yet."""

    row_number: int
    reason: str
    report_ready_text: str = ""
    tema: str = ""
    demanda: str = ""
    razao_social: str = ""
    especialista: str = ""
    kick_off_text: str = ""
    link_text: str = ""


@dataclass(frozen=True)
class StopCondition:
    """A row that must not produce an output because a required input is unsafe."""

    row_number: int
    cause: str
    report_ready_text: str = ""
    demanda: str = ""
    razao_social: str = ""
    especialista: str = ""
    kick_off_text: str = ""
    link_text: str = ""


RowOutcome: TypeAlias = Engagement | UnsupportedRow | StopCondition


@dataclass(frozen=True)
class _Cell:
    value: str | datetime


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def _text(value: str | datetime | None) -> str:
    return "" if value is None else str(value).strip()


def _display_text(value: str | datetime | None) -> str:
    """Return spreadsheet text for display without interpreting or normalising it."""
    return "" if value is None else str(value)


def _display_cell(value: str | datetime | None) -> str:
    """Return a sheet cell as a consultant would expect to read it."""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return _display_text(value)


def _cnpj(value: str | datetime | None) -> str:
    text = _text(value)
    if not text:
        raise ValueError("CNPJ is absent")
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) not in (13, 14):
        raise ValueError("CNPJ must contain 13 or 14 digits")
    if len(digits) == 13:
        digits = digits.zfill(14)
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _kick_off(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    text = _text(value)
    if not text:
        raise ValueError("Kick off is absent")
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError("Kick off is not a date")


def _link(value: str | datetime | None) -> tuple[str, str | None] | str:
    if value is None or not _text(value):
        return "Link is absent"
    if isinstance(value, datetime):
        return "Link contains a delivery date"
    link = _text(value)
    concatenated = _CONCATENATED_DOMAIN.fullmatch(link)
    if concatenated:
        return concatenated.group("origin"), concatenated.group("domain")
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Link is not a URL"
    return link, None


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    try:
        document = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return ()
    return tuple(
        "".join(part.text or "" for part in item.iter(f"{_MAIN}t"))
        for item in document.iter(f"{_MAIN}si")
    )


def _number_formats(archive: ZipFile) -> tuple[tuple[int, str | None], ...]:
    try:
        document = ElementTree.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return ()
    custom_formats = {
        int(item.attrib["numFmtId"]): item.attrib["formatCode"]
        for item in document.iter(f"{_MAIN}numFmt")
    }
    cell_xfs = document.find(f"{_MAIN}cellXfs")
    if cell_xfs is None:
        return ()
    return tuple(
        (
            int(item.get("numFmtId", "0")),
            custom_formats.get(int(item.get("numFmtId", "0"))),
        )
        for item in cell_xfs
    )


def _worksheet_path(archive: ZipFile) -> str:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    sheet = next(
        (
            item
            for item in workbook.iter(f"{_MAIN}sheet")
            if item.get("name") == CONTROL_SHEET_NAME
        ),
        None,
    )
    if sheet is None:
        raise ValueError(f"workbook has no {CONTROL_SHEET_NAME!r} worksheet")
    relationship_id = sheet.get(f"{_WORKBOOK_RELATIONSHIPS}id")
    relationships = ElementTree.fromstring(
        archive.read("xl/_rels/workbook.xml.rels")
    )
    for relationship in relationships.iter(f"{_RELATIONSHIPS}Relationship"):
        if relationship.get("Id") == relationship_id:
            return "xl/" + relationship.attrib["Target"].lstrip("/")
    raise ValueError("workbook's first worksheet relationship is missing")


def _cell_value(
    cell: ElementTree.Element,
    shared_strings: tuple[str, ...],
    number_formats: tuple[tuple[int, str | None], ...],
) -> str | datetime | None:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        return "" if inline is None else "".join(
            item.text or "" for item in inline.iter(f"{_MAIN}t")
        )
    raw = cell.findtext(f"{_MAIN}v")
    if raw is None:
        return None
    if cell_type == "s":
        return shared_strings[int(raw)]
    style = int(cell.get("s", "0"))
    number_format, format_code = (
        number_formats[style] if style < len(number_formats) else (0, None)
    )
    if _is_date_number_format(number_format, format_code):
        return datetime(1899, 12, 30) + timedelta(days=float(raw))
    return raw


def _is_date_number_format(number_format: int, format_code: str | None) -> bool:
    if number_format in _DATE_NUMBER_FORMATS:
        return True
    if number_format < 164 or format_code is None:
        return False
    unquoted = re.sub(r'"[^"]*"|\[[^]]*\]|\\.', "", format_code)
    return bool(re.search(r"[dy]|a{2,4}", unquoted, re.IGNORECASE))


def _rows(path: str | Path) -> tuple[tuple[int, dict[str, _Cell]], ...]:
    with ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        number_formats = _number_formats(archive)
        sheet = ElementTree.fromstring(archive.read(_worksheet_path(archive)))
    rows: list[tuple[int, dict[str, _Cell]]] = []
    for position, row in enumerate(sheet.iter(f"{_MAIN}row"), start=1):
        values: dict[str, _Cell] = {}
        for cell in row.iter(f"{_MAIN}c"):
            reference = cell.get("r", "")
            column = re.match(r"[A-Z]+", reference)
            if column is None:
                continue
            value = _cell_value(cell, shared_strings, number_formats)
            if value is not None:
                values[column.group()] = _Cell(value)
        rows.append((int(row.get("r", str(position))), values))
    return tuple(rows)


def _headers(header: dict[str, _Cell]) -> dict[str, str]:
    names = {_normalise(cell.value): column for column, cell in header.items()}
    aliases = {
        "demanda": ("titulo", "demanda"),
        "pasta": ("no da pasta", "pasta"),
        "tema": ("tema contrato senai", "tema"),
        "cnpj": ("cnpj",),
        "razao_social": ("razao social",),
        "especialista": ("consultor responsavel", "especialista"),
        "kick_off": ("kick off",),
        "link": ("link",),
        "complete": ("relatorio pronto?", "relatorio pronto"),
    }
    resolved: dict[str, str] = {}
    for field, options in aliases.items():
        column = next((names[name] for name in options if name in names), None)
        if column is None:
            raise ValueError(f"control sheet: missing {field} column")
        resolved[field] = column
    return resolved


def _value(row: dict[str, _Cell], columns: dict[str, str], field: str) -> str | datetime | None:
    cell = row.get(columns[field])
    return None if cell is None else cell.value


def read_control_sheet(path: str | Path) -> tuple[RowOutcome, ...]:
    """Classify every data row by the action currently available for it."""
    rows = _rows(path)
    if not rows:
        raise ValueError("control sheet: no header row")
    columns = _headers(rows[0][1])
    outcomes: list[RowOutcome] = []
    for row_number, row in rows[1:]:
        report_ready_text = _display_text(_value(row, columns, "complete"))
        blocked_row = {
            "demanda": _display_cell(_value(row, columns, "demanda")),
            "razao_social": _display_cell(_value(row, columns, "razao_social")),
            "especialista": _display_cell(_value(row, columns, "especialista")),
            "kick_off_text": _display_cell(_value(row, columns, "kick_off")),
            "link_text": _display_cell(_value(row, columns, "link")),
        }
        tema = _text(_value(row, columns, "tema"))
        if not tema:
            outcomes.append(
                StopCondition(
                    row_number,
                    "Tema is absent",
                    report_ready_text,
                    **blocked_row,
                )
            )
            continue
        contract = contract_for(tema)
        if contract is None or not contract.supported:
            outcomes.append(
                UnsupportedRow(
                    row_number=row_number,
                    reason="Tema is unsupported",
                    report_ready_text=report_ready_text,
                    tema=tema,
                    **blocked_row,
                )
            )
            continue
        pasta = _text(_value(row, columns, "pasta"))
        if not pasta:
            outcomes.append(
                StopCondition(
                    row_number,
                    "Pasta is absent",
                    report_ready_text,
                    **blocked_row,
                )
            )
            continue
        link = _link(_value(row, columns, "link"))
        if isinstance(link, str):
            outcomes.append(
                StopCondition(
                    row_number,
                    link,
                    report_ready_text,
                    **blocked_row,
                )
            )
            continue
        try:
            cnpj = _cnpj(_value(row, columns, "cnpj"))
            kick_off = _kick_off(_value(row, columns, "kick_off"))
        except ValueError as error:
            outcomes.append(
                StopCondition(
                    row_number,
                    str(error),
                    report_ready_text,
                    **blocked_row,
                )
            )
            continue
        outcomes.append(
            Engagement(
                row_number=row_number,
                demanda=_text(_value(row, columns, "demanda")),
                pasta=pasta,
                razao_social=_text(_value(row, columns, "razao_social")),
                cnpj=cnpj,
                kick_off=kick_off,
                especialista=_text(_value(row, columns, "especialista")),
                capture_origin=link[0],
                published_domain=link[1],
                report_ready_text=report_ready_text,
                tema=tema,
            )
        )
    return tuple(outcomes)


def read_row_pastas(path: str | Path) -> dict[int, str]:
    """Every data row's Pasta cell, including rows that stop or are skipped.

    `StopCondition` and `UnsupportedRow` do not carry Pasta, but a row is addressed by Pasta
    *and* row number, so callers presenting those rows need the Pasta separately.
    """
    rows = _rows(path)
    if not rows:
        return {}
    columns = _headers(rows[0][1])
    return {
        row_number: _text(_value(row, columns, "pasta"))
        for row_number, row in rows[1:]
    }


def read_control_sheet_for_pasta(
    path: str | Path, pasta: str
) -> tuple[RowOutcome, ...]:
    """Read every row whose Pasta matches *pasta*, including Stop Conditions."""
    rows = _rows(path)
    if not rows:
        raise ValueError("control sheet: no header row")
    columns = _headers(rows[0][1])
    requested = _normalise(pasta)
    matching_rows = {
        row_number
        for row_number, row in rows[1:]
        if _normalise(_text(_value(row, columns, "pasta"))) == requested
    }
    if not matching_rows:
        raise ValueError(f"control sheet: Pasta {pasta!r} was not found")
    return tuple(
        outcome
        for outcome in read_control_sheet(path)
        if outcome.row_number in matching_rows
    )
