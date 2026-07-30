"""Durable, pollable execution of one Engagement at a time."""

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
from .prose import ProseConfig, ProseProvider
from .retention import RETENTION
from .run_context import Pendencia


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
RunOutcome = Literal["running", "finished", "stopped", "rejected"]

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


class RunStore:
    """JSON records retained on disk so navigation does not own a run."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = RLock()

    def create(self, engagement: Engagement, sheet_id: str) -> RunRecord:
        now = datetime.now(UTC).isoformat()
        record = RunRecord(
            run_id=uuid4().hex,
            sheet_id=sheet_id,
            engagement={
                "row_number": engagement.row_number,
                "pasta": engagement.pasta,
                "razao_social": engagement.razao_social,
            },
            outcome="running",
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
    pendencias: tuple[Pendencia, ...]
) -> tuple[dict[str, object], ...]:
    """Translate Pendências into the durable shape a RunRecord stores."""
    return tuple(
        {
            "slot": item.slot,
            "classification": item.classification,
            "name": item.name,
            "page": item.page,
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
            max_workers=2, thread_name_prefix="report-run"
        )

    def submit(self, engagement: Engagement, sheet_id: str) -> RunRecord:
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
        record = self.store.create(engagement, sheet_id)
        record = self.store.update(record.run_id, current_stage=STAGES[0])
        self._executor.submit(self._execute, record.run_id, engagement)
        return record

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _execute(self, run_id: str, engagement: Engagement) -> None:
        with run_scope(run_id):
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
            if not self.no_llm and provider is None:
                settings = GeminiSettings.from_environment()
                managed_provider = GeminiProseProvider(settings)
                provider = managed_provider
                config = settings.prose_config()
            package = self.assembler(
                self.master,
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
            self._terminal(run_id, "rejected", str(error))
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
                pendencias=_pendencia_dicts(package.report.context.pendencias),
                previews=tuple(
                    str(path.resolve()) for path in package.previews
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
            reason=reason,
        )


def default_run_service() -> RunService:
    data_root = Path(os.environ.get("REPORT_DATA_ROOT", "/app/data"))
    master = Path(
        os.environ.get("REPORT_MASTER_PATH", str(PACKAGED_MASTER_PATH))
    )
    if not master.is_file():
        raise RuntimeError(
            f"configured Master does not exist or is not a file: {master}"
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
