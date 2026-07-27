from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


HEADERS = (
    " Titulo ",
    "n\N{MASCULINE ORDINAL INDICATOR}  da   pasta",
    "Tema Contrato SENAI",
    "CNPJ",
    "Razao   Social",
    "Consultor responsavel",
    "Kick off",
    "Link ",
    "Relatorio pronto?",
)
IN_SCOPE = "Insercao digital - Desenvolvimento de WebSite"
OUT_OF_SCOPE = "Implantacao de Loja Virtual"
ROWS = (
    (
        "011616/2026", "40-2026", IN_SCOPE, "52052612000121",
        "DENISE BARROS DE ALMEIDA", "Bruno Henrique Santana Leal",
        datetime(2026, 4, 15), "https://denise.example/", "",
    ),
    (
        "011642/2026", "64-2026", IN_SCOPE, "24465685000100",
        "CARLA MONIZE LOPES", "Bruno Henrique Santana Leal",
        datetime(2026, 4, 20), datetime(2026, 7, 20, 10, 30), "",
    ),
    (
        "011675/2026", "37-2026", IN_SCOPE, "35980485000101",
        "MAGICO TECH", "Bruno Henrique Santana Leal",
        datetime(2026, 4, 14), "", "",
    ),
    (
        "011739/2026", "63-2026", IN_SCOPE, "67671933000181",
        "SAN FRIO REFRIGERACAO", "Bruno Henrique Santana Leal",
        datetime(2026, 5, 4),
        "https://midnightblue-jellyfish-121804.hostingersite.com/sanfrio.com.br",
        "",
    ),
    (
        "011749/2026", "50-2026", IN_SCOPE, "58548043000196",
        "LARI TORELLO CONSULTORIA LTDA", "Bruno Henrique Santana Leal",
        datetime(2026, 5, 5), "https://lari.example/", "",
    ),
    (
        "011289/2026", "26-2026", IN_SCOPE, "18034491000157",
        "SANTANA BELLINI", "Christian Albuquerque Alonso",
        datetime(2026, 3, 24), "https://complete.example/", "ok",
    ),
    (
        "011910/2026", "", IN_SCOPE, "31245686000104",
        "CLINICA SILVIA", "Bruno Henrique Santana Leal",
        datetime(2026, 5, 13), "https://missing-pasta.example/", "",
    ),
    (
        "011547/2026", "72-2026", OUT_OF_SCOPE, "18573230000105",
        "CASA NOSSA", "Christian Albuquerque Alonso",
        datetime(2026, 4, 21), "https://out-of-scope.example/", "",
    ),
    (
        "012000/2026", "80-2026", IN_SCOPE, "1234",
        "CNPJ INVALIDO", "Bruno Henrique Santana Leal",
        datetime(2026, 5, 8), "https://invalid-cnpj.example/", "",
    ),
    (
        "012001/2026", "81-2026", IN_SCOPE, "52999999000199",
        "KICK OFF INVALIDO", "Bruno Henrique Santana Leal",
        "amanha", "https://invalid-kickoff.example/", "",
    ),
)
ROW_NUMBERS = (2, 3, 4, 5, 6, 7, 8, 10, 11, 13)


def _xml_cell(column: str, row: int, value: object) -> str:
    reference = f"{column}{row}"
    if isinstance(value, datetime):
        serial = (value - datetime(1899, 12, 30)).total_seconds() / 86400
        return f'<c r="{reference}" s="1"><v>{serial:g}</v></c>'
    return (
        f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
    )


def _sheet_xml() -> str:
    all_rows = ((1, HEADERS), *zip(ROW_NUMBERS, ROWS))
    rows = []
    for number, values in all_rows:
        cells = "".join(
            _xml_cell(chr(ord("A") + index), number, value)
            for index, value in enumerate(values)
        )
        rows.append(f'<row r="{number}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
    )


PARTS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    ),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    ),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Resumo" sheetId="1" r:id="rId1"/>'
        '<sheet name="LV e Site" sheetId="2" r:id="rId2"/></sheets></workbook>'
    ),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    ),
    "xl/styles.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font/></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders>'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164" applyNumberFormat="1"/></cellXfs>'
        '</styleSheet>'
    ),
}


def build(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Resumo</t></is></c></row></sheetData>'
        '</worksheet>'
    )
    parts = {
        **PARTS,
        "xl/worksheets/sheet1.xml": summary,
        "xl/worksheets/sheet2.xml": _sheet_xml(),
    }
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name, text in parts.items():
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = ZIP_STORED
            archive.writestr(info, text.encode("utf-8"))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    build(arguments.output)
