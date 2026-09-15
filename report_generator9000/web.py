from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .auth import (
    UNAUTHENTICATED_DETAIL,
    clear_session_cookie,
    is_public_path,
    login_failed_detail,
    passwords_match,
    request_is_authenticated,
    resolve_password,
    set_session_cookie,
)

from .control_sheet import (
    CONTROL_SHEET_NAME,
    Engagement,
    RowOutcome,
    StopCondition,
    UnsupportedRow,
    read_control_sheet,
    read_row_pastas,
)
from .run_context import classification_label
from .gated_inputs import (
    GATED_IMAGE_PARTS,
    GATED_VALUE_SLOTS,
    VALUES_FILE,
    GatedInputError,
    gated_drop_folder,
    load_gated_inputs,
)
from .runs import RunRecord, STAGES, default_run_service
from .tema import supported_contract
from .sheet_store import SheetStore, default_sheet_store


DEFAULT_STATIC_DIR = Path(__file__).with_name("web_dist")

_ROBOTS_TXT = "User-agent: *\nDisallow: /\n"
_X_ROBOTS_TAG = "noindex, nofollow"
_REFERRER_POLICY = "no-referrer"

_NOT_XLSX_DETAIL = "Este arquivo não é uma planilha .xlsx que possamos ler."
_MISSING_WORKSHEET_DETAIL = "A planilha não tem a aba “LV e Site”."
_MISSING_COLUMNS_DETAIL = "A aba “LV e Site” não tem as colunas esperadas."
_EXPIRED_SHEET_DETAIL = (
    "Esta planilha expirou ou não é conhecida. Envie-a novamente."
)

@dataclass(frozen=True)
class _Remedy:
    """What a consultant is told about a Stop Condition, and where to fix it."""

    coluna: str
    problema: str
    solucao: str


_STOP_CAUSES: dict[str, _Remedy] = {
    "Tema is absent": _Remedy(
        "Tema",
        "A coluna Tema está vazia.",
        "Preencha o produto contratado na coluna Tema.",
    ),
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
    "CNPJ is absent": _Remedy(
        "CNPJ",
        "A coluna CNPJ está vazia.",
        "Preencha o CNPJ na coluna CNPJ.",
    ),
    "Kick off is not a date": _Remedy(
        "Kick off",
        "A coluna Kick off não tem uma data.",
        "Use uma data no formato dd/mm/aaaa.",
    ),
    "Kick off is absent": _Remedy(
        "Kick off",
        "A coluna Kick off está vazia.",
        "Preencha a data de início na coluna Kick off.",
    ),
}

_UNTRANSLATED_CAUSE = _Remedy(
    "—",
    "Esta linha foi interrompida por um motivo que ainda não tem explicação em português.",
    "Avise quem cuida do sistema, informando a causa original registrada abaixo.",
)

# The Pendência classes must read correctly and differently: GATED is normal
# and expected, TOOL_BLOCKED is a defect worth re-running for, and UNDECLARED
# is a property of the site rather than a failure of either kind. REVIEW is
# generated content still awaiting the consultant's approval.
_CLASSIFICATION_EXPLANATIONS = {
    "GATED": (
        "Normal e esperado: nenhuma automação consegue obter este conteúdo "
        "sozinha."
    ),
    "TOOL_BLOCKED": (
        "Defeito da automação: a captura falhou e gerar de novo pode "
        "resolver."
    ),
    "UNDECLARED": (
        "O site não declara essa informação — é uma característica do "
        "site, não uma falha da geração."
    ),
    "REVIEW": (
        "Gerado a partir de fatos observados, mas ainda precisa da sua "
        "aprovação antes do envio."
    ),
}

# The same gates that would have blocked the run, stated in language that
# means something to a consultant rather than the gate's internal name.
_GATE_LABELS = {
    "media-provenance": "Nenhuma imagem de outro cliente no arquivo",
    "link-provenance": "Os links apontam para o cliente certo",
    "token-residue": "Nenhum campo do Master ficou por preencher",
    "engagement-scope": "Os arquivos usados pertencem a este cliente",
    "block-integrity": "Todo título de Bloco tem sua imagem",
    "pendencias-agreement": "A lista de Pendências bate com o documento",
}


class LoginRequest(BaseModel):
    password: str


class RowRef(BaseModel):
    pasta: str | None
    row_number: int


class EngagementOut(BaseModel):
    row: RowRef
    tema: str
    demanda: str
    razao_social: str
    especialista: str
    kick_off: str
    capture_origin: str
    published_domain: str | None
    report_ready_text: str


class StopConditionOut(BaseModel):
    row: RowRef
    demanda: str
    razao_social: str
    especialista: str
    kick_off: str
    link: str
    coluna: str
    problema: str
    solucao: str
    cause: str
    report_ready_text: str


class UnsupportedRowOut(BaseModel):
    row: RowRef
    tema: str
    demanda: str
    razao_social: str
    especialista: str
    kick_off: str
    link: str
    report_ready_text: str
    cause: str
    explicacao: str


class UnsupportedRowsOut(BaseModel):
    total: int
    rows: list[UnsupportedRowOut]


class ControlSheetResponse(BaseModel):
    sheet_id: str
    filename: str
    engagements: list[EngagementOut]
    stop_conditions: list[StopConditionOut]
    unsupported_rows: UnsupportedRowsOut


class RetainedSheetOut(BaseModel):
    sheet_id: str
    filename: str
    uploaded_at: str
    ready_count: int


class StartRunRequest(BaseModel):
    sheet_id: str
    row_number: int


class StartBatchRequest(BaseModel):
    sheet_id: str
    row_numbers: list[int]


class StageOut(BaseModel):
    name: str
    state: str


class RunResponse(BaseModel):
    run_id: str
    sheet_id: str
    tema: str
    engagement: dict[str, object]
    outcome: str
    current_stage: str | None
    stages: list[StageOut]
    stage_history: list[str]
    page_count: int | None
    status: str | None
    filename: str | None
    reason: str | None
    download_url: str | None


class BatchResponse(BaseModel):
    batch_id: str
    sheet_id: str
    runs: list[RunResponse]


class PastRunOut(BaseModel):
    run_id: str
    razao_social: str
    pasta: str
    demanda: str
    generated_at: str
    page_count: int
    status: str
    filename: str
    review_url: str
    download_url: str


class PendenciaOut(BaseModel):
    classification: str
    classification_label: str
    classification_explanation: str
    name: str
    required_action: str
    page: str
    preview_page: int | None
    attachment_filename: str | None
    attachment_value_key: str | None


class CheckOut(BaseModel):
    label: str
    passed: bool


class FinishedReportResponse(BaseModel):
    run_id: str
    status: str
    # This resource describes the finished document, so its page count is the
    # rendered document's count. RunResponse.page_count separately narrates
    # the size of the client's Lista de Páginas while generation is running.
    page_count: int
    filename: str
    download_url: str
    pendencias: list[PendenciaOut]
    checks: list[CheckOut]


def _run_response(record: RunRecord) -> RunResponse:
    completed = set(record.completed_stages)
    return RunResponse(
        run_id=record.run_id,
        sheet_id=record.sheet_id,
        tema=record.tema,
        engagement=record.engagement,
        outcome=record.outcome,
        current_stage=record.current_stage,
        stages=[
            StageOut(
                name=name,
                state=(
                    "current"
                    if name == record.current_stage
                    else "done"
                    if name in completed
                    else "pending"
                ),
            )
            for name in STAGES
        ],
        stage_history=list(record.stage_history),
        page_count=record.page_count,
        status=record.report_status,
        filename=record.filename,
        reason=record.reason,
        download_url=(
            f"/api/runs/{record.run_id}/download"
            if record.outcome == "finished" and record.document
            else None
        ),
    )


def _report_response(record: RunRecord) -> FinishedReportResponse:
    contract = supported_contract(record.tema)
    image_filenames = contract.image_filenames
    value_slots = contract.value_slot_names
    return FinishedReportResponse(
        run_id=record.run_id,
        status=record.report_status or "draft",
        page_count=len(record.previews),
        filename=record.filename or "",
        download_url=f"/api/runs/{record.run_id}/download",
        pendencias=[
            PendenciaOut(
                classification=item["classification"],
                classification_label=classification_label(
                    item["classification"]
                ),
                classification_explanation=_CLASSIFICATION_EXPLANATIONS.get(
                    item["classification"], ""
                ),
                name=item["name"],
                required_action=item["required_action"],
                page=item["page"],
                preview_page=item.get("preview_page"),
                attachment_filename=(
                    image_filenames.get(str(item.get("slot")))
                    or (VALUES_FILE if item.get("slot") in value_slots else None)
                    if item["classification"] == "GATED"
                    else None
                ),
                attachment_value_key=(
                    str(item.get("slot"))
                    if item["classification"] == "GATED"
                    and item.get("slot") in value_slots
                    else None
                ),
            )
            for item in record.pendencias
        ],
        checks=[
            CheckOut(
                label=_GATE_LABELS.get(item["gate"], item["gate"]),
                passed=item["passed"],
            )
            for item in record.checks
        ],
    )


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
            tema=outcome.tema,
            demanda=outcome.demanda,
            razao_social=outcome.razao_social,
            especialista=outcome.especialista,
            kick_off=outcome.kick_off_br,
            capture_origin=outcome.capture_origin,
            published_domain=outcome.published_domain,
            report_ready_text=outcome.report_ready_text,
        )
        for outcome in outcomes
        if isinstance(outcome, Engagement)
    ]
    stop_conditions = [
        StopConditionOut(
            row=row_ref(outcome.row_number, pasta_by_row.get(outcome.row_number, "")),
            demanda=outcome.demanda,
            razao_social=outcome.razao_social,
            especialista=outcome.especialista,
            kick_off=outcome.kick_off_text,
            link=outcome.link_text,
            coluna=remedy.coluna,
            problema=remedy.problema,
            solucao=remedy.solucao,
            cause=outcome.cause,
            report_ready_text=outcome.report_ready_text,
        )
        for outcome in outcomes
        if isinstance(outcome, StopCondition)
        for remedy in (_STOP_CAUSES.get(outcome.cause, _UNTRANSLATED_CAUSE),)
    ]
    unsupported = [
        outcome for outcome in outcomes if isinstance(outcome, UnsupportedRow)
    ]
    return ControlSheetResponse(
        sheet_id=sheet_id,
        filename=filename,
        engagements=engagements,
        stop_conditions=stop_conditions,
        unsupported_rows=UnsupportedRowsOut(
            total=len(unsupported),
            rows=[
                UnsupportedRowOut(
                    row=row_ref(
                        outcome.row_number,
                        pasta_by_row.get(outcome.row_number, ""),
                    ),
                    tema=outcome.tema,
                    demanda=outcome.demanda,
                    razao_social=outcome.razao_social,
                    especialista=outcome.especialista,
                    kick_off=outcome.kick_off_text,
                    link=outcome.link_text,
                    report_ready_text=outcome.report_ready_text,
                    cause=outcome.reason,
                    explicacao=(
                        "Ainda não existe um Master aprovado para este Tema."
                    ),
                )
                for outcome in unsupported
            ],
        ),
    )


def create_app(
    *,
    static_dir: Path = DEFAULT_STATIC_DIR,
    sheet_store: SheetStore | None = None,
    app_password: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Relatórios SEBRAETEC")
    store = sheet_store if sheet_store is not None else default_sheet_store()
    app.state.run_service = default_run_service()
    app.state.app_password = resolve_password(app_password)

    @app.middleware("http")
    async def _require_session(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if is_public_path(request.url.path):
            return await call_next(request)
        if request_is_authenticated(request, app.state.app_password):
            return await call_next(request)
        return JSONResponse({"detail": UNAUTHENTICATED_DETAIL}, status_code=401)

    @app.middleware("http")
    async def _crawler_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = _X_ROBOTS_TAG
        response.headers["Referrer-Policy"] = _REFERRER_POLICY
        return response

    @app.get("/robots.txt")
    def robots_txt() -> PlainTextResponse:
        return PlainTextResponse(_ROBOTS_TXT)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/login")
    def login(body: LoginRequest) -> Response:
        secret = app.state.app_password
        if not passwords_match(body.password, secret):
            raise HTTPException(401, login_failed_detail())
        response = Response(status_code=204)
        set_session_cookie(response, secret)
        return response

    @app.post("/api/logout")
    def logout() -> Response:
        response = Response(status_code=204)
        clear_session_cookie(response)
        return response

    @app.get("/api/session")
    def session() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/control-sheet")
    async def control_sheet(file: UploadFile = File(...)) -> ControlSheetResponse:
        filename = file.filename or "planilha.xlsx"
        sheet_id, path = store.save(await file.read(), filename)
        try:
            outcomes, pasta_by_row = _read_sheet(path)
        except HTTPException:
            store.discard(sheet_id)
            raise
        return _build_response(
            sheet_id, filename, outcomes, pasta_by_row
        )

    @app.get("/api/control-sheet/{sheet_id}")
    def retained_control_sheet(sheet_id: str) -> ControlSheetResponse:
        path = store.path(sheet_id)
        if path is None:
            raise HTTPException(404, _EXPIRED_SHEET_DETAIL)
        outcomes, pasta_by_row = _read_sheet(path)
        return _build_response(
            sheet_id, store.filename(sheet_id), outcomes, pasta_by_row
        )

    @app.get("/api/control-sheets")
    def retained_control_sheets() -> list[RetainedSheetOut]:
        retained: list[RetainedSheetOut] = []
        for sheet in store.all():
            outcomes, _pasta_by_row = _read_sheet(sheet.path)
            retained.append(
                RetainedSheetOut(
                    sheet_id=sheet.sheet_id,
                    filename=sheet.filename,
                    uploaded_at=sheet.uploaded_at.isoformat(),
                    ready_count=sum(
                        isinstance(outcome, Engagement)
                        for outcome in outcomes
                    ),
                )
            )
        return retained

    @app.post("/api/runs", status_code=202)
    def start_run(request: StartRunRequest, response: Response) -> RunResponse:
        path = store.path(request.sheet_id)
        if path is None:
            raise HTTPException(404, _EXPIRED_SHEET_DETAIL)
        outcomes, _pasta_by_row = _read_sheet(path)
        engagement = next(
            (
                outcome
                for outcome in outcomes
                if isinstance(outcome, Engagement)
                and outcome.row_number == request.row_number
            ),
            None,
        )
        if engagement is None:
            raise HTTPException(
                422,
                "A linha escolhida não é um Engagement pronto para gerar.",
            )
        record = app.state.run_service.submit(engagement, request.sheet_id)
        response.headers["Location"] = f"/api/runs/{record.run_id}"
        return _run_response(record)

    @app.post("/api/batches", status_code=202)
    def start_batch(
        request: StartBatchRequest, response: Response
    ) -> BatchResponse:
        path = store.path(request.sheet_id)
        if path is None:
            raise HTTPException(404, _EXPIRED_SHEET_DETAIL)
        if not request.row_numbers:
            raise HTTPException(
                422, "Selecione pelo menos um Engagement para gerar."
            )
        if len(set(request.row_numbers)) != len(request.row_numbers):
            raise HTTPException(
                422, "Cada Engagement só pode aparecer uma vez no lote."
            )
        outcomes, _pasta_by_row = _read_sheet(path)
        engagements_by_row = {
            outcome.row_number: outcome
            for outcome in outcomes
            if isinstance(outcome, Engagement)
        }
        try:
            engagements = tuple(
                engagements_by_row[row_number]
                for row_number in request.row_numbers
            )
        except KeyError as error:
            raise HTTPException(
                422,
                "Uma das linhas escolhidas não é um Engagement pronto para gerar.",
            ) from error
        batch_id, records = app.state.run_service.submit_batch(
            engagements, request.sheet_id
        )
        response.headers["Location"] = f"/api/batches/{batch_id}"
        return BatchResponse(
            batch_id=batch_id,
            sheet_id=request.sheet_id,
            runs=[_run_response(record) for record in records],
        )

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str) -> BatchResponse:
        records = sorted(
            (
                record
                for record in app.state.run_service.store.all()
                if record.batch_id == batch_id
            ),
            key=lambda record: record.batch_position or 0,
        )
        if not records:
            raise HTTPException(404, "Este lote não existe ou expirou.")
        return BatchResponse(
            batch_id=batch_id,
            sheet_id=records[0].sheet_id,
            runs=[_run_response(record) for record in records],
        )

    @app.get("/api/runs")
    def past_runs() -> list[PastRunOut]:
        return [
            PastRunOut(
                run_id=record.run_id,
                razao_social=str(record.engagement.get("razao_social", "")),
                pasta=str(record.engagement.get("pasta", "")),
                demanda=str(record.engagement.get("demanda", "")),
                generated_at=record.updated_at,
                page_count=len(record.previews),
                status=record.report_status or "draft",
                filename=record.filename or "",
                review_url=f"/relatorios/{record.run_id}",
                download_url=f"/api/runs/{record.run_id}/download",
            )
            for record in app.state.run_service.retained_runs()
        ]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> RunResponse:
        record = app.state.run_service.store.get(run_id)
        if record is None:
            raise HTTPException(404, "Esta geração não existe ou expirou.")
        return _run_response(record)

    @app.get("/api/runs/{run_id}/download")
    def download_run(run_id: str) -> FileResponse:
        record = app.state.run_service.store.get(run_id)
        if (
            record is None
            or record.outcome != "finished"
            or record.document is None
            or record.filename is None
        ):
            raise HTTPException(
                404, "Esta geração não tem um documento para baixar."
            )
        document = Path(record.document)
        if not document.is_file():
            raise HTTPException(404, "O documento desta geração expirou.")
        return FileResponse(
            document,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            filename=record.filename,
        )

    @app.get("/api/runs/{run_id}/report")
    def get_report(run_id: str) -> FinishedReportResponse:
        record = app.state.run_service.store.get(run_id)
        if record is None or record.outcome != "finished" or record.document is None:
            raise HTTPException(
                404, "Esta geração ainda não tem um relatório para revisar."
            )
        return _report_response(record)

    @app.post("/api/runs/{run_id}/attachments", status_code=202)
    async def attach_gated_inputs(
        run_id: str,
        response: Response,
        files: list[UploadFile] = File(...),
    ) -> RunResponse:
        record = app.state.run_service.store.get(run_id)
        if record is None or record.outcome != "finished":
            raise HTTPException(404, "Este relatório não está disponível para anexos.")
        path = store.path(record.sheet_id)
        if path is None:
            raise HTTPException(404, _EXPIRED_SHEET_DETAIL)
        outcomes, _ = _read_sheet(path)
        engagement = next(
            (
                item for item in outcomes
                if isinstance(item, Engagement)
                and item.row_number == record.engagement["row_number"]
                and item.tema == record.tema
            ),
            None,
        )
        if engagement is None:
            raise HTTPException(422, "A Demanda deste relatório não pode ser refeita.")
        contract = supported_contract(record.tema)
        image_filenames = contract.image_filenames
        value_slots = contract.value_slot_names
        expected = {
            image_filenames.get(str(item.get("slot")))
            or (VALUES_FILE if item.get("slot") in value_slots else None)
            for item in record.pendencias
            if item.get("classification") == "GATED"
        } - {None}
        pending_value_slots = {
            str(item.get("slot"))
            for item in record.pendencias
            if item.get("classification") == "GATED"
            and item.get("slot") in value_slots
        }
        names = [file.filename or "" for file in files]
        unknown = sorted(set(names) - expected)
        if not files or unknown or len(names) != len(set(names)):
            reason = ", ".join(unknown) if unknown else "nomes repetidos ou nenhum arquivo"
            raise HTTPException(422, f"Anexo sem Pendência GATED correspondente: {reason}.")
        payloads = [(file.filename or "", await file.read()) for file in files]
        if VALUES_FILE in names:
            try:
                supplied_values = json.loads(dict(payloads)[VALUES_FILE])
            except (json.JSONDecodeError, UnicodeDecodeError):
                supplied_values = {}
            if not isinstance(supplied_values, dict) or not (
                set(supplied_values) & pending_value_slots
            ):
                raise HTTPException(
                    422,
                    "valores.json não satisfaz nenhuma Pendência GATED deste relatório.",
                )
        target = gated_drop_folder(app.state.run_service.gated_drop_root, engagement)
        with tempfile.TemporaryDirectory() as temporary:
            validation_root = Path(temporary)
            validation_folder = gated_drop_folder(validation_root, engagement)
            if target.exists():
                shutil.copytree(target, validation_folder)
            else:
                validation_folder.mkdir(parents=True)
            for name, content in payloads:
                (validation_folder / name).write_bytes(content)
            values_path = validation_folder / VALUES_FILE
            if not values_path.exists():
                values_path.write_text(
                    json.dumps(
                        {
                            "pasta": engagement.pasta,
                            "razao_social": engagement.razao_social,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            try:
                load_gated_inputs(validation_root, engagement)
            except GatedInputError as error:
                raise HTTPException(422, f"Anexo inválido: {error}") from error
            target.mkdir(parents=True, exist_ok=True)
            for validated in validation_folder.iterdir():
                shutil.copy2(validated, target / validated.name)
        rerun = app.state.run_service.submit(engagement, record.sheet_id)
        response.headers["Location"] = f"/api/runs/{rerun.run_id}"
        return _run_response(rerun)

    @app.get("/api/runs/{run_id}/previews/{page}")
    def get_preview_page(run_id: str, page: int) -> FileResponse:
        record = app.state.run_service.store.get(run_id)
        if record is None or record.outcome != "finished" or record.document is None:
            raise HTTPException(
                404, "Esta geração não tem páginas de prévia disponíveis."
            )
        # The renderer owns where its pages live and what they are called, so
        # the paths it recorded are followed rather than reconstructed here.
        if not 1 <= page <= len(record.previews):
            raise HTTPException(404, "Esta página não existe na prévia.")
        image_path = Path(record.previews[page - 1])
        if not image_path.is_file():
            raise HTTPException(404, "Esta página não existe na prévia.")
        return FileResponse(image_path, media_type="image/png")

    app.frontend(
        "/",
        directory=static_dir,
        fallback="index.html",
        check_dir=False,
    )
    return app


app = create_app()
