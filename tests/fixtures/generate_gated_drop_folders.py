from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from docx_builder import png_bytes


ENGAGEMENT_FOLDER = "50-2026_LARI TORELLO CONSULTORIA LTDA"
IMAGE_FILES = (
    "paleta.png",
    "login.png",
    "painel.png",
    "yoast-a.png",
    "yoast-b.png",
    "yoast-c.png",
    "drive.png",
    "kickoff.jpg",
    "entrega.png",
)
IDENTITY = {
    "pasta": "50-2026",
    "razao_social": "LARI TORELLO CONSULTORIA LTDA",
}
COMPLETE_VALUES = {
    **IDENTITY,
    "plano_hospedagem": "PLANO BUSINESS",
    "email_cliente": "handoff@lari.example",
    "data_entrega": "30/06/2026",
    "data_backup": "29/06/2026",
    "link_codigo_fonte": "https://drive.google.com/drive/folders/codigo",
    "link_guia_rapido": "https://drive.google.com/drive/folders/guia",
    "link_identidade_visual": "https://drive.google.com/drive/folders/visual",
    "link_usuarios_senhas": "https://drive.google.com/drive/folders/acessos",
    "dominio_publicado": "lari-publicado.example",
}
PARTIAL_VALUES = {
    **IDENTITY,
    "email_cliente": "handoff-parcial@lari.example",
    "dominio_publicado": "lari-parcial.example",
}
WRONG_VALUES = {
    **COMPLETE_VALUES,
    "pasta": "63-2026",
    "razao_social": "SAN FRIO REFRIGERACAO",
}
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAIBAQIBAQICAgICAgICAwUDAwMDAwYE"
    "BAMFBwYHBwcGBwcICQsJCAgKCAcHCg0KCgsMDAwMBwkODw0MDgsMDAz/2wBDAQIC"
    "AgMDAwYDAwYMCAcIDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA"
    "wMDAwMDAwMDAwMDAwMDAz/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBA"
    "QEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQR"
    "BRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY"
    "3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJ"
    "WWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5"
    "ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL"
    "/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHB"
    "CSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpj"
    "ZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
    "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIR"
    "AxEAPwD9/KKKKAP/2Q=="
)


def _write_values(folder: Path, values: dict[str, str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "valores.json").write_text(
        json.dumps(values, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build(root: Path) -> Path:
    complete = root / "complete" / ENGAGEMENT_FOLDER
    partial = root / "partial" / ENGAGEMENT_FOLDER
    wrong = root / "wrong" / ENGAGEMENT_FOLDER
    absent = root / "absent"
    _write_values(complete, COMPLETE_VALUES)
    _write_values(partial, PARTIAL_VALUES)
    _write_values(wrong, WRONG_VALUES)
    absent.mkdir(parents=True, exist_ok=True)
    (absent / ".gitkeep").write_bytes(b"")

    for index, name in enumerate(IMAGE_FILES, start=1):
        content = (
            JPEG
            if name.endswith(".jpg")
            else png_bytes(8 + index, 5 + index, red=index * 17)
        )
        (complete / name).write_bytes(content)
    (partial / "paleta.png").write_bytes(
        png_bytes(11, 3, red=0x33, green=0x66, blue=0x99)
    )
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    build(arguments.output)
