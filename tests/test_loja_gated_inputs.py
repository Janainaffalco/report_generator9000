"""Loja Virtual accepts consultant-supplied Gated Inputs, never credentials."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from fixtures.docx_builder import build_docx, paragraph
from report_generator9000.control_sheet import Engagement, read_control_sheet
from report_generator9000.docx_package import media_location, open_docx_package
from report_generator9000.gated_inputs import (
    GatedInputError,
    gated_drop_folder,
    load_gated_inputs,
)
from report_generator9000.gates import run_gates
from report_generator9000.gates.loja_handover import check_loja_handover_claims
from report_generator9000.generate import GeneratedReport, generate_report
from report_generator9000.run_context import Pendencia, RunContext
from report_generator9000.tema import (
    LOJA_VIRTUAL_TEMA,
    WEBSITE_TEMA,
    contract_for,
    supported_contract,
)


SHEET = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"

# Every administrative Slot a consultant may attach, and the label the Master
# binds it to. The label is what a Pendência names, so a consultant reading
# PENDENCIAS.md knows which screenshot is missing without opening the Word file.
ADMIN_SLOT_LABELS = {
    "login": "PÁGINA DE LOGIN",
    "painel": "PAINEL DE CONFIGURAÇÃO WORDPRESS",
    "produtos-admin": "LISTA DE PRODUTOS",
    "pagamentos-admin": "CONFIGURAÇÃO DE PAGAMENTOS",
    "entregas-admin": "CONFIGURAÇÃO DE ENTREGAS",
    "drive": "COMPARTILHAMENTO DECLARADO PELO CONSULTOR",
    "kickoff": "PRINT DO KICKOFF",
    "entrega": "PRINT DA ENTREGA",
}


def _loja_engagement() -> Engagement:
    return next(
        row
        for row in read_control_sheet(SHEET)
        if isinstance(row, Engagement)
        and (contract := contract_for(row.tema)) is not None
        and contract.name == LOJA_VIRTUAL_TEMA
    )


def _identity(engagement: Engagement) -> dict[str, str]:
    return {"pasta": engagement.pasta, "razao_social": engagement.razao_social}


def _write_values(folder: Path, document: dict[str, object]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "valores.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )


def _write_image(folder: Path, filename: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 360), "white").save(folder / filename)


def _run(engagement: Engagement, root: Path, gated: Path) -> GeneratedReport:
    contract = supported_contract(engagement.tema)
    assert contract.master is not None
    return generate_report(
        contract.master,
        root / "outputs",
        engagement,
        gated,
        pages=(),
        no_llm=True,
    )


def _pendencias_by_slot(report: GeneratedReport) -> dict[str, Pendencia]:
    return {item.slot: item for item in report.context.pendencias}


def test_every_loja_gated_slot_is_bound_to_its_own_labelled_position() -> None:
    contract = supported_contract(LOJA_VIRTUAL_TEMA)
    assert contract.master is not None
    package = open_docx_package(contract.master)
    labels = dict(contract.gated_slot_labels)
    assert ADMIN_SLOT_LABELS.items() <= labels.items()
    pages: list[str] = []
    for slot, _filename, part_name in contract.gated_image_slots:
        if slot not in ADMIN_SLOT_LABELS:
            continue
        _position, page = media_location(package, part_name)
        assert page == labels[slot], slot
        pages.append(page)
    assert len(set(pages)) == len(pages)


@pytest.mark.parametrize("tema", [LOJA_VIRTUAL_TEMA, WEBSITE_TEMA])
def test_no_block_heading_is_bound_to_a_gated_image_slot(tema: str) -> None:
    """A Gated Slot's label may never shadow a Block from the block-integrity gate.

    `check_block_integrity` exempts a `keepNext` label sitting immediately above
    a Gated image Slot from its declared-Block bookkeeping. That exemption is
    only safe while the two sets stay disjoint in every approved Master, which
    is what this pins -- a Block's Capture is stamped into its own media part
    and must never land on one a Gated Input can claim.
    """
    contract = supported_contract(tema)
    assert contract.master is not None
    package = open_docx_package(contract.master)
    gated_parts = {part for _slot, _filename, part in contract.gated_image_slots}
    by_position = {
        (item.source_part, item.index): item for item in package.paragraphs
    }
    for heading in package.paragraphs:
        if not heading.keep_next or heading.text.strip() not in contract.required_blocks:
            continue
        following = by_position.get((heading.source_part, heading.index + 1))
        assert following is not None
        bound = {
            slot.media_part
            for slot in package.slots
            if slot.source_part == following.source_part
            and slot.paragraph_index == following.index
        }
        assert not bound & gated_parts, heading.text


def test_absent_gated_inputs_classify_every_admin_slot_and_keep_a_draft(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    report = _run(engagement, tmp_path, tmp_path / "gated")
    assert report.status == "draft"
    assert not report.ready_to_send
    assert report.context.drop_folder is None
    pendencias = _pendencias_by_slot(report)
    for slot, label in ADMIN_SLOT_LABELS.items():
        item = pendencias[slot]
        assert item.classification == "GATED"
        assert item.page == label
        assert label.casefold() in item.name.casefold()
    for slot in (
        "data_entrega",
        "data_backup",
        "link_codigo_fonte",
        "link_guia_rapido",
        "link_identidade_visual",
    ):
        assert pendencias[slot].classification == "GATED"


def test_supplied_gated_inputs_embed_with_provenance_inside_the_pasta(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    gated = tmp_path / "gated"
    folder = gated_drop_folder(gated, engagement)
    _write_values(
        folder,
        {
            **_identity(engagement),
            "data_entrega": "30/06/2026",
            "data_backup": "29/06/2026",
            "link_codigo_fonte": "https://drive.google.com/drive/folders/codigo",
        },
    )
    filenames = supported_contract(engagement.tema).image_filenames
    for slot in ADMIN_SLOT_LABELS:
        _write_image(folder, filenames[slot])

    report = _run(engagement, tmp_path, gated)
    assert report.context.drop_folder == str(folder.resolve())
    gated_artifacts = report.context.artifacts_of("gated")
    assert {item.label for item in gated_artifacts} == set(ADMIN_SLOT_LABELS)
    for artifact in gated_artifacts:
        assert artifact.source is not None
        assert Path(artifact.source).parent == folder.resolve()
    pendencias = _pendencias_by_slot(report)
    assert not set(ADMIN_SLOT_LABELS) & set(pendencias)
    assert "data_entrega" not in pendencias
    assert run_gates(
        open_docx_package(report.document),
        report.context,
        tema=engagement.tema,
    ).passed


def test_a_later_attachment_reruns_unattended_and_clears_only_that_slot(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    gated = tmp_path / "gated"
    first = _run(engagement, tmp_path, gated)
    assert "produtos-admin" in _pendencias_by_slot(first)
    first_bytes = first.document.read_bytes()

    folder = gated_drop_folder(gated, engagement)
    _write_values(folder, _identity(engagement))
    _write_image(folder, "produtos-admin.png")

    second = _run(engagement, tmp_path, gated)
    assert second.document == first.document
    assert second.document.read_bytes() != first_bytes
    pendencias = _pendencias_by_slot(second)
    assert "produtos-admin" not in pendencias
    assert "pagamentos-admin" in pendencias
    assert second.status == "draft"
    assert [item.label for item in second.context.artifacts_of("gated")] == [
        "produtos-admin"
    ]


def test_a_drop_folder_for_another_pasta_is_rejected(tmp_path: Path) -> None:
    engagement = _loja_engagement()
    folder = gated_drop_folder(tmp_path, engagement)
    _write_values(folder, {"pasta": "99-2026", "razao_social": "OUTRA LOJA"})
    with pytest.raises(GatedInputError, match="not this Engagement"):
        load_gated_inputs(tmp_path, engagement)


@pytest.mark.parametrize(
    "document",
    [
        {"link_usuarios_senhas": "https://drive.google.com/drive/folders/x"},
        {"configuracao_woocommerce": "usuario admin / senha 1234"},
    ],
)
def test_credential_bearing_values_are_rejected_by_name(
    tmp_path: Path, document: dict[str, str]
) -> None:
    engagement = _loja_engagement()
    folder = gated_drop_folder(tmp_path, engagement)
    _write_values(folder, {**_identity(engagement), **document})
    with pytest.raises(GatedInputError, match="credential"):
        load_gated_inputs(tmp_path, engagement)


def test_credential_uploads_are_rejected_by_name(tmp_path: Path) -> None:
    engagement = _loja_engagement()
    folder = gated_drop_folder(tmp_path, engagement)
    _write_values(folder, _identity(engagement))
    _write_image(folder, "usuarios-senhas.png")
    with pytest.raises(GatedInputError, match="credential"):
        load_gated_inputs(tmp_path, engagement)


@pytest.mark.parametrize(
    "link",
    [
        "http://drive.google.com/drive/folders/codigo",
        "https://example.com/drive/folders/codigo",
        "https://drive.google.com/",
        "nao-informado",
    ],
)
def test_declared_drive_links_must_keep_their_url_shape(
    tmp_path: Path, link: str
) -> None:
    engagement = _loja_engagement()
    folder = gated_drop_folder(tmp_path, engagement)
    _write_values(folder, {**_identity(engagement), "link_codigo_fonte": link})
    with pytest.raises(GatedInputError, match="drive.google.com"):
        load_gated_inputs(tmp_path, engagement)


def test_a_declared_drive_link_is_embedded_without_claiming_inspection(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    gated = tmp_path / "gated"
    folder = gated_drop_folder(gated, engagement)
    _write_values(
        folder,
        {
            **_identity(engagement),
            "link_codigo_fonte": "https://drive.google.com/drive/folders/codigo",
        },
    )
    report = _run(engagement, tmp_path, gated)
    text = "\n".join(
        item.text for item in open_docx_package(report.document).paragraphs
    ).casefold()
    assert "https://drive.google.com/drive/folders/codigo" in text
    assert "declarado pelo consultor" in text
    for claim in ("verificamos", "conferimos o conteúdo", "acessamos"):
        assert claim not in text


@pytest.mark.parametrize(
    "claim",
    [
        "O link permanecerá disponível por 30 dias.",
        "O representante declara ter recebido o projeto.",
        "Todas as orientações foram realizadas junto do responsável.",
        "O código fonte foi cedido por meio do link acima.",
        "Recomendamos alterar as senhas de acesso após a entrega.",
    ],
)
def test_unevidenced_handover_language_is_rejected(
    tmp_path: Path, claim: str
) -> None:
    path = tmp_path / "claim.docx"
    build_docx(path, paragraphs=(paragraph(claim),))
    package = open_docx_package(path)
    assert not check_loja_handover_claims(package, RunContext()).passed


def test_the_generated_loja_report_carries_no_handover_claims(
    tmp_path: Path,
) -> None:
    engagement = _loja_engagement()
    report = _run(engagement, tmp_path, tmp_path / "gated")
    package = open_docx_package(report.document)
    assert check_loja_handover_claims(package, report.context).passed
    assert check_loja_handover_claims in supported_contract(engagement.tema).gates
