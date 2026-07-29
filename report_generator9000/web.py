from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from .control_sheet import (
    CONTROL_SHEET_NAME,
    Engagement,
    RowOutcome,
    SkippedRow,
    StopCondition,
    read_control_sheet,
    read_row_pastas,
)
from .sheet_store import SheetStore, default_sheet_store


DEFAULT_STATIC_DIR = Path(__file__).with_name("web_dist")

_NOT_XLSX_DETAIL = "Este arquivo não é uma planilha .xlsx que possamos ler."
_MISSING_WORKSHEET_DETAIL = "A planilha não tem a aba “LV e Site”."
_MISSING_COLUMNS_DETAIL = "A aba “LV e Site” não tem as colunas esperadas."

@dataclass(frozen=True)
class _Remedy:
    """What a consultant is told about a Stop Condition, and where to fix it."""

    coluna: str
    problema: str
    solucao: str


@dataclass(frozen=True)
class _Exclusion:
    """What a consultant is told about a row the pipeline left out."""

    titulo: str
    explicacao: str


_STOP_CAUSES: dict[str, _Remedy] = {
    "Link is absent": _Remedy(
        "Link",
        "A coluna Link está vazia.",
        "Cole o endereço do site publicado, começando com https://.",
    ),
    "Link contains a delivery date": _Remedy(
        "Link",
        "A coluna Link tem uma data no lugar do endereço.",
        "Troque a data pelo endereço do site publicado.",
    ),
    "Link is not a URL": _Remedy(
        "Link",
        "O que está na coluna Link não é um endereço de site.",
        "Corrija para um endereço completo, começando com https://.",
    ),
    "Pasta is absent": _Remedy(
        "nº da pasta",
        "A coluna nº da pasta está vazia.",
        "Preencha o número da pasta, como 115-2026.",
    ),
    "CNPJ must contain 13 or 14 digits": _Remedy(
        "CNPJ",
        "O CNPJ não tem 13 ou 14 dígitos.",
        "Corrija o CNPJ na coluna CNPJ.",
    ),
    "Kick off is not a date": _Remedy(
        "Kick off",
        "A coluna Kick off não tem uma data.",
        "Use uma data no formato dd/mm/aaaa.",
    ),
}

_UNTRANSLATED_CAUSE = _Remedy(
    "—",
    "Esta linha foi interrompida por um motivo que ainda não tem explicação em português.",
    "Avise quem cuida do sistema, informando a causa original registrada abaixo.",
)

_SKIPPED_REASONS: dict[str, _Exclusion] = {
    "Tema is out of scope": _Exclusion(
        "Tema fora do escopo",
        "São linhas de Implantação de Loja Virtual. Ainda não existe um Master aprovado "
        "para esse Tema, então não há de onde gerar o relatório — a linha está correta, "
        "só não é deste pipeline.",
    ),
    "already complete": _Exclusion(
        "Relatório já marcado como pronto",
        "A coluna “Relatório pronto?” já está preenchida, então a linha foi "
        "deixada de fora.",
    ),
}


class RowRef(BaseModel):
    pasta: str | None
    row_number: int


class EngagementOut(BaseModel):
    row: RowRef
    demanda: str
    razao_social: str
    especialista: str
    kick_off: str
    capture_origin: str
    published_domain: str | None


class StopConditionOut(BaseModel):
    row: RowRef
    coluna: str
    problema: str
    solucao: str
    cause: str


class SkippedReasonOut(BaseModel):
    cause: str
    titulo: str
    explicacao: str
    total: int
    rows: list[RowRef]


class SkippedRowsOut(BaseModel):
    total: int
    resumo: str
    reasons: list[SkippedReasonOut]


class ControlSheetResponse(BaseModel):
    sheet_id: str
    filename: str
    engagements: list[EngagementOut]
    stop_conditions: list[StopConditionOut]
    skipped_rows: SkippedRowsOut


def _unreadable_detail(error: ValueError) -> str:
    message = str(error)
    if CONTROL_SHEET_NAME in message:
        return _MISSING_WORKSHEET_DETAIL
    if message.startswith("control sheet:"):
        return _MISSING_COLUMNS_DETAIL
    return _NOT_XLSX_DETAIL


def _read_sheet(path: Path) -> tuple[tuple[RowOutcome, ...], dict[int, str]]:
    """Every row's outcome, plus the Pasta of the rows that carry only a row number."""
    try:
        return read_control_sheet(path), read_row_pastas(path)
    except (BadZipFile, KeyError, ParseError) as error:
        raise HTTPException(422, _NOT_XLSX_DETAIL) from error
    except ValueError as error:
        raise HTTPException(422, _unreadable_detail(error)) from error


def _resumo(total: int) -> str:
    if total == 1:
        return "1 linha ficou de fora"
    return f"{total} linhas ficaram de fora"


def _build_response(
    sheet_id: str,
    filename: str,
    outcomes: tuple[RowOutcome, ...],
    pasta_by_row: dict[int, str],
) -> ControlSheetResponse:
    def row_ref(row_number: int, pasta: str) -> RowRef:
        return RowRef(pasta=pasta or None, row_number=row_number)

    engagements = [
        EngagementOut(
            row=row_ref(outcome.row_number, outcome.pasta),
            demanda=outcome.demanda,
            razao_social=outcome.razao_social,
            especialista=outcome.especialista,
            kick_off=outcome.kick_off_br,
            capture_origin=outcome.capture_origin,
            published_domain=outcome.published_domain,
        )
        for outcome in outcomes
        if isinstance(outcome, Engagement)
    ]
    stop_conditions = [
        StopConditionOut(
            row=row_ref(outcome.row_number, pasta_by_row.get(outcome.row_number, "")),
            coluna=remedy.coluna,
            problema=remedy.problema,
            solucao=remedy.solucao,
            cause=outcome.cause,
        )
        for outcome in outcomes
        if isinstance(outcome, StopCondition)
        for remedy in (_STOP_CAUSES.get(outcome.cause, _UNTRANSLATED_CAUSE),)
    ]
    skipped = [outcome for outcome in outcomes if isinstance(outcome, SkippedRow)]
    reasons = []
    for cause, exclusion in _SKIPPED_REASONS.items():
        matching = [row for row in skipped if row.reason == cause]
        if not matching:
            continue
        reasons.append(
            SkippedReasonOut(
                cause=cause,
                titulo=exclusion.titulo,
                explicacao=exclusion.explicacao,
                total=len(matching),
                rows=[
                    row_ref(row.row_number, pasta_by_row.get(row.row_number, ""))
                    for row in matching
                ],
            )
        )
    return ControlSheetResponse(
        sheet_id=sheet_id,
        filename=filename,
        engagements=engagements,
        stop_conditions=stop_conditions,
        skipped_rows=SkippedRowsOut(
            total=len(skipped), resumo=_resumo(len(skipped)), reasons=reasons
        ),
    )


def create_app(
    *,
    static_dir: Path = DEFAULT_STATIC_DIR,
    sheet_store: SheetStore | None = None,
) -> FastAPI:
    app = FastAPI(title="Relatórios SEBRAETEC")
    store = sheet_store if sheet_store is not None else default_sheet_store()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/control-sheet")
    async def control_sheet(file: UploadFile = File(...)) -> ControlSheetResponse:
        sheet_id, path = store.save(await file.read())
        try:
            outcomes, pasta_by_row = _read_sheet(path)
        except HTTPException:
            store.discard(sheet_id)
            raise
        return _build_response(
            sheet_id, file.filename or "planilha.xlsx", outcomes, pasta_by_row
        )

    app.frontend(
        "/",
        directory=static_dir,
        fallback="index.html",
        check_dir=False,
    )
    return app


app = create_app()
