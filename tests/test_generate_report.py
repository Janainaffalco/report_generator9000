from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates.master import BOILERPLATE_MEDIA
from report_generator9000.gates.tokens import check_token_residue
from report_generator9000.gated_inputs import GATED_VALUE_SLOTS
from report_generator9000.master import build_master
from report_generator9000.run_context import RunContext
from test_master_build import approved_source


ROOT = Path(__file__).resolve().parent.parent
CONTROL_SHEET = Path(__file__).parent / "fixtures" / "control-sheet-cases.xlsx"
SPREADSHEET_TOKENS = {
    "{{DEMANDA}}",
    "{{RAZAO_SOCIAL}}",
    "{{CNPJ}}",
    "{{ESPECIALISTA}}",
    "{{DATA_KICKOFF}}",
}
PROSE_VALUES = {
    "{{SOBRE_A_EMPRESA}}": (
        "[PENDÊNCIA GATED: descrição da empresa não gerada (--no-llm)]"
    ),
    "{{BRIEFING_INICIAL}}": (
        "[PENDÊNCIA GATED: objetivo do briefing não gerado (--no-llm)]"
    ),
    "{{LISTA_DE_PAGINAS}}": (
        "A estrutura do site contempla as páginas Home."
    ),
}


def run_generator(
    master: Path,
    output: Path,
    pasta: str,
    *,
    control_sheet: Path = CONTROL_SHEET,
    gated_drop_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    stdout_path = output.parent / f"{pasta}-stdout.txt"
    stderr_path = output.parent / f"{pasta}-stderr.txt"
    selected_gated_root = output.parent / f"declared-gated-{pasta}"
    if gated_drop_root is not None and gated_drop_root.exists():
        shutil.copytree(
            gated_drop_root,
            selected_gated_root,
            dirs_exist_ok=True,
        )
    companies = {
        "40-2026": (
            "DENISE BARROS DE ALMEIDA",
            "EMPRESA GEMEA LTDA",
        ),
        "50-2026": ("LARI TORELLO CONSULTORIA LTDA",),
    }.get(pasta, ())
    for company in companies:
        folder = selected_gated_root / f"{pasta}_{company}"
        folder.mkdir(parents=True, exist_ok=True)
        values_path = folder / "valores.json"
        values = (
            json.loads(values_path.read_text(encoding="utf-8"))
            if values_path.exists()
            else {"pasta": pasta, "razao_social": company}
        )
        values["lista_paginas"] = [
            {
                "tipo": "pagina_principal",
                "rotulo": "Home",
                "url": "/",
            }
        ]
        values_path.write_text(
            json.dumps(values, ensure_ascii=False),
            encoding="utf-8",
        )
    command = [
        sys.executable,
        str(ROOT / "gerar_relatorio.py"),
        "--linha",
        pasta,
        "--planilha",
        str(control_sheet),
        "--master",
        str(master),
        "--saida",
        str(output),
        "--no-llm",
        "--skip-assembly",
    ]
    command.extend(
        (
            "--gated-drop-root",
            str(
                selected_gated_root
            ),
        )
    )
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        completed = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    return subprocess.CompletedProcess(
        command,
        completed.returncode,
        stdout_path.read_text(encoding="utf-8"),
        stderr_path.read_text(encoding="utf-8"),
    )


def test_cli_clones_master_and_fills_each_shared_pasta_engagement(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "master"
    ).master

    completed = run_generator(master, tmp_path / "reports", "40-2026")

    assert completed.returncode == 0, completed.stderr
    outputs = [
        Path(line.split("\t", 1)[1])
        for line in completed.stdout.splitlines()
        if line.startswith("DOCX\t")
    ]
    assert len(outputs) == 2
    assert len({path.name.casefold() for path in outputs}) == 2
    assert all("40-2026" in str(path) for path in outputs)
    assert any("DENISE BARROS DE ALMEIDA" in str(path) for path in outputs)
    assert any("EMPRESA GEMEA LTDA" in str(path) for path in outputs)

    with ZipFile(master) as source:
        source_parts = {
            item.filename: (item, source.read(item.filename))
            for item in source.infolist()
        }
    expected_values = (
        {
            "{{DEMANDA}}": "011616/2026",
            "{{RAZAO_SOCIAL}}": "DENISE BARROS DE ALMEIDA",
            "{{CNPJ}}": "52.052.612/0001-21",
            "{{ESPECIALISTA}}": "Bruno Henrique Santana Leal",
            "{{DATA_KICKOFF}}": "15/04/2026",
        },
        {
            "{{DEMANDA}}": "012099/2026",
            "{{RAZAO_SOCIAL}}": "EMPRESA GEMEA LTDA",
            "{{CNPJ}}": "11.222.333/0001-81",
            "{{ESPECIALISTA}}": "Christian Albuquerque Alonso",
            "{{DATA_KICKOFF}}": "12/06/2026",
        },
    )
    for output, values in zip(
        sorted(outputs, key=lambda item: item.name), expected_values
    ):
        package = open_docx_package(output)
        text = "\n".join(part.text or "" for part in package.parts)
        assert not any(token in text for token in SPREADSHEET_TOKENS)
        assert all(value in text for value in values.values())
        assert not any(token in text for token in PROSE_VALUES)
        assert all(value in text for value in PROSE_VALUES.values())
        token_gate = check_token_residue(package, RunContext())
        assert token_gate.passed
        with ZipFile(output) as generated:
            assert generated.namelist() == list(source_parts)
            assert {
                (
                    item.source_part,
                    item.paragraph_index,
                    item.width_emu,
                    item.height_emu,
                )
                for item in package.slots
            } == {
                (
                    item.source_part,
                    item.paragraph_index,
                    item.width_emu,
                    item.height_emu,
                )
                for item in open_docx_package(master).slots
            }
            for item in generated.infolist():
                source_info, source_content = source_parts[item.filename]
                assert (
                    item.date_time,
                    item.compress_type,
                    item.external_attr,
                    item.create_system,
                ) == (
                    source_info.date_time,
                    source_info.compress_type,
                    source_info.external_attr,
                    source_info.create_system,
                )
                expected_content = source_content
                for token, value in values.items():
                    expected_content = expected_content.replace(
                        token.encode(), value.encode()
                    )
                for slot, tokens in GATED_VALUE_SLOTS:
                    evidence = f"[PEND\u00caNCIA GATED: {slot}]".encode()
                    for token in tokens:
                        expected_content = expected_content.replace(
                            token.encode(), evidence
                        )
                for token, value in PROSE_VALUES.items():
                    expected_content = expected_content.replace(
                        token.encode(), value.encode()
                    )
                generated_content = generated.read(item.filename)
                if "/media/" not in f"/{item.filename}":
                    assert generated_content == expected_content
                elif item.filename in BOILERPLATE_MEDIA:
                    assert generated_content == source_content
                else:
                    assert generated_content != source_content


def test_cli_stop_condition_produces_no_document(tmp_path: Path) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"), tmp_path / "master"
    ).master
    output = tmp_path / "reports"

    completed = run_generator(master, output, "64-2026")

    assert completed.returncode == 0, completed.stderr
    assert "STOP CONDITION\t64-2026\tLink contains a delivery date" in completed.stdout
    assert not list(output.rglob("*.docx"))
