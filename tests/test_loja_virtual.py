"""Public Tema seams exercised with the committed control-sheet fixture."""

from __future__ import annotations

from pathlib import Path
import json
import hashlib

import pytest
from PIL import Image

from report_generator9000.block_stamping import BlockImage, stamp_blocks
from report_generator9000.control_sheet import Engagement, StopCondition, read_control_sheet
from report_generator9000.docx_package import open_docx_package
from report_generator9000.generate import generate_report
from report_generator9000.gated_inputs import GatedInputError, gated_drop_folder, load_gated_inputs
from report_generator9000.gates import run_gates
from report_generator9000.gates.loja_blocks import check_loja_block_grammar
from report_generator9000.lista_paginas import ELEMENTO_TRANSVERSAL, PAGINA_PRINCIPAL, Pagina
from report_generator9000.loja_block_draft import loja_draft_blocks
from report_generator9000.tema import (
    LOJA_VIRTUAL_TEMA,
    WEBSITE_TEMA,
    contract_for,
    supported_contract,
)


SHEET = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"


def _is_loja(row: object) -> bool:
    """A Loja row whether it was selectable or stopped before its Tema was kept.

    A row keeps the sheet's own spelling, so the Tema is matched through the
    routing contract rather than by comparing strings.
    """
    if isinstance(row, Engagement):
        contract = contract_for(row.tema)
        return contract is not None and contract.name == LOJA_VIRTUAL_TEMA
    return isinstance(row, StopCondition) and row.razao_social.startswith("LOJA CNPJ")


def _loja_engagement() -> Engagement:
    return next(
        row for row in read_control_sheet(SHEET)
        if isinstance(row, Engagement) and _is_loja(row)
    )


def test_sheet_selects_valid_loja_rows_and_stops_on_malformed_rows() -> None:
    rows = read_control_sheet(SHEET)
    loja = [row for row in rows if _is_loja(row)]
    assert [type(row).__name__ for row in loja] == ["Engagement", "StopCondition"]
    assert loja[1].cause == "CNPJ must contain 13 or 14 digits"
    website = [
        row for row in rows
        if isinstance(row, Engagement)
        and (contract := contract_for(row.tema)) is not None
        and contract.name == WEBSITE_TEMA
    ]
    assert website


def test_loja_master_is_client_neutral_and_passes_its_signoff_gate() -> None:
    contract = supported_contract(LOJA_VIRTUAL_TEMA)
    website = supported_contract(WEBSITE_TEMA)
    assert contract.master != website.master
    assert contract.master is not None and contract.master_gate is not None
    package = open_docx_package(contract.master)
    assert contract.master_gate(package).passed
    assert not any(
        word in "\n".join(paragraph.text for paragraph in package.paragraphs).casefold()
        for word in ("cronograma", "senha", "plugins adicionados")
    )


def test_loja_engagement_yields_gated_draft_without_credentials(tmp_path: Path) -> None:
    engagement = _loja_engagement()
    contract = supported_contract(engagement.tema)
    assert contract.master is not None
    report = generate_report(
        contract.master, tmp_path / "outputs", engagement,
        tmp_path / "gated", pages=(), no_llm=True,
    )
    assert report.status == "draft"
    assert report.document.is_file()
    assert {"configuracao_woocommerce", "evidencia_checkout"} <= {
        item.slot for item in report.context.pendencias
    }
    assert run_gates(open_docx_package(report.document), report.context, tema=engagement.tema).passed
    text = "\n".join(paragraph.text for paragraph in open_docx_package(report.document).paragraphs)
    assert "{{" not in text
    assert "senha" not in text.casefold()


def test_loja_rejects_credential_bearing_gated_text_before_generation(tmp_path: Path) -> None:
    engagement = _loja_engagement()
    folder = gated_drop_folder(tmp_path, engagement)
    folder.mkdir(parents=True)
    (folder / "valores.json").write_text(
        json.dumps({
            "pasta": engagement.pasta,
            "razao_social": engagement.razao_social,
            "configuracao_woocommerce": "senha: [omitida]",
        }, ensure_ascii=False), encoding="utf-8",
    )

    with pytest.raises(GatedInputError, match="cannot be inserted automatically"):
        load_gated_inputs(tmp_path, engagement)


def test_loja_stamping_keeps_storefront_blocks_and_classifies_missing_public_evidence(tmp_path: Path) -> None:
    engagement = _loja_engagement()
    contract = supported_contract(engagement.tema)
    assert contract.master is not None
    capture_folder = tmp_path / "capturas"
    capture_folder.mkdir()
    image_path = capture_folder / "home.png"
    Image.new("RGB", (1200, 675), "white").save(image_path)
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    pages = (
        Pagina(PAGINA_PRINCIPAL, "Home", engagement.capture_origin, "PÁGINA HOME"),
        Pagina(ELEMENTO_TRANSVERSAL, "Cabeçalho", engagement.capture_origin, "CABEÇALHO"),
        Pagina(ELEMENTO_TRANSVERSAL, "Rodapé", engagement.capture_origin, "RODAPÉ"),
    )
    images = tuple(BlockImage(page, image_path, digest) for page in pages)
    block_pages, block_images, pendencias = loja_draft_blocks(
        contract.required_blocks, pages, images, capture_folder,
        engagement.capture_origin,
    )
    stamped = stamp_blocks(
        contract.master, tmp_path / "stamped.docx", block_pages, block_images,
        capture_folder=capture_folder,
    )
    report = generate_report(
        stamped.document, tmp_path / "outputs", engagement,
        tmp_path / "gated", pages=pages, no_llm=True,
        run_artifacts=stamped.artifacts, blocks=stamped.headings,
        run_pendencias=pendencias,
    )
    package = open_docx_package(report.document)
    assert check_loja_block_grammar(package, report.context).passed
    assert run_gates(package, report.context, tema=engagement.tema).passed
    assert {"SEÇÃO PRODUTOS", "SEÇÃO CARRINHO", "SEÇÃO CHECKOUT"} <= {
        item.name for item in report.context.pendencias
        if item.slot.startswith("loja_block_") and item.classification == "TOOL_BLOCKED"
    }
