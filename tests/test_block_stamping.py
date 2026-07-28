from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree

from fixtures.docx_builder import png_bytes

from report_generator9000.block_stamping import BlockImage, stamp_blocks
from report_generator9000.docx_package import open_docx_package
from report_generator9000.gates.blocks import check_block_integrity
from report_generator9000.lista_paginas import (
    AREA_LEGAL,
    ELEMENTO_TRANSVERSAL,
    PAGINA_PRINCIPAL,
    Pagina,
)
from report_generator9000.master import build_master
from report_generator9000.run_context import RunContext
from tests.test_master_build import approved_source


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _block_image(
    tmp_path: Path,
    pagina: Pagina,
    index: int,
    *,
    origin: str = "capture",
) -> BlockImage:
    content = png_bytes(
        40 + index,
        20 + index,
        red=30 * index,
        green=180 - 20 * index,
        blue=60 + 10 * index,
    )
    folder = tmp_path / ("gated" if origin == "gated" else "captures")
    folder.mkdir(exist_ok=True)
    path = folder / f"capture-{index}.png"
    path.write_bytes(content)
    return BlockImage(
        pagina=pagina,
        path=path,
        digest=hashlib.sha256(content).hexdigest(),
        origin=origin,
    )


def test_blocks_are_stamped_from_lista_with_bound_provenant_images(
    tmp_path: Path,
) -> None:
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master
    pages = (
        Pagina(PAGINA_PRINCIPAL, "Home", "https://example.test/", "PÁGINA HOME"),
        Pagina(
            PAGINA_PRINCIPAL,
            "Serviços",
            "https://example.test/servicos",
            "SEÇÃO SERVIÇOS",
        ),
        Pagina(
            AREA_LEGAL,
            "Política de Privacidade",
            "https://example.test/privacidade",
            "POLÍTICA DE PRIVACIDADE",
        ),
        Pagina(
            ELEMENTO_TRANSVERSAL,
            "Rodapé",
            "https://example.test/",
            "RODAPÉ",
        ),
    )
    images = tuple(
        _block_image(
            tmp_path,
            pagina,
            index,
            origin="gated" if index == 3 else "capture",
        )
        for index, pagina in enumerate(pages, start=1)
    )

    result = stamp_blocks(
        master,
        tmp_path / "stamped.docx",
        pages,
        images,
        capture_folder=tmp_path / "captures",
        drop_folder=tmp_path / "gated",
    )

    package = open_docx_package(result.document)
    assert result.headings == tuple(page.titulo_bloco for page in pages)
    assert len(result.artifacts) == len(pages)
    assert {item.digest for item in result.artifacts} == {
        image.digest for image in images
    }
    assert {item.origin for item in result.artifacts} == {"capture", "gated"}
    stamped_media = {
        item.sha256
        for item in package.media
        if item.part_name.startswith("word/media/block-")
    }
    assert stamped_media == {image.digest for image in images}
    assert check_block_integrity(
        package,
        RunContext(media=result.artifacts, blocks=result.headings),
    ).passed

    with ZipFile(result.document) as archive:
        assert "word/media/image2.png" not in archive.namelist()
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{W}body")
    assert body is not None
    children = list(body)
    start = next(
        index
        for index, item in enumerate(children)
        if "".join(node.text or "" for node in item.iter(f"{W}t")).strip()
        == "PÁGINA HOME E SEÇÕES"
    )
    end = next(
        index
        for index, item in enumerate(children[start + 1 :], start + 1)
        if "".join(node.text or "" for node in item.iter(f"{W}t")).strip()
        == "PAINEL DE CONFIGURAÇÃO WORDPRESS"
    )
    region = children[start + 1 : end]
    assert len(region) == len(pages) * 2
    for offset, page in enumerate(pages):
        heading, image = region[offset * 2 : offset * 2 + 2]
        assert "".join(node.text or "" for node in heading.iter(f"{W}t")) == (
            page.titulo_bloco
        )
        assert heading.find(f"{W}pPr/{W}keepNext") is not None
        style = heading.find(f"{W}pPr/{W}pStyle")
        assert style is None or style.get(f"{W}val") not in {
            "Heading1",
            "Heading2",
        }
        extent = image.find(
            ".//{http://schemas.openxmlformats.org/drawingml/2006/"
            "wordprocessingDrawing}extent"
        )
        assert extent is not None
        width, height = images[offset].pixel_size
        assert int(extent.get("cy")) == round(
            int(extent.get("cx")) * height / width
        )


def test_block_image_must_belong_to_the_declared_run_folder(
    tmp_path: Path,
) -> None:
    page = Pagina(
        PAGINA_PRINCIPAL,
        "Home",
        "https://example.test/",
        "PÁGINA HOME",
    )
    image = _block_image(tmp_path, page, 1)
    master = build_master(
        approved_source(tmp_path / "approved.docx"),
        tmp_path / "master",
    ).master

    from pytest import raises

    with raises(ValueError, match="outside this run's Capture folder"):
        stamp_blocks(
            master,
            tmp_path / "stamped.docx",
            (page,),
            (image,),
            capture_folder=tmp_path / "some-other-run",
        )
