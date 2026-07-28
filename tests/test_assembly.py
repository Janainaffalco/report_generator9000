from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

import pytest
from PIL import Image

from report_generator9000.assembly import assemble_output_package
from report_generator9000.control_sheet import Engagement
from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates import GATES
from report_generator9000.gates.blocks import check_block_integrity
from report_generator9000.generate import StopCondition
from report_generator9000.master import build_master
from report_generator9000.prose import (
    GroundedField,
    ProseConfig,
    ProseRequest,
    ProseResponse,
)
from tests.fixtures.docx_builder import png_bytes
from tests.test_lista_paginas import serve_fixture_site
from tests.test_master_build import approved_source


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class _Provider:
    def __init__(self, response: ProseResponse) -> None:
        self.response = response

    def generate(
        self,
        request: ProseRequest,
        config: ProseConfig,
    ) -> ProseResponse:
        return self.response


def _engagement(origin: str) -> Engagement:
    return Engagement(
        row_number=2,
        demanda="011616/2026",
        pasta="40-2026",
        razao_social="CLIENTE",
        cnpj="52.052.612/0001-21",
        kick_off=datetime(2026, 4, 15),
        especialista="Especialista",
        capture_origin=origin,
        published_domain=None,
    )


def test_one_engagement_directory_contains_the_complete_handoff_package(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    gated_root = tmp_path / "gated"
    gated_folder = gated_root / "40-2026_CLIENTE"
    gated_folder.mkdir(parents=True)
    (gated_folder / "valores.json").write_text(
        json.dumps(
            {
                "pasta": "40-2026",
                "razao_social": "CLIENTE",
                "lista_paginas": [
                    {
                        "tipo": "pagina_principal",
                        "rotulo": "Home",
                        "url": "/",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stale_directory = tmp_path / "outputs" / "40-2026_CLIENTE"
    stale_preview = stale_directory / "previews" / "preview-999.png"
    stale_raw = stale_directory / "capturas" / "99-stale.png"
    stale_embedding = (
        stale_directory / "capturas" / "embutir" / "99-stale.png"
    )
    stale_preview.parent.mkdir(parents=True)
    stale_embedding.parent.mkdir(parents=True)
    stale_preview.write_bytes(b"stale preview")
    stale_raw.write_bytes(b"stale raw capture")
    stale_embedding.write_bytes(b"stale embedding")

    with serve_fixture_site() as origin:
        package = assemble_output_package(
            master,
            tmp_path / "outputs",
            _engagement(origin),
            gated_root,
            no_llm=True,
        )

    assert [item for item in (tmp_path / "outputs").iterdir()] == [
        package.directory
    ]
    assert package.report.document.parent == package.directory
    assert package.report.context_document.parent == package.directory
    assert package.report.pendencias_document.parent == package.directory
    assert package.report.pendencias_json.parent == package.directory
    assert package.previews
    assert all(path.parent.name == "previews" for path in package.previews)
    assert package.raw_captures
    assert all(path.parent.name == "capturas" for path in package.raw_captures)
    assert all(path.exists() for path in package.previews + package.raw_captures)
    assert not stale_preview.exists()
    assert not stale_raw.exists()
    assert not stale_embedding.exists()

    preview_has_site_color = False
    for preview in package.previews:
        with Image.open(preview) as image:
            assert image.size == (1240, 1754)
            colors = image.convert("RGB").resize((200, 200)).getcolors(
                maxcolors=1_000_000
            )
            assert colors is not None
            preview_has_site_color = preview_has_site_color or any(
                green > 110 and red < 170
                for _count, (red, green, _blue) in colors
            )
    assert preview_has_site_color
    assert any(
        capture.raw_width > capture.embedding_width
        for capture in package.capture_run.captures
    )

    document_package = open_docx_package(package.report.document)
    assert package.report.context.blocks == tuple(
        page.titulo_bloco for page in package.pages
    )
    assert check_block_integrity(
        document_package,
        package.report.context,
    ).passed
    assert package.report.gate_report.passed
    assert len(package.report.gate_report.results) == len(GATES)
    assert [
        page.rotulo
        for page in package.pages
        if page.tipo == "pagina_principal"
    ] == ["Home"]
    document_text = "\n".join(
        part.text or "" for part in document_package.parts
    )
    domain_pendencia = next(
        item
        for item in package.report.context.pendencias
        if item.slot == "dominio_publicado"
    )
    assert domain_pendencia.evidence in document_text
    assert origin not in document_text

    with ZipFile(package.report.document) as archive:
        settings = ElementTree.fromstring(
            archive.read("word/settings.xml")
        )
        document = ElementTree.fromstring(
            archive.read("word/document.xml")
        )
    update_fields = settings.find(f"{W}updateFields")
    assert update_fields is not None
    assert update_fields.get(f"{W}val") == "true"
    assert any(
        'TOC \\o "1-2"' in (item.text or "")
        for item in document.iter(f"{W}instrText")
    )

    pendencias = json.loads(
        package.report.pendencias_json.read_text(encoding="utf-8")
    )
    assert pendencias["status"] == "draft"
    assert pendencias["ready_to_send"] is False
    assert "Estado: **RASCUNHO**" in (
        package.report.pendencias_document.read_text(encoding="utf-8")
    )
    assert set(package.report.context.output_paths) == {
        str(package.report.document.resolve()),
        str(package.report.context_document.resolve()),
        str(package.report.pendencias_document.resolve()),
        str(package.report.pendencias_json.resolve()),
        *(str(path.resolve()) for path in package.previews),
        *(str(path.resolve()) for path in package.raw_captures),
    }


def test_a_gate_failure_never_promotes_the_staged_report(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    with ZipFile(master, "a") as archive:
        archive.writestr(
            "word/media/orphan.png",
            png_bytes(20, 10),
        )
    gated_root = tmp_path / "gated"
    gated_folder = gated_root / "40-2026_CLIENTE"
    gated_folder.mkdir(parents=True)
    (gated_folder / "valores.json").write_text(
        json.dumps(
            {
                "pasta": "40-2026",
                "razao_social": "CLIENTE",
                "lista_paginas": [
                    {
                        "tipo": "pagina_principal",
                        "rotulo": "Home",
                        "url": "/",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with serve_fixture_site() as origin, pytest.raises(
        StopCondition,
        match=(
            r"STOP CONDITION[\s\S]*block-integrity"
            r"[\s\S]*unreferenced-media"
            r"\s+word/media/orphan\.png"
        ),
    ):
        assemble_output_package(
            master,
            tmp_path / "outputs",
            _engagement(origin),
            gated_root,
            no_llm=True,
        )

    output_directory = tmp_path / "outputs" / "40-2026_CLIENTE"
    assert not output_directory.exists()
    assert not list(output_directory.glob("*.docx"))
    assert not (output_directory / "run.json").exists()
    assert not (output_directory / "pendencias.json").exists()
    assert not (output_directory / "PENDENCIAS.md").exists()


def test_budget_stop_condition_discards_the_whole_staged_package(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    provider = _Provider(
        ProseResponse(
            company_description=GroundedField("Parcial", True),
            briefing_objective=GroundedField("Parcial", True),
            output_budget_exhausted=True,
        )
    )

    with serve_fixture_site() as origin, pytest.raises(StopCondition):
        assemble_output_package(
            master,
            tmp_path / "outputs",
            _engagement(origin),
            tmp_path / "absent-gated",
            prose_provider=provider,
            prose_config=ProseConfig("configured", 20),
        )

    assert not (tmp_path / "outputs" / "40-2026_CLIENTE").exists()


def test_ungrounded_prose_is_a_marked_pendencia_in_a_certified_package(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    provider = _Provider(
        ProseResponse(
            company_description=GroundedField("Inventado", False),
            briefing_objective=GroundedField(None, False),
        )
    )

    with serve_fixture_site() as origin:
        package = assemble_output_package(
            master,
            tmp_path / "outputs",
            _engagement(origin),
            tmp_path / "absent-gated",
            prose_provider=provider,
            prose_config=ProseConfig("configured", 100),
        )

    assert package.report.gate_report.passed
    pendencia_items = [
        item
        for item in package.report.context.pendencias
        if item.classification == "TOOL_BLOCKED"
        and item.slot in {"descricao_empresa", "objetivo_briefing"}
    ]
    assert {item.slot for item in pendencia_items} == {
        "descricao_empresa",
        "objetivo_briefing",
    }
    document = open_docx_package(package.report.document)
    text = "\n".join(part.text or "" for part in document.parts)
    assert all(item.evidence in text for item in pendencia_items)


def test_mis_keyed_gated_folder_produces_no_package(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    gated_folder = tmp_path / "gated" / "40-2026_CLIENTE"
    gated_folder.mkdir(parents=True)
    (gated_folder / "valores.json").write_text(
        json.dumps(
            {
                "pasta": "63-2026",
                "razao_social": "OUTRO CLIENTE",
            }
        ),
        encoding="utf-8",
    )

    with serve_fixture_site() as origin, pytest.raises(StopCondition):
        assemble_output_package(
            master,
            tmp_path / "outputs",
            _engagement(origin),
            tmp_path / "gated",
            no_llm=True,
        )

    assert not (tmp_path / "outputs" / "40-2026_CLIENTE").exists()
