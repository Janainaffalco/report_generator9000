from __future__ import annotations

from datetime import datetime
from pathlib import Path

from report_generator9000.control_sheet import (
    Engagement,
    SkippedRow,
    StopCondition,
    read_control_sheet,
)


FIXTURE = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"


def test_committed_workbook_exercises_every_control_sheet_outcome() -> None:
    outcomes = read_control_sheet(FIXTURE)

    assert outcomes == (
        Engagement(
            row_number=2,
            demanda="011616/2026",
            pasta="40-2026",
            razao_social="DENISE BARROS DE ALMEIDA",
            cnpj="52.052.612/0001-21",
            kick_off=datetime(2026, 4, 15),
            especialista="Bruno Henrique Santana Leal",
            capture_origin="https://denise.example/",
            published_domain=None,
        ),
        StopCondition(3, "Link contains a delivery date"),
        StopCondition(4, "Link is absent"),
        Engagement(
            row_number=5,
            demanda="011739/2026",
            pasta="63-2026",
            razao_social="SAN FRIO REFRIGERACAO",
            cnpj="67.671.933/0001-81",
            kick_off=datetime(2026, 5, 4),
            especialista="Bruno Henrique Santana Leal",
            capture_origin="https://midnightblue-jellyfish-121804.hostingersite.com/",
            published_domain="sanfrio.com.br",
        ),
        Engagement(
            row_number=6,
            demanda="011749/2026",
            pasta="50-2026",
            razao_social="LARI TORELLO CONSULTORIA LTDA",
            cnpj="58.548.043/0001-96",
            kick_off=datetime(2026, 5, 5),
            especialista="Bruno Henrique Santana Leal",
            capture_origin="https://lari.example/",
            published_domain=None,
        ),
        SkippedRow(7, "already complete"),
        StopCondition(8, "Pasta is absent"),
        SkippedRow(10, "Tema is out of scope"),
        StopCondition(11, "CNPJ must contain 13 or 14 digits"),
        StopCondition(13, "Kick off is not a date"),
    )

    first = outcomes[0]
    assert isinstance(first, Engagement)
    assert first.kick_off_br == "15/04/2026"
    assert first.output_key == "40-2026_DENISE BARROS DE ALMEIDA"
