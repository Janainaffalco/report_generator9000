"""Durable, pollable execution of Engagements, one at a time."""

from __future__ import annotations

import json
import os
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Callable, Literal
from uuid import uuid4

from .assembly import OutputPackage, ProgressCallback, assemble_output_package
from .control_sheet import Engagement
from .events import configure_logging, notice, run_scope
from .events import stage as emit_stage
from .gates.results import GateReport
from .generate import GateRejected, StopCondition
from .gemini_provider import (
    GeminiProseProvider,
    GeminiSettings,
)
from .previews import PreviewRender
from .prose import ProseConfig, ProseProvider
from .retention import RETENTION
from .run_context import Pendencia, load_run_context
from .tema import WEBSITE_TEMA, supported_contract


StageName = Literal[
    "read_row",
    "open_origin",
    "derive_pages",
    "capture",
    "derive_palette",
    "capture_logo",
    "draft_prose",
    "assemble",
    "gate",
]
RunOutcome = Literal[
    "queued", "running", "finished", "stopped", "rejected", "failed"
]

STAGES: tuple[StageName, ...] = (
    "read_row",
    "open_origin",
    "derive_pages",
    "capture",
    "derive_palette",
    "capture_logo",
    "draft_prose",
    "assemble",
    "gate",
)
PACKAGED_MASTER_PATH = Path(__file__).with_name("assets") / "MASTER.docx"


@dataclass(frozen=True)
class RunRecord:
    """One run's durable state.

    ``page_count`` is the size of the Lista de Páginas — how many pages the
    client's site has — which is what the working screen announces once
    ``derive_pages`` discovers it. It is *not* how many pages the generated
    document has: each page of the site becomes a Block, a Block spans more
    than one page in Word, and the report carries matter that comes from no
    page of the site at all. Anything paging through the document counts
    ``previews`` instead.
    """

    run_id: str
    sheet_id: str
    tema: str
    engagement: dict[str, object]
    outcome: RunOutcome
    current_stage: StageName | None
    completed_stages: tuple[StageName, ...]
    stage_history: tuple[StageName, ...]
    page_count: int | None
    report_status: str | None
    filename: str | None
    document: str | None
    reason: str | None
    created_at: str
    updated_at: str
    checks: tuple[dict[str, object], ...] = ()
    pendencias: tuple[dict[str, object], ...] = ()
    previews: tuple[str, ...] = ()
    batch_id: str | None = None
    batch_position: int | None = None
    batch_size: int | None = None
    schema_version: int = 2
    pdf: str | None = None
    pdf_filename: str | None = None


class RunStore:
    """JSON records retained on disk so navigation does not own a run."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = RLock()

    def create(
        self,
        engagement: Engagement,
        sheet_id: str,
        *,
        outcome: RunOutcome = "running",
        batch_id: str | None = None,
        batch_position: int | None = None,
        batch_size: int | None = None,
    ) -> RunRecord:
        now = datetime.now(UTC).isoformat()
        record = RunRecord(
            run_id=uuid4().hex,
            sheet_id=sheet_id,
            tema=engagement.tema,
            engagement={
                "row_number": engagement.row_number,
                "tema": engagement.tema,
                "pasta": engagement.pasta,
                "demanda": engagement.demanda,
                "razao_social": engagement.razao_social,
            },
            outcome=outcome,
            current_stage=None,
            completed_stages=(),
            stage_history=(),
            page_count=None,
            report_status=None,
            filename=None,
            document=None,
            reason=None,
            created_at=now,
            updated_at=now,
            checks=(),
            pendencias=(),
            previews=(),
            batch_id=batch_id,
            batch_position=batch_position,
            batch_size=batch_size,
        )
        self._write(record)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        path = self.directory / f"{run_id}.json"
        record = self._load(path)
        if record is None:
            return None
        if datetime.fromisoformat(record.updated_at) < (
            datetime.now(UTC) - RETENTION
        ):
            path.unlink(missing_ok=True)
            path.with_suffix(".log").unlink(missing_ok=True)
            notice(
                "run_expired_on_read",
                severity="info",
                expired_run_id=record.run_id,
                path=str(path),
            )
            return None
        return record

    def _load(self, path: Path) -> RunRecord | None:
        with self._lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (json.JSONDecodeError, OSError) as error:
                notice(
                    "run_record_load_failed",
                    severity="warning",
                    path=str(path),
                    error=type(error).__name__,
                )
                return None
        payload["completed_stages"] = tuple(payload["completed_stages"])
        payload["stage_history"] = tuple(payload["stage_history"])
        payload["checks"] = tuple(payload.get("checks", ()))
        payload["pendencias"] = tuple(payload.get("pendencias", ()))
        payload["previews"] = tuple(payload.get("previews", ()))
        if payload.get("schema_version", 1) == 1 and "tema" not in payload:
            # The previous record schema could only run WebSite. Migrate by
            # that known schema, never by Demanda, domain, or filename.
            payload["tema"] = WEBSITE_TEMA
            payload["engagement"]["tema"] = WEBSITE_TEMA
            payload["schema_version"] = 2
        if not isinstance(payload.get("tema"), str) or not payload["tema"]:
            notice("run_record_missing_tema", severity="warning", path=str(path))
            return None
        return RunRecord(**payload)

    def update(self, run_id: str, **changes: object) -> RunRecord:
        with self._lock:
            record = self.get(run_id)
            if record is None:
                raise KeyError(run_id)
            updated = replace(
                record,
                **changes,
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._write(updated)
            return updated

    def all(self) -> tuple[RunRecord, ...]:
        self.directory.mkdir(parents=True, exist_ok=True)
        return tuple(
            record
            for path in self.directory.glob("*.json")
            if (record := self.get(path.stem)) is not None
        )

    def delete(self, run_id: str) -> None:
        with self._lock:
            (self.directory / f"{run_id}.json").unlink(missing_ok=True)
            (self.directory / f"{run_id}.log").unlink(missing_ok=True)

    def discard_expired(self) -> tuple[RunRecord, ...]:
        cutoff = datetime.now(UTC) - RETENTION
        expired: list[RunRecord] = []
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*.json"):
            record = self._load(path)
            if record is None:
                continue
            if datetime.fromisoformat(record.updated_at) < cutoff:
                expired.append(record)
                path.unlink(missing_ok=True)
                path.with_suffix(".log").unlink(missing_ok=True)
                notice(
                    "run_discarded_expired",
                    severity="info",
                    expired_run_id=record.run_id,
                    path=str(path),
                )
        return tuple(expired)

    def _write(self, record: RunRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{record.run_id}.json"
        temporary = path.with_suffix(".json.tmp")
        with self._lock:
            temporary.write_text(
                json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)


Assembler = Callable[..., OutputPackage]


def _check_dicts(gate_report: GateReport) -> tuple[dict[str, object], ...]:
    """Translate a GateReport into the durable shape a RunRecord stores."""
    return tuple(
        {"gate": item.gate, "passed": item.passed}
        for item in gate_report.results
    )


def _pendencia_dicts(
    pendencias: tuple[Pendencia, ...],
    preview_render: PreviewRender | None = None,
) -> tuple[dict[str, object], ...]:
    """Translate Pendências into the durable shape a RunRecord stores."""
    return tuple(
        {
            "slot": item.slot,
            "classification": item.classification,
            "name": item.name,
            "page": item.page,
            "preview_page": (
                preview_render.page_for_evidence(item.evidence)
                if preview_render is not None
                else None
            ),
            "required_action": item.required_action,
        }
        for item in pendencias
    )


class RunService:
    """Own background workers and translate library outcomes into run records."""

    def __init__(
        self,
        *,
        store: RunStore,
        master: Path,
        output_root: Path,
        gated_drop_root: Path,
        assembler: Assembler = assemble_output_package,
        prose_provider: ProseProvider | None = None,
        prose_config: ProseConfig | None = None,
        no_llm: bool = False,
    ) -> None:
        self.store = store
        self.master = master
        self.output_root = output_root
        self.gated_drop_root = gated_drop_root
        self.assembler = assembler
        self.prose_provider = prose_provider
        self.prose_config = prose_config
        self.no_llm = no_llm
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="report-run"
        )

    def submit(self, engagement: Engagement, sheet_id: str) -> RunRecord:
        supported_contract(engagement.tema)
        self._discard_expired_outputs()
        record = self.store.create(engagement, sheet_id)
        record = self.store.update(record.run_id, current_stage=STAGES[0])
        self._executor.submit(self._execute, record.run_id, engagement)
        return record

    def retained_runs(self) -> tuple[RunRecord, ...]:
        """Discover the latest finished Run for each retained output package."""
        cutoff = datetime.now(UTC).timestamp() - RETENTION.total_seconds()
        records = tuple(
            record
            for record in self.store.all()
            if record.outcome == "finished" and record.document
        )
        retained: list[RunRecord] = []
        self.output_root.mkdir(parents=True, exist_ok=True)
        for directory in self.output_root.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            if directory.stat().st_mtime < cutoff:
                for record in records:
                    if Path(record.document or "").parent.resolve() == directory.resolve():
                        self.store.delete(record.run_id)
                shutil.rmtree(directory)
                shutil.rmtree(
                    self.gated_drop_root / directory.name,
                    ignore_errors=True,
                )
                continue
            try:
                context = load_run_context(directory / "run.json")
                pendencias_document = json.loads(
                    (directory / "pendencias.json").read_text(encoding="utf-8")
                )
            except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
                continue
            if not isinstance(pendencias_document, dict):
                continue
            matching = sorted(
                (
                    record
                    for record in records
                    if Path(record.document or "").parent.resolve()
                    == directory.resolve()
                ),
                key=lambda record: record.updated_at,
                reverse=True,
            )
            if not matching:
                continue
            previews = tuple(
                str(path.resolve())
                for path in sorted((directory / "previews").glob("*.png"))
            )
            document_path = Path(matching[0].document or "")
            pdf_path = document_path.with_suffix(".pdf")
            pdf_exists = pdf_path.is_file()
            retained.append(
                replace(
                    matching[0],
                    report_status=str(pendencias_document.get("status", "draft")),
                    pendencias=_pendencia_dicts(context.pendencias),
                    previews=previews,
                    pdf=str(pdf_path.resolve()) if pdf_exists else None,
                    pdf_filename=pdf_path.name if pdf_exists else None,
                )
            )
        return tuple(
            sorted(retained, key=lambda record: record.updated_at, reverse=True)
        )

    def submit_batch(
        self,
        engagements: tuple[Engagement, ...],
        sheet_id: str,
    ) -> tuple[str, tuple[RunRecord, ...]]:
        if not engagements:
            raise ValueError("a batch needs at least one Engagement")
        self._discard_expired_outputs()
        batch_id = uuid4().hex
        records = tuple(
            self.store.create(
                engagement,
                sheet_id,
                outcome="queued",
                batch_id=batch_id,
                batch_position=position,
                batch_size=len(engagements),
            )
            for position, engagement in enumerate(engagements, start=1)
        )
        for record, engagement in zip(records, engagements, strict=True):
            self._executor.submit(self._execute, record.run_id, engagement)
        return batch_id, records

    def _discard_expired_outputs(self) -> None:
        output_root = self.output_root.resolve()
        expired_records = self.store.discard_expired()
        active_documents = {
            str(Path(record.document).resolve())
            for record in self.store.all()
            if record.document is not None
        }
        for expired in expired_records:
            if expired.document is None:
                continue
            document = Path(expired.document).resolve()
            if (
                document.is_relative_to(output_root)
                and str(document) not in active_documents
            ):
                notice(
                    "run_output_directory_removed",
                    severity="info",
                    expired_run_id=expired.run_id,
                    path=str(document.parent),
                )
                shutil.rmtree(document.parent, ignore_errors=True)
                shutil.rmtree(
                    self.gated_drop_root / document.parent.name,
                    ignore_errors=True,
                )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _execute(self, run_id: str, engagement: Engagement) -> None:
        with run_scope(run_id):
            current = self.store.get(run_id)
            if current is None:
                return
            if current.outcome == "queued":
                self.store.update(
                    run_id,
                    outcome="running",
                    current_stage=STAGES[0],
                )
            self._execute_within_scope(run_id, engagement)

    def _execute_within_scope(
        self, run_id: str, engagement: Engagement
    ) -> None:
        def progress(stage: str, page_count: int | None = None) -> None:
            if stage not in STAGES:
                raise ValueError(f"unknown progress stage: {stage}")
            current = self.store.get(run_id)
            if current is None:
                return
            completed = [*current.completed_stages, stage]
            history = [*current.stage_history, stage]
            stage_name: StageName = stage
            position = STAGES.index(stage_name)
            self.store.update(
                run_id,
                current_stage=(
                    stage_name
                    if stage_name == "gate"
                    else STAGES[position + 1]
                    if position + 1 < len(STAGES)
                    else None
                ),
                completed_stages=tuple(dict.fromkeys(completed)),
                stage_history=tuple(history),
                page_count=(
                    page_count
                    if page_count is not None
                    else current.page_count
                ),
            )
            if page_count is not None:
                emit_stage(stage_name, page_count=page_count)
            else:
                emit_stage(stage_name)

        provider = self.prose_provider
        config = self.prose_config
        managed_provider: GeminiProseProvider | None = None
        try:
            current = self.store.get(run_id)
            if current is None or current.tema != engagement.tema:
                raise StopCondition("STOP CONDITION: Run Tema differs from Engagement")
            contract = supported_contract(current.tema)
            selected_master = (
                self.master if contract.name == WEBSITE_TEMA else contract.master
            )
            if not self.no_llm and provider is None:
                settings = GeminiSettings.from_environment()
                managed_provider = GeminiProseProvider(settings)
                provider = managed_provider
                config = settings.prose_config()
            package = self.assembler(
                selected_master,
                self.output_root,
                engagement,
                self.gated_drop_root,
                prose_provider=provider,
                prose_config=config,
                no_llm=self.no_llm,
                progress=progress,
            )
        except GateRejected as error:
            self._terminal(run_id, "rejected", str(error))
        except StopCondition as error:
            self._terminal(run_id, "stopped", str(error))
        except Exception as error:
            notice(
                "run_failed_unexpectedly",
                severity="error",
                error=type(error).__name__,
                detail={"traceback": traceback.format_exc()},
            )
            # Not "rejected": nothing conferred this document and found it
            # defective -- the pipeline broke before it could. Reporting a
            # browser timeout or a provider outage as a gate rejection sends
            # the consultant to inspect a report that was never produced.
            self._terminal(run_id, "failed", str(error))
        else:
            current = self.store.get(run_id)
            if current is None:
                return
            if current.stage_history != STAGES:
                self._terminal(
                    run_id,
                    "rejected",
                    "progress callback reported an incomplete or reordered "
                    "stage sequence",
                )
                return
            self.store.update(
                run_id,
                outcome="finished",
                current_stage=None,
                completed_stages=current.completed_stages,
                page_count=len(package.pages),
                report_status=package.report.status,
                filename=package.report.document.name,
                document=str(package.report.document.resolve()),
                reason=None,
                checks=_check_dicts(package.report.gate_report),
                pendencias=_pendencia_dicts(
                    package.report.context.pendencias,
                    getattr(package, "preview_render", None),
                ),
                previews=tuple(
                    str(path.resolve()) for path in package.previews
                ),
                pdf=(
                    str(package.pdf.resolve())
                    if getattr(package, "pdf", None) is not None
                    else None
                ),
                pdf_filename=(
                    package.pdf.name
                    if getattr(package, "pdf", None) is not None
                    else None
                ),
            )
        finally:
            if managed_provider is not None:
                managed_provider.close()

    def _terminal(
        self, run_id: str, outcome: RunOutcome, reason: str
    ) -> None:
        current = self.store.get(run_id)
        if current is None:
            return
        self.store.update(
            run_id,
            outcome=outcome,
            current_stage=None,
            completed_stages=current.completed_stages,
            document=None,
            filename=None,
            pdf=None,
            pdf_filename=None,
            reason=reason,
        )


def default_run_service() -> RunService:
    data_root = Path(os.environ.get("REPORT_DATA_ROOT", "/app/data"))
    from .tema import LOJA_VIRTUAL_TEMA

    contract = supported_contract(WEBSITE_TEMA)
    loja_contract = supported_contract(LOJA_VIRTUAL_TEMA)
    if loja_contract.master is None or not loja_contract.master.is_file():
        raise RuntimeError("versioned Loja Virtual Master does not exist")
    from .docx_package import open_docx_package

    assert loja_contract.master_gate is not None
    loja_validation = loja_contract.master_gate(open_docx_package(loja_contract.master))
    if not loja_validation.passed:
        raise RuntimeError("versioned Loja Virtual Master failed its sign-off gate")
    master = Path(os.environ.get("REPORT_MASTER_PATH", str(contract.master)))
    if not master.is_file():
        raise RuntimeError(
            f"configured Master does not exist or is not a file: {master}"
        )
    if "REPORT_MASTER_PATH" in os.environ:
        try:
            assert contract.master_gate is not None
            validation = contract.master_gate(open_docx_package(master))
        except (OSError, ValueError) as error:
            raise RuntimeError(
                f"configured Master is not a valid WebSite Master: {error}"
            ) from error
        if not validation.passed:
            raise RuntimeError(
                "configured Master does not match the WebSite Tema: "
                + ", ".join(item.rule for item in validation.violations)
            )
    configure_logging(run_log_directory=data_root / "runs")
    return RunService(
        store=RunStore(data_root / "runs"),
        master=master,
        output_root=data_root / "outputs",
        gated_drop_root=Path(
            os.environ.get(
                "REPORT_GATED_DROP_ROOT", str(data_root / "gated")
            )
        ),
    )


__all__ = [
    "GateRejected",
    "RunRecord",
    "RunService",
    "RunStore",
    "STAGES",
    "PACKAGED_MASTER_PATH",
    "default_run_service",
]
