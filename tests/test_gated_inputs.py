from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from fixtures.check_cli import run_check
from fixtures.docx_builder import (
    RelationshipSpec,
    build_docx,
    paragraph,
    png_bytes,
)
from report_generator9000.artifact_paths import engagement_artifact_key
from report_generator9000.control_sheet import (
    Engagement,
    read_control_sheet_for_pasta,
)
from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates.pendencias import check_pendencias_agreement
from report_generator9000.gates.provenance import check_media_provenance
from report_generator9000.gates.scope import check_engagement_scope
from report_generator9000.gated_inputs import gated_drop_folder
from report_generator9000.generate import report_output_path
from report_generator9000.master import build_master
from report_generator9000.run_context import load_run_context
from test_generate_report import run_generator


GATED_FIXTURES = Path(__file__).parent / "fixtures" / "gated"
CONTROL_SHEET = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"
ENGAGEMENT_FOLDER = "50-2026_LARI TORELLO CONSULTORIA LTDA"
IMAGE_PARTS = {
    "paleta.png": "word/media/image3.png",
    "login.png": "word/media/image13.png",
    "painel.png": "word/media/image14.png",
    "yoast-a.png": "word/media/image15.png",
    "yoast-b.png": "word/media/image16.png",
    "yoast-c.png": "word/media/image17.png",
    "drive.png": "word/media/image18.png",
    "kickoff.jpg": "word/media/image19.jpeg",
    "entrega.png": "word/media/image20.png",
}
GATED_TOKENS = {
    "{{PLANO_HOSPEDAGEM}}",
    "{{EMAIL_CLIENTE}}",
    "{{DATA_ENTREGA}}",
    "{{DATA_BACKUP}}",
    "{{LINK_CODIGO_FONTE}}",
    "{{LINK_GUIA_RAPIDO}}",
    "{{LINK_IDENTIDADE_VISUAL}}",
    "{{LINK_USUARIOS_SENHAS}}",
    "{{DOMINIO_PUBLICADO}}",
    "{{WP_ADMIN_URL}}",
}


def gated_master(path: Path) -> Path:
    paragraphs = [
        paragraph("{{DEMANDA}}"),
        paragraph("{{RAZAO_SOCIAL}}"),
        paragraph("{{CNPJ}}"),
        paragraph("{{ESPECIALISTA}}"),
        paragraph("{{DATA_KICKOFF}}"),
        *(paragraph(token) for token in sorted(GATED_TOKENS)),
        paragraph("{{SOBRE_A_EMPRESA}}"),
    ]
    relationships = []
    media = {}
    for index, target in enumerate(IMAGE_PARTS.values(), start=1):
        name = target.removeprefix("word/")
        relationship_id = f"rIdGated{index}"
        paragraphs.append(paragraph(image=relationship_id))
        relationships.append(
            RelationshipSpec(id=relationship_id, target=name)
        )
        media[name] = png_bytes(6 + index, 4 + index, blue=index * 13)
    return build_docx(
        path,
        paragraphs=paragraphs,
        media=media,
        relationships=relationships,
    )


def generated_document(completed_output: str) -> Path:
    return Path(
        next(
            line.split("\t", 1)[1]
            for line in completed_output.splitlines()
            if line.startswith("DOCX\t")
        )
    )


def test_output_and_gated_folder_share_the_canonical_engagement_key() -> None:
    engagement = next(
        outcome
        for outcome in read_control_sheet_for_pasta(
            CONTROL_SHEET, "50-2026"
        )
        if isinstance(outcome, Engagement)
    )

    assert engagement_artifact_key(engagement) == ENGAGEMENT_FOLDER
    assert (
        report_output_path("outputs", engagement).parent.name
        == gated_drop_folder("gated", engagement).name
    )


def test_complete_gated_folder_fills_values_images_and_provenance(
    tmp_path: Path,
) -> None:
    master = gated_master(tmp_path / "MASTER.docx")

    completed = run_generator(
        master,
        tmp_path / "reports",
        "50-2026",
        control_sheet=CONTROL_SHEET,
        gated_drop_root=GATED_FIXTURES / "complete",
    )

    assert completed.returncode == 0, completed.stderr
    output = generated_document(completed.stdout)
    package = open_docx_package(output)
    text = "\n".join(part.text or "" for part in package.parts)
    for expected in (
        "PLANO BUSINESS",
        "handoff@lari.example",
        "30/06/2026",
        "29/06/2026",
        "lari-publicado.example",
        "https://lari-publicado.example/wp-admin/",
        "https://drive.google.com/drive/folders/codigo",
        "https://drive.google.com/drive/folders/guia",
        "https://drive.google.com/drive/folders/visual",
        "https://drive.google.com/drive/folders/acessos",
    ):
        assert expected in text
    assert not any(token in text for token in GATED_TOKENS)
    assert "https://teal-duck-363012.hostingersite.com/" not in text
    with ZipFile(output) as generated:
        for filename, part_name in IMAGE_PARTS.items():
            assert generated.read(part_name) == (
                GATED_FIXTURES / "complete" / ENGAGEMENT_FOLDER / filename
            ).read_bytes()
    pendencias = json.loads(
        output.with_name("pendencias.json").read_text(encoding="utf-8")
    )
    assert pendencias == []
    context = json.loads(
        output.with_name("run.json").read_text(encoding="utf-8")
    )
    assert len(context["media"]) == len(IMAGE_PARTS)
    assert {item["origin"] for item in context["media"]} == {"gated"}
    assert all(
        ENGAGEMENT_FOLDER in item["source"] for item in context["media"]
    )
    run_context = load_run_context(output.with_name("run.json"))
    assert check_media_provenance(package, run_context).passed
    assert check_engagement_scope(package, run_context).passed
    assert check_pendencias_agreement(package, run_context).passed


def test_absent_gated_folder_is_a_normal_draft_with_explicit_pendencias(
    tmp_path: Path,
) -> None:
    master = gated_master(tmp_path / "MASTER.docx")
    with ZipFile(master) as source:
        original_images = {
            part_name: source.read(part_name)
            for part_name in IMAGE_PARTS.values()
        }

    completed = run_generator(
        master,
        tmp_path / "reports",
        "50-2026",
        control_sheet=CONTROL_SHEET,
        gated_drop_root=GATED_FIXTURES / "absent",
    )

    assert completed.returncode == 0, completed.stderr
    output = generated_document(completed.stdout)
    package = open_docx_package(output)
    text = "\n".join(part.text or "" for part in package.parts)
    assert not any(token in text for token in GATED_TOKENS)
    assert "PENDÊNCIA GATED: dominio_publicado" in text
    assert "https://teal-duck-363012.hostingersite.com/" not in text
    with ZipFile(output) as generated:
        assert all(
            generated.read(part_name) == content
            for part_name, content in original_images.items()
        )
    pendencias = json.loads(
        output.with_name("pendencias.json").read_text(encoding="utf-8")
    )
    assert len(pendencias) == 18
    assert {item["classification"] for item in pendencias} == {"GATED"}
    assert "GATED" in output.with_name("PENDENCIAS.md").read_text(
        encoding="utf-8"
    )
    run_context = load_run_context(output.with_name("run.json"))
    assert check_media_provenance(package, run_context).passed
    assert check_engagement_scope(package, run_context).passed
    assert check_pendencias_agreement(package, run_context).passed


def test_partial_gated_folder_fills_only_what_is_present(
    tmp_path: Path,
) -> None:
    master = gated_master(tmp_path / "MASTER.docx")
    completed = run_generator(
        master,
        tmp_path / "reports",
        "50-2026",
        control_sheet=CONTROL_SHEET,
        gated_drop_root=GATED_FIXTURES / "partial",
    )

    assert completed.returncode == 0, completed.stderr
    output = generated_document(completed.stdout)
    text = "\n".join(
        part.text or "" for part in open_docx_package(output).parts
    )
    assert "handoff-parcial@lari.example" in text
    assert "lari-parcial.example" in text
    assert "https://lari-parcial.example/wp-admin/" in text
    assert "PENDÊNCIA GATED: plano_hospedagem" in text
    with ZipFile(output) as generated:
        assert generated.read("word/media/image3.png") == (
            GATED_FIXTURES / "partial" / ENGAGEMENT_FOLDER / "paleta.png"
        ).read_bytes()
    pendencias = json.loads(
        output.with_name("pendencias.json").read_text(encoding="utf-8")
    )
    missing_slots = {item["slot"] for item in pendencias}
    assert "paleta" not in missing_slots
    assert "email_cliente" not in missing_slots
    assert "dominio_publicado" not in missing_slots
    assert "plano_hospedagem" in missing_slots
    assert "login" in missing_slots


def test_wrong_engagement_gated_folder_fails_without_output(
    tmp_path: Path,
) -> None:
    master = gated_master(tmp_path / "MASTER.docx")
    output_root = tmp_path / "reports"

    completed = run_generator(
        master,
        output_root,
        "50-2026",
        control_sheet=CONTROL_SHEET,
        gated_drop_root=GATED_FIXTURES / "wrong",
    )

    assert completed.returncode != 0
    assert "belongs to Pasta '63-2026'" in completed.stderr
    assert not list(output_root.rglob("*.docx"))


def test_real_current_master_passes_media_and_link_provenance_gates(
    tmp_path: Path,
) -> None:
    sources = list(Path(__file__).resolve().parent.parent.glob("*ARGEL*.docx"))
    if not sources:
        pytest.skip("approved source binary is intentionally not tracked")
    master = build_master(sources[0], tmp_path / "master").master
    generated = run_generator(
        master,
        tmp_path / "reports",
        "50-2026",
        control_sheet=CONTROL_SHEET,
        gated_drop_root=GATED_FIXTURES / "complete",
    )
    assert generated.returncode == 0, generated.stderr
    output = generated_document(generated.stdout)

    checked = run_check(output, output.with_name("run.json"))

    assert checked.returncode == 1
    assert "GATE media-provenance: PASS" in checked.stdout
    assert "GATE link-provenance: PASS" in checked.stdout
    assert "GATE pendencias-agreement: PASS" in checked.stdout
    assert "GATE token-residue: FAIL" in checked.stdout
    assert "{{SOBRE_A_EMPRESA}}" in checked.stdout
