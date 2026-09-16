from __future__ import annotations

from datetime import datetime
from pathlib import Path

from report_generator9000.control_sheet import (
    Engagement,
    StopCondition,
    UnsupportedRow,
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
            tema="Insercao digital - Desenvolvimento de WebSite",
        ),
        StopCondition(
            3,
            "Link contains a delivery date",
            demanda="011642/2026",
            razao_social="CARLA MONIZE LOPES",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="20/04/2026",
            link_text="20/07/2026",
        ),
        StopCondition(
            4,
            "Link is absent",
            demanda="011675/2026",
            razao_social="MAGICO TECH",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="14/04/2026",
        ),
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
            tema="Insercao digital - Desenvolvimento de WebSite",
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
            tema="Insercao digital - Desenvolvimento de WebSite",
        ),
        Engagement(
            row_number=7,
            demanda="011289/2026",
            pasta="26-2026",
            razao_social="SANTANA BELLINI",
            cnpj="18.034.491/0001-57",
            kick_off=datetime(2026, 3, 24),
            especialista="Christian Albuquerque Alonso",
            capture_origin="https://complete.example/",
            published_domain=None,
            report_ready_text="ok",
            tema="Insercao digital - Desenvolvimento de WebSite",
        ),
        StopCondition(
            8,
            "Pasta is absent",
            demanda="011910/2026",
            razao_social="CLINICA SILVIA",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="13/05/2026",
            link_text="https://missing-pasta.example/",
        ),
        Engagement(
            row_number=10,
            demanda="011547/2026",
            pasta="72-2026",
            razao_social="CASA NOSSA",
            cnpj="18.573.230/0001-05",
            kick_off=datetime(2026, 4, 21),
            especialista="Christian Albuquerque Alonso",
            capture_origin="https://casanossa.example/",
            published_domain=None,
            tema="Implantacao de Loja Virtual",
        ),
        StopCondition(
            11,
            "CNPJ must contain 13 or 14 digits",
            demanda="012000/2026",
            razao_social="CNPJ INVALIDO",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="08/05/2026",
            link_text="https://invalid-cnpj.example/",
        ),
        StopCondition(
            13,
            "Kick off is not a date",
            demanda="012001/2026",
            razao_social="KICK OFF INVALIDO",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="amanha",
            link_text="https://invalid-kickoff.example/",
        ),
        Engagement(
            row_number=14,
            demanda="012099/2026",
            pasta="40-2026",
            razao_social="EMPRESA GEMEA LTDA",
            cnpj="11.222.333/0001-81",
            kick_off=datetime(2026, 6, 12),
            especialista="Christian Albuquerque Alonso",
            capture_origin="https://gemea.example/",
            published_domain=None,
            tema="Insercao digital - Desenvolvimento de WebSite",
        ),
        StopCondition(
            16,
            "Link is not a URL",
            demanda="012120/2026",
            razao_social="LOJA SEM PROTOCOLO",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="20/05/2026",
            link_text="www.exemplo.com.br",
        ),
        StopCondition(
            17,
            "CNPJ must contain 13 or 14 digits",
            demanda="012140/2026",
            razao_social="LOJA CNPJ INVALIDO",
            especialista="Christian Albuquerque Alonso",
            kick_off_text="22/05/2026",
            link_text="https://loja-invalida.example/",
        ),
        UnsupportedRow(
            row_number=19,
            reason="Tema is unsupported",
            tema="Servico sem Master aprovado",
            demanda="012160/2026",
            razao_social="SERVICO NAO CONTRATADO",
            especialista="Bruno Henrique Santana Leal",
            kick_off_text="26/05/2026",
            link_text="https://out-of-scope.example/",
        ),
    )

    first = outcomes[0]
    assert isinstance(first, Engagement)
    assert first.kick_off_br == "15/04/2026"
    assert first.output_key == "40-2026_DENISE BARROS DE ALMEIDA"
