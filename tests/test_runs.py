from __future__ import annotations

from dataclasses import replace
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from report_generator9000.control_sheet import Engagement
from report_generator9000.previews import RenderFailed, RenderRejected
from report_generator9000.runs import (
    GateRejected,
    PACKAGED_MASTER_PATH,
    RunService,
    RunStore,
    STAGES,
    default_run_service,
)
from report_generator9000.tema import WEBSITE_TEMA, contract_for


def _engagement() -> Engagement:
    return Engagement(
        row_number=2,
        demanda="011616/2026",
        pasta="40-2026",
        razao_social="DENISE BARROS DE ALMEIDA",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin="https://example.test/",
        published_domain=None,
    )


def _service(tmp_path: Path, assembler) -> RunService:
    return RunService(
        store=RunStore(tmp_path / "runs"),
        master=tmp_path / "MASTER.docx",
        output_root=tmp_path / "outputs",
        gated_drop_root=tmp_path / "gated",
        assembler=assembler,
        no_llm=True,
    )


def test_default_run_service_uses_the_versioned_master(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPORT_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("REPORT_MASTER_PATH", raising=False)

    service = default_run_service()
    try:
        assert service.master == PACKAGED_MASTER_PATH
        assert service.master.is_file()
    finally:
        service.shutdown()


def test_default_run_service_fails_at_startup_for_a_missing_master_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-MASTER.docx"
    monkeypatch.setenv("REPORT_MASTER_PATH", str(missing))

    with pytest.raises(RuntimeError, match="configured Master does not exist"):
        default_run_service()


def test_master_override_must_match_the_web_site_tema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_master = tmp_path / "loja-master.docx"
    with ZipFile(PACKAGED_MASTER_PATH) as source, ZipFile(other_master, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "word/document.xml":
                content = content.replace(
                    b"DESENVOLVIMENTO DE WEBSITE",
                    b"IMPLANTACAO DE LOJA VIRTUAL",
                )
            target.writestr(item, content)
    monkeypatch.setenv("REPORT_MASTER_PATH", str(other_master))

    with pytest.raises(RuntimeError, match="does not match the WebSite Tema"):
        default_run_service()


def test_tema_contract_selects_both_approved_masters() -> None:
    website = contract_for(WEBSITE_TEMA)
    loja = contract_for("Implantacao de Loja Virtual")

    assert website is not None and website.supported
    assert website.master == PACKAGED_MASTER_PATH
    assert website.spreadsheet_tokens
    assert website.master_gate is not None
    assert website.gated_value_slots and website.gated_image_slots
    assert website.boilerplate_media and website.gates
    assert loja is not None and loja.supported
    assert loja.master is not None and loja.master.is_file()
    assert loja.master != website.master
    assert loja.master_gate is not None and loja.gates


def test_run_store_retains_sheet_tema_without_reconstructing_it(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    engagement = replace(
        _engagement(), tema="Insercao digital - Desenvolvimento de WebSite"
    )
    record = store.create(engagement, "sheet-1", batch_id="batch-1")
    restored = store.get(record.run_id)

    assert restored is not None
    assert restored.tema == engagement.tema
    assert restored.engagement["tema"] == engagement.tema
    assert restored.batch_id == "batch-1"


def test_legacy_web_site_run_is_migrated_by_schema_not_filename(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    record = store.create(_engagement(), "sheet-1")
    path = store.directory / f"{record.run_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["tema"]
    del payload["engagement"]["tema"]
    del payload["schema_version"]
    payload["filename"] = "Implantacao de Loja Virtual.docx"
    path.write_text(json.dumps(payload), encoding="utf-8")

    restored = store.get(record.run_id)

    assert restored is not None
    assert restored.tema == WEBSITE_TEMA
    assert restored.engagement["tema"] == WEBSITE_TEMA


def test_unexpected_exception_puts_traceback_in_run_log_and_keeps_reason(
    tmp_path, recording_sink
) -> None:
    def boom(*args, **options):
        raise KeyError("missing-thing")

    service = _service(tmp_path, boom)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    finished = service.store.get(record.run_id)
    assert finished is not None
    assert finished.outcome == "failed"
    assert finished.reason == str(KeyError("missing-thing"))

    error_events = [
        event
        for event in recording_sink.events
        if event.run_id == record.run_id and event.severity == "error"
    ]
    assert error_events
    tracebacks = [
        event.detail.get("traceback")
        for event in error_events
        if "traceback" in event.detail
    ]
    assert tracebacks
    assert any("KeyError" in tb for tb in tracebacks)


def test_a_gate_rejection_stays_distinct_from_an_infrastructure_failure(
    tmp_path,
) -> None:
    """Only a gate that conferred the document may report "rejected".

    A crash and a rejection mean opposite things to a consultant: one says
    the report was inspected and found defective, the other says no report
    exists. Collapsing them sends them to look at a document that was never
    produced.
    """

    def rejected(*args, **options):
        raise GateRejected("as conferências recusaram o documento")

    service = _service(tmp_path, rejected)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    finished = service.store.get(record.run_id)
    assert finished is not None
    assert finished.outcome == "rejected"


def test_render_failure_marks_run_failed_with_no_document_or_pdf(
    tmp_path: Path,
) -> None:
    """A render that breaks the pipeline is "failed", never "rejected" or
    "finished" -- nothing was produced for a consultant to inspect, and no
    stale document or PDF may linger on the record -- issue #47 item 3."""

    def boom(*args, **options):
        raise RenderFailed("soffice exploded rendering the PDF")

    service = _service(tmp_path, boom)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    finished = service.store.get(record.run_id)
    assert finished is not None
    assert finished.outcome == "failed"
    assert finished.reason == "soffice exploded rendering the PDF"
    assert finished.document is None
    assert finished.filename is None
    assert finished.pdf is None
    assert finished.pdf_filename is None


def test_render_rejection_marks_run_rejected(tmp_path: Path) -> None:
    """Visual validation failing the render is a rejection, distinct from an
    infrastructure failure -- something was produced and inspected, and
    found defective -- issue #47 item 3."""

    def rejected(*args, **options):
        raise RenderRejected(
            "STOP CONDITION: the rendered PDF has zero pages"
        )

    service = _service(tmp_path, rejected)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    finished = service.store.get(record.run_id)
    assert finished is not None
    assert finished.outcome == "rejected"
    assert finished.document is None
    assert finished.pdf is None
    assert finished.pdf_filename is None


def test_expiring_the_output_directory_takes_the_pdf_and_previews_with_it(
    tmp_path: Path, recording_sink
) -> None:
    """The PDF and preview pages belong to the same Pasta directory as the
    DOCX, so the seven-day retention sweep that removes an expired Pasta
    removes them too -- issue #47 item 4."""
    output_root = tmp_path / "outputs"
    document_dir = output_root / "old-run"
    document_dir.mkdir(parents=True)
    document = document_dir / "report.docx"
    document.write_bytes(b"stale")
    pdf = document_dir / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 stale")
    previews_dir = document_dir / "previews"
    previews_dir.mkdir()
    preview = previews_dir / "preview-001.png"
    preview.write_bytes(b"stale preview")

    store = RunStore(tmp_path / "runs")
    record = store.create(_engagement(), sheet_id="sheet-1")
    expired = replace(
        record,
        updated_at=(
            datetime.now(UTC) - timedelta(days=30)
        ).isoformat(),
        document=str(document),
        pdf=str(pdf),
        pdf_filename="report.pdf",
    )
    store._write(expired)

    def assemble(master, out_root, engagement, gated_root, **options):
        raise AssertionError("assembler should not run in this test")

    service = RunService(
        store=store,
        master=tmp_path / "MASTER.docx",
        output_root=output_root,
        gated_drop_root=tmp_path / "gated",
        assembler=assemble,
        no_llm=True,
    )
    service.submit(_engagement(), sheet_id="sheet-2")
    service.shutdown()

    assert not document_dir.exists()
    assert not pdf.exists()
    assert not preview.exists()


def test_successful_run_records_pdf_alongside_the_document(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "outputs" / "report.pdf"

    def assemble(master, output_root, engagement, gated_root, **options):
        progress = options["progress"]
        for stage_name in STAGES:
            progress(stage_name, 3 if stage_name == "derive_pages" else None)
        document = output_root / "report.docx"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b"generated docx")
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        return SimpleNamespace(
            pages=(object(), object(), object()),
            previews=(),
            pdf=pdf_path,
            report=SimpleNamespace(
                status="draft",
                document=document,
                gate_report=SimpleNamespace(results=()),
                context=SimpleNamespace(pendencias=()),
            ),
        )

    service = _service(tmp_path, assemble)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    finished = service.store.get(record.run_id)
    assert finished is not None
    assert finished.outcome == "finished"
    assert finished.pdf == str(pdf_path.resolve())
    assert finished.pdf_filename == "report.pdf"


def test_worker_thread_events_carry_run_id(tmp_path, recording_sink) -> None:
    def assemble(master, output_root, engagement, gated_root, **options):
        progress = options["progress"]
        for stage_name in STAGES:
            progress(stage_name, 3 if stage_name == "derive_pages" else None)
        document = output_root / "report.docx"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b"generated docx")
        return SimpleNamespace(
            pages=(object(), object(), object()),
            report=SimpleNamespace(status="draft", document=document),
        )

    service = _service(tmp_path, assemble)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    stage_events = [
        event
        for event in recording_sink.events
        if event.kind == "stage" and event.run_id == record.run_id
    ]
    assert stage_events
    assert all(event.run_id == record.run_id for event in stage_events)


def test_load_emits_warning_on_corrupt_record_and_returns_none(
    tmp_path, recording_sink
) -> None:
    store = RunStore(tmp_path / "runs")
    store.directory.mkdir(parents=True, exist_ok=True)
    path = store.directory / "bad-run.json"
    path.write_text("{ not valid json", encoding="utf-8")

    record = store._load(path)

    assert record is None
    warnings = [
        event
        for event in recording_sink.events
        if event.severity == "warning"
    ]
    assert warnings
    assert any(
        str(path) in str(event.fields.get("path")) for event in warnings
    )


def test_load_emits_nothing_for_missing_file(tmp_path, recording_sink) -> None:
    store = RunStore(tmp_path / "runs")
    store.directory.mkdir(parents=True, exist_ok=True)
    path = store.directory / "does-not-exist.json"

    record = store._load(path)

    assert record is None
    assert recording_sink.events == []


def test_get_unlinks_sibling_log_for_expired_record(
    tmp_path, recording_sink
) -> None:
    store = RunStore(tmp_path / "runs")
    record = store.create(_engagement(), sheet_id="sheet-1")
    expired = replace(
        record,
        updated_at=(
            datetime.now(UTC) - timedelta(days=30)
        ).isoformat(),
    )
    store._write(expired)
    log_path = store.directory / f"{record.run_id}.log"
    log_path.write_text("some log line\n", encoding="utf-8")

    result = store.get(record.run_id)

    assert result is None
    assert not (store.directory / f"{record.run_id}.json").exists()
    assert not log_path.exists()

    notices = [
        event
        for event in recording_sink.events
        if event.kind == "notice"
    ]
    assert notices


def test_discard_expired_unlinks_sibling_log(tmp_path, recording_sink) -> None:
    store = RunStore(tmp_path / "runs")
    record = store.create(_engagement(), sheet_id="sheet-1")
    expired = replace(
        record,
        updated_at=(
            datetime.now(UTC) - timedelta(days=30)
        ).isoformat(),
    )
    store._write(expired)
    log_path = store.directory / f"{record.run_id}.log"
    log_path.write_text("some log line\n", encoding="utf-8")

    expired_records = store.discard_expired()

    assert len(expired_records) == 1
    assert not (store.directory / f"{record.run_id}.json").exists()
    assert not log_path.exists()

    notices = [
        event
        for event in recording_sink.events
        if event.kind == "notice"
    ]
    assert notices


def test_removing_expired_output_directory_emits_notice(
    tmp_path, recording_sink
) -> None:
    output_root = tmp_path / "outputs"
    document_dir = output_root / "old-run"
    document_dir.mkdir(parents=True)
    document = document_dir / "report.docx"
    document.write_bytes(b"stale")

    store = RunStore(tmp_path / "runs")
    record = store.create(_engagement(), sheet_id="sheet-1")
    expired = replace(
        record,
        updated_at=(
            datetime.now(UTC) - timedelta(days=30)
        ).isoformat(),
        document=str(document),
    )
    store._write(expired)

    def assemble(master, out_root, engagement, gated_root, **options):
        raise AssertionError("assembler should not run in this test")

    service = RunService(
        store=store,
        master=tmp_path / "MASTER.docx",
        output_root=output_root,
        gated_drop_root=tmp_path / "gated",
        assembler=assemble,
        no_llm=True,
    )
    service.submit(_engagement(), sheet_id="sheet-2")
    service.shutdown()

    assert not document_dir.exists()
    rmtree_notices = [
        event
        for event in recording_sink.events
        if event.name == "run_output_directory_removed"
    ]
    assert rmtree_notices


def test_successful_run_emits_one_stage_event_per_stage_in_order_no_duration(
    tmp_path, recording_sink
) -> None:
    def assemble(master, output_root, engagement, gated_root, **options):
        progress = options["progress"]
        for stage_name in STAGES:
            progress(stage_name, 3 if stage_name == "derive_pages" else None)
        document = output_root / "report.docx"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(b"generated docx")
        return SimpleNamespace(
            pages=(object(), object(), object()),
            report=SimpleNamespace(status="draft", document=document),
        )

    service = _service(tmp_path, assemble)
    record = service.submit(_engagement(), sheet_id="sheet-1")
    service.shutdown()

    stage_events = [
        event
        for event in recording_sink.events
        if event.kind == "stage" and event.run_id == record.run_id
    ]
    assert [event.name for event in stage_events] == list(STAGES)
    assert all(event.duration_ms is None for event in stage_events)
