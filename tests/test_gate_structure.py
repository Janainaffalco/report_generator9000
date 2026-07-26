from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from fixtures.docx_builder import (
    RelationshipSpec,
    build_docx,
    paragraph,
    png_bytes,
)


def write_context(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run_check(
    document: Path, context: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "report_generator9000.check",
            str(document),
            "--context",
            str(context),
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_a_well_formed_block_passes_both_gates(tmp_path: Path) -> None:
    image = png_bytes(2, 2)
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("SEÇÃO Exemplo", keep_next=True),
            paragraph(image="rIdImage1"),
        ],
        media={"media/image1.png": image},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": digest_of(image),
                    "origin": "capture",
                    "label": "Página Exemplo",
                }
            ],
            "blocks": ["SEÇÃO Exemplo"],
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GATE block-integrity: PASS" in completed.stdout
    assert "GATE pendencias-agreement: PASS" in completed.stdout


def test_heading_without_image_is_reported(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("SEÇÃO Órfã", keep_next=True)],
    )
    context_path = write_context(tmp_path / "run.json", {})

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE block-integrity: FAIL" in completed.stdout
    assert "heading-without-image" in completed.stdout
    assert "word/document.xml p=0" in completed.stdout
    assert "SEÇÃO Órfã" in completed.stdout


def test_block_heading_missing_is_reported(tmp_path: Path) -> None:
    image = png_bytes(2, 2)
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("SEÇÃO Exemplo", keep_next=True),
            paragraph(image="rIdImage1"),
        ],
        media={"media/image1.png": image},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": digest_of(image),
                    "origin": "capture",
                    "label": "Página Exemplo",
                }
            ],
            "blocks": ["SEÇÃO Ausente"],
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE block-integrity: FAIL" in completed.stdout
    assert "block-heading-missing" in completed.stdout
    assert "SEÇÃO Ausente" in completed.stdout


def test_orphaned_relationship_is_reported(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Texto qualquer")],
        relationships=[
            RelationshipSpec(id="rIdMissing", target="media/missing.png")
        ],
    )
    context_path = write_context(tmp_path / "run.json", {})

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE block-integrity: FAIL" in completed.stdout
    assert "orphaned-relationship" in completed.stdout
    assert "word/document.xml rIdMissing" in completed.stdout
    assert "media/missing.png" in completed.stdout


def test_unreferenced_media_is_reported(tmp_path: Path) -> None:
    image = png_bytes(2, 2)
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Texto qualquer")],
        media={"media/image1.png": image},
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": digest_of(image),
                    "origin": "capture",
                    "label": "Página Exemplo",
                }
            ],
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE block-integrity: FAIL" in completed.stdout
    assert "unreferenced-media" in completed.stdout
    assert "word/media/image1.png" in completed.stdout


def test_unreferenced_relationship_is_reported(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Texto qualquer, sem link nenhum")],
        relationships=[
            RelationshipSpec(
                id="rIdExternal",
                target="https://example.invalid/",
                kind="hyperlink",
                external=True,
            )
        ],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {"boilerplate_links": ["https://example.invalid/"]},
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE block-integrity: FAIL" in completed.stdout
    assert "unreferenced-relationship" in completed.stdout
    assert "word/document.xml rIdExternal" in completed.stdout
    assert "https://example.invalid/" in completed.stdout


def test_placeholder_without_pendencia_is_reported(tmp_path: Path) -> None:
    image = png_bytes(3, 3)
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph(image="rIdImg")],
        media={"media/placeholder.png": image},
        relationships=[
            RelationshipSpec(id="rIdImg", target="media/placeholder.png")
        ],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": digest_of(image),
                    "origin": "placeholder",
                    "label": "Print de tela indisponível",
                }
            ],
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE pendencias-agreement: FAIL" in completed.stdout
    assert "placeholder-without-pendencia" in completed.stdout
    assert "word/media/placeholder.png" in completed.stdout
    assert "Print de tela indisponível" in completed.stdout


def test_pendencia_without_evidence_missing_digest_is_reported(
    tmp_path: Path,
) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Nada de especial por aqui")],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "pendencias": [
                {
                    "slot": "paleta",
                    "classification": "GATED",
                    "reason": "não fornecida",
                    "evidence": "deadbeefcafe",
                }
            ]
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE pendencias-agreement: FAIL" in completed.stdout
    assert "pendencia-without-evidence" in completed.stdout
    assert "paleta" in completed.stdout
    assert "deadbeefcafe" in completed.stdout
    assert "GATED" in completed.stdout


def test_pendencia_without_evidence_missing_text_marker_is_reported(
    tmp_path: Path,
) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Nada de especial por aqui")],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "pendencias": [
                {
                    "slot": "dominio",
                    "classification": "TOOL_BLOCKED",
                    "reason": "falha na captura",
                    "evidence": "MARCADOR_AUSENTE_NO_DOCUMENTO",
                }
            ]
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE pendencias-agreement: FAIL" in completed.stdout
    assert "pendencia-without-evidence" in completed.stdout
    assert "dominio" in completed.stdout
    assert "MARCADOR_AUSENTE_NO_DOCUMENTO" in completed.stdout
    assert "TOOL_BLOCKED" in completed.stdout


def test_pendencia_evidence_as_text_marker_passes(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("PLACEHOLDER_LOGO_AUSENTE presente aqui")],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "pendencias": [
                {
                    "slot": "logo",
                    "classification": "GATED",
                    "reason": "não fornecida",
                    "evidence": "PLACEHOLDER_LOGO_AUSENTE",
                }
            ]
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GATE pendencias-agreement: PASS" in completed.stdout


def test_duplicate_pendencia_is_reported(tmp_path: Path) -> None:
    docx_path = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("MARCA_A e também MARCA_B nesta frase")],
    )
    context_path = write_context(
        tmp_path / "run.json",
        {
            "pendencias": [
                {
                    "slot": "paleta",
                    "classification": "GATED",
                    "reason": "não fornecida",
                    "evidence": "MARCA_A",
                },
                {
                    "slot": "paleta",
                    "classification": "GATED",
                    "reason": "não fornecida, segunda vez",
                    "evidence": "MARCA_B",
                },
            ]
        },
    )

    completed = run_check(docx_path, context_path)

    assert completed.returncode == 1
    assert "GATE pendencias-agreement: FAIL" in completed.stdout
    assert "duplicate-pendencia" in completed.stdout
    assert "paleta" in completed.stdout
