from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from fixtures.docx_builder import RelationshipSpec, build_docx, paragraph, png_bytes


PACKAGE = Path(__file__).resolve().parent.parent / "report_generator9000"

BOILERPLATE = png_bytes(8, 8, red=0x00, green=0x00, blue=0xFF)
CAPTURE = png_bytes(16, 9, red=0x00, green=0xC0, blue=0x00)
PLACEHOLDER = png_bytes(12, 4, red=0xF2, green=0xF2, blue=0xF2)
FOREIGN = png_bytes(20, 10, red=0x77, green=0x71, blue=0x71)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_check(document: Path, context: Path | None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "report_generator9000.check", str(document)]
    if context is not None:
        command.extend(["--context", str(context)])
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def write_context(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def clean_package(path: Path) -> Path:
    return build_docx(
        path,
        paragraphs=[
            paragraph("PÁGINA HOME", keep_next=True),
            paragraph(image="rIdCapture"),
            paragraph("CABEÇALHO", keep_next=True),
            paragraph(image="rIdBoilerplate"),
            paragraph("RODAPÉ", keep_next=True),
            paragraph(image="rIdPlaceholder"),
            paragraph("Acesse o painel", hyperlink="rIdPainel"),
            paragraph("Uso de CMS no mundo", hyperlink="rIdW3techs"),
        ],
        media={
            "media/image1.png": BOILERPLATE,
            "media/image2.png": CAPTURE,
            "media/image3.png": PLACEHOLDER,
        },
        relationships=[
            RelationshipSpec(id="rIdBoilerplate", target="media/image1.png"),
            RelationshipSpec(id="rIdCapture", target="media/image2.png"),
            RelationshipSpec(id="rIdPlaceholder", target="media/image3.png"),
            RelationshipSpec(
                id="rIdPainel",
                target="https://cliente.example/wp-admin/",
                kind="hyperlink",
                external=True,
            ),
            RelationshipSpec(
                id="rIdW3techs",
                target="https://w3techs.example/cms",
                kind="hyperlink",
                external=True,
            ),
        ],
    )


def clean_context(path: Path) -> Path:
    return write_context(
        path,
        {
            "pasta": "115-2026",
            "media": [
                {
                    "digest": digest(BOILERPLATE),
                    "origin": "boilerplate",
                    "label": "cabecalho SEBRAE",
                },
                {
                    "digest": digest(CAPTURE),
                    "origin": "capture",
                    "label": "PÁGINA HOME",
                    "source": "outputs/115-2026_CLIENTE/capturas/home.png",
                },
                {
                    "digest": digest(PLACEHOLDER),
                    "origin": "placeholder",
                    "label": "paleta",
                },
            ],
            "boilerplate_links": ["https://w3techs.example/cms"],
            "input_urls": ["https://cliente.example/"],
            "drop_folder": "gated/115-2026",
            "capture_folder": "outputs/115-2026_CLIENTE/capturas",
            "output_paths": ["outputs/115-2026_CLIENTE/RELATORIO_CLIENTE.docx"],
            "blocks": ["PÁGINA HOME", "CABEÇALHO", "RODAPÉ"],
            "pendencias": [
                {
                    "slot": "paleta",
                    "classification": "GATED",
                    "reason": "paleta não fornecida na pasta de entrada",
                    "evidence": digest(PLACEHOLDER),
                }
            ],
        },
    )


def test_a_package_with_full_provenance_passes_every_gate(tmp_path: Path) -> None:
    document = clean_package(tmp_path / "RELATORIO_CLIENTE.docx")
    context = clean_context(tmp_path / "run.json")

    completed = run_check(document, context)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip().endswith("PASSED 6 of 6 gates")
    for gate in (
        "media-provenance",
        "link-provenance",
        "token-residue",
        "engagement-scope",
        "block-integrity",
        "pendencias-agreement",
    ):
        assert f"GATE {gate}: PASS" in completed.stdout


def test_every_gate_names_its_rule_and_the_offending_artifact(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "RELATORIO_CLIENTE.docx",
        paragraphs=[
            paragraph("PÁGINA HOME", keep_next=True),
            paragraph(image="rIdCapture"),
            paragraph("SEÇÃO SOBRE", keep_next=True),
            paragraph("Razão social: {{RAZAO_SOCIAL}}"),
            paragraph("Acesse o painel", hyperlink="rIdPainel"),
        ],
        media={
            "media/image2.png": CAPTURE,
            "media/image4.png": FOREIGN,
            "media/image5.png": PLACEHOLDER,
        },
        relationships=[
            RelationshipSpec(id="rIdCapture", target="media/image2.png"),
            RelationshipSpec(id="rIdForeign", target="media/image4.png"),
            RelationshipSpec(id="rIdGone", target="media/image9.png"),
            RelationshipSpec(
                id="rIdPainel",
                target="https://outrocliente.example/wp-admin/",
                kind="hyperlink",
                external=True,
            ),
        ],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "media": [
                {
                    "digest": digest(CAPTURE),
                    "origin": "capture",
                    "label": "PÁGINA HOME",
                    "source": "outputs/115-2026_CLIENTE/capturas/home.png",
                },
                {
                    "digest": digest(PLACEHOLDER),
                    "origin": "placeholder",
                    "label": "paleta",
                },
            ],
            "input_urls": ["https://cliente.example/"],
            "drop_folder": "gated/999-2026",
            "capture_folder": "outputs/115-2026_CLIENTE/capturas",
            "output_paths": ["outputs/115-2026_CLIENTE/RELATORIO_CLIENTE.docx"],
            "blocks": ["PÁGINA HOME", "SEÇÃO SOBRE", "RODAPÉ"],
            "pendencias": [],
        },
    )

    completed = run_check(document, context)
    output = completed.stdout

    assert completed.returncode == 1, output + completed.stderr
    assert "FAILED 6 of 6 gates" in output

    assert "media-without-provenance\tword/media/image4.png" in output
    assert "link-without-provenance" in output
    assert "https://outrocliente.example/wp-admin/" in output
    assert "unreplaced-token\tword/document.xml\t{{RAZAO_SOCIAL}}" in output
    assert "drop-folder-not-this-engagement\tgated/999-2026" in output
    assert "heading-without-image\tword/document.xml p=2\tSEÇÃO SOBRE" in output
    assert "block-heading-missing\tRODAPÉ" in output
    assert "orphaned-relationship\tword/document.xml rIdGone" in output
    assert "unreferenced-relationship\tword/document.xml rIdForeign" in output
    assert "placeholder-without-pendencia\tword/media/image5.png" in output


def test_a_package_is_reported_gate_by_gate_without_a_run_context(
    tmp_path: Path,
) -> None:
    document = clean_package(tmp_path / "RELATORIO_CLIENTE.docx")

    completed = run_check(document, None)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE media-provenance: FAIL (3 violations)" in completed.stdout
    assert "GATE link-provenance: FAIL (2 violations)" in completed.stdout
    assert "GATE token-residue: PASS" in completed.stdout
    assert "GATE engagement-scope: PASS" in completed.stdout


def test_the_gates_import_nothing_beyond_the_standard_library() -> None:
    imported: set[str] = set()
    for module in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add((node.module or "").split(".")[0])

    outside = sorted(
        name
        for name in imported
        if name and name not in sys.stdlib_module_names
    )

    assert outside == []
