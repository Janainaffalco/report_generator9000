from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

from PIL import Image

from report_generator9000.assembly import assemble_output_package
from report_generator9000.control_sheet import Engagement
from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates.blocks import check_block_integrity
from report_generator9000.master import build_master
from tests.test_lista_paginas import serve_fixture_site
from tests.test_master_build import approved_source


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


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

    for preview in package.previews:
        with Image.open(preview) as image:
            assert image.size == (1240, 1754)
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
