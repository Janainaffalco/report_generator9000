"""Keep Loja's curated Blocks visible while public discovery is incomplete."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image

from .block_stamping import BlockImage
from .lista_paginas import (
    CATEGORIA_PRODUTO,
    EVIDENCIA_AUSENTE,
    FILTRO_PRODUTO,
    PRODUTO_PUBLICADO,
    VISAO_MOBILE,
    Pagina,
)
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
        page = Pagina(EVIDENCIA_AUSENTE, heading, capture_origin, heading)
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
    storefront_types = {
        CATEGORIA_PRODUTO,
        FILTRO_PRODUTO,
        PRODUTO_PUBLICADO,
        VISAO_MOBILE,
    }
    storefront_extras = [
        item for item in extras if item[0].tipo in storefront_types
    ]
    other_extras = [
        item for item in extras if item[0].tipo not in storefront_types
    ]
    first: list[tuple[Pagina, BlockImage]] = []
    for item in selected[:-2]:
        first.append(item)
        if item[0].titulo_bloco == "SEÇÃO PRODUTOS":
            first.extend(storefront_extras)
    # Institutional/legal pages outside the curated Loja grammar retain their
    # source-grounded Captures immediately before Cabeçalho and Rodapé.
    first.extend(other_extras)
    first.extend(selected[-2:])
    assert tuple(item[0].titulo_bloco for item in first[-2:]) == required[-2:]
    return (
        tuple(page for page, _image in first),
        tuple(image for _page, image in first),
        tuple(pendencias),
    )
