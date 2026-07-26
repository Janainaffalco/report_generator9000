from __future__ import annotations

from pathlib import Path

from fixtures.check_cli import run_check, write_context
from fixtures.docx_builder import build_docx, paragraph


def test_both_gates_pass_on_a_clean_document_and_context(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Razão Social: CLIENTE LTDA")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "drop_folder": "gated/115-2026",
            "capture_folder": "outputs/115-2026_CLIENTE/capturas",
            "output_paths": ["outputs/115-2026_CLIENTE/RELATORIO.docx"],
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GATE token-residue: PASS" in completed.stdout
    assert "GATE engagement-scope: PASS" in completed.stdout


def test_empty_run_context_leaves_engagement_scope_passing(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("nothing declared")],
    )

    completed = run_check(document, None)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GATE engagement-scope: PASS" in completed.stdout


def test_unreplaced_token_in_document_xml_is_reported(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Razão Social: {{RAZAO_SOCIAL}}")],
    )

    completed = run_check(document, None)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE token-residue: FAIL" in completed.stdout
    assert "unreplaced-token" in completed.stdout
    assert "word/document.xml" in completed.stdout
    assert "{{RAZAO_SOCIAL}}" in completed.stdout


def test_token_split_across_runs_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("{{RAZAO", "_SOCIAL}}")],
    )

    completed = run_check(document, None)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE token-residue: FAIL" in completed.stdout
    assert "token-split-across-runs" in completed.stdout
    assert "word/document.xml p=0" in completed.stdout
    assert "{{RAZAO_SOCIAL}}" in completed.stdout


def test_token_split_across_runs_not_double_reported_when_whole_elsewhere(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("{{RAZAO", "_SOCIAL}}"),
            paragraph("Nome fantasia: {{RAZAO_SOCIAL}}"),
        ],
    )

    completed = run_check(document, None)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE token-residue: FAIL" in completed.stdout
    assert "unreplaced-token" in completed.stdout
    assert "token-split-across-runs" not in completed.stdout
    assert completed.stdout.count("{{RAZAO_SOCIAL}}") == 1


def test_drop_folder_not_this_engagement_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {"pasta": "115-2026", "drop_folder": "gated/999-2026"},
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "drop-folder-not-this-engagement" in completed.stdout
    assert "gated/999-2026" in completed.stdout


def test_gated_input_outside_drop_folder_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "drop_folder": "gated/115-2026",
            "media": [
                {
                    "digest": "ab12",
                    "origin": "gated",
                    "label": "paleta",
                    "source": "gated/999-2026/paleta.png",
                }
            ],
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "gated-input-outside-drop-folder" in completed.stdout
    assert "paleta" in completed.stdout
    assert "gated/999-2026/paleta.png" in completed.stdout


def test_capture_outside_run_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "capture_folder": "outputs/115-2026_CLIENTE/capturas",
            "media": [
                {
                    "digest": "ab12",
                    "origin": "capture",
                    "label": "home",
                    "source": "outputs/999-2026_OUTRO/capturas/home.png",
                }
            ],
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "capture-outside-run" in completed.stdout
    assert "home" in completed.stdout


def test_output_path_outside_pasta_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "output_paths": ["outputs/999-2026_OUTRO/RELATORIO.docx"],
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "output-path-outside-pasta" in completed.stdout
    assert "outputs/999-2026_OUTRO/RELATORIO.docx" in completed.stdout


def test_capture_folder_not_this_engagement_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "capture_folder": "outputs/999-2026_OUTRO/capturas",
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "capture-folder-not-this-engagement" in completed.stdout
    assert "outputs/999-2026_OUTRO/capturas" in completed.stdout


def test_drop_folder_not_declared_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "media": [
                {
                    "digest": "ab12",
                    "origin": "gated",
                    "label": "paleta",
                    "source": "gated/115-2026/paleta.png",
                }
            ],
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "drop-folder-not-declared" in completed.stdout
    assert "gated/115-2026/paleta.png" in completed.stdout


def test_pasta_not_declared_is_reported(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {"drop_folder": "gated/115-2026"},
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "pasta-not-declared" in completed.stdout
    assert "run context" in completed.stdout


def test_pasta_not_declared_fires_for_a_media_artifact_source(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("body")],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": "ab12",
                    "origin": "gated",
                    "label": "paleta",
                    "source": "gated/115-2026/paleta.png",
                }
            ],
        },
    )

    completed = run_check(document, context)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE engagement-scope: FAIL" in completed.stdout
    assert "pasta-not-declared" in completed.stdout
    assert "run context" in completed.stdout
