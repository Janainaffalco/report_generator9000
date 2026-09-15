"""Keep Loja's curated Blocks visible while public discovery is incomplete."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image

from .block_stamping import BlockImage
from .lista_paginas import PAGINA_PRINCIPAL, Pagina
from .placeholders import render_placeholder
from .run_context import Pendencia


_PRIVACY_ALIAS = "POLÍTICA DE PRIVACIDADE"


def loja_draft_blocks(
    required: tuple[str, ...],
    pages: tuple[Pagina, ...],
    images: tuple[BlockImage, ...],
    capture_folder: Path,
    capture_origin: str,
) -> tuple[tuple[Pagina, ...], tuple[BlockImage, ...], tuple[Pendencia, ...]]:
    """Use confirmed Captures where possible and classify missing Loja Blocks."""
    by_heading: dict[str, tuple[Pagina, BlockImage]] = {}
    for page, image in zip(pages, images):
        heading = (
            "POLÍTICAS DE PRIVACIDADE"
            if page.titulo_bloco == _PRIVACY_ALIAS
            else page.titulo_bloco
        )
        if heading in required and heading not in by_heading:
            renamed = replace(page, titulo_bloco=heading)
            by_heading[heading] = (renamed, replace(image, pagina=renamed))

    base = Image.new("RGB", (1200, 675), "white")
    buffer = BytesIO()
    base.save(buffer, format="PNG")
    original = buffer.getvalue()
    selected: list[tuple[Pagina, BlockImage]] = []
    pendencias: list[Pendencia] = []
    for index, heading in enumerate(required, start=1):
        if heading in by_heading:
            selected.append(by_heading[heading])
            continue
        page = Pagina(PAGINA_PRINCIPAL, heading, capture_origin, heading)
        content = render_placeholder(
            original, "TOOL_BLOCKED", heading, 1200, 675
        )
        path = capture_folder / "embutir" / f"loja-missing-{index:02d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        selected.append((page, BlockImage(page, path, digest, "placeholder")))
        pendencias.append(
            Pendencia(
                slot=f"loja_block_{index:02d}",
                classification="TOOL_BLOCKED",
                reason=f"nenhuma página pública confirmada para {heading}",
                evidence=digest,
                name=heading,
                page="VITRINE E PÁGINAS",
                required_action=f"Revisar {heading} no Word",
            )
        )

    extras = [
        (page, image) for page, image in zip(pages, images)
        if page.titulo_bloco not in required
        and page.titulo_bloco != _PRIVACY_ALIAS
    ]
    # Institutional/legal pages outside the curated Loja grammar still retain
    # their source-grounded Captures, ahead of transversal Cabeçalho/Rodapé.
    transversal = required[-2:]
    first = selected[:-2] + extras + selected[-2:]
    assert tuple(item[0].titulo_bloco for item in first[-2:]) == transversal
    return (
        tuple(page for page, _image in first),
        tuple(image for _page, image in first),
        tuple(pendencias),
    )
