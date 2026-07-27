from __future__ import annotations

from pathlib import Path

from fixtures.docx_builder import RelationshipSpec, build_docx, paragraph, png_bytes

from report_generator9000.docx_package import open_docx_package
from report_generator9000.master import EXPECTED_TOKENS, build_master


def approved_source(path: Path) -> Path:
    return build_docx(
        path,
        paragraphs=[
            paragraph("demanda 010028/2025"),
            paragraph("ARGEL RESISTENCIAS ELETRICAS LTDA"),
            paragraph("64.525.744/0001-02"),
            paragraph("Christian Albuquerque Alonso"),
            paragraph(
                "A ARGEL Resistências Elétricas LTDA é especializada na "
                "fabricação e comercialização de resistências elétricas."
            ),
            paragraph("O responsável pela ARGEL preparou o site."),
            paragraph("A estrutura do site contempla as páginas Home."),
            paragraph("Backup do código fonte – última versão (data 22/07/2026)"),
            paragraph("Assinatura: PLANO SINGLE"),
            paragraph("Domínio: argelresistencia.com.br"),
            paragraph("https://onhttps://argelresistencia.com.br/wp-admin/", hyperlink="rId25"),
            paragraph("Disponibilizamos links para download.", hyperlink="rId2"),
            paragraph("Ressaltamos a importância de alterar as senhas após entrega, Além de realizar o download no e-mail argelresistencias@hotmail.com."),
            paragraph("O código fonte do website desenvolvido para o cliente ARGEL RESISTENCIAS ELETRICAS LTDA| CNPJ: 64.525.744/0001-02 foi cedido por meio do link: https://drive.google.com/drive/folders/source"),
            paragraph("Guia Rápido -https://drive.google.com/drive/folders/guide"),
            paragraph("ID Visual - https://drive.google.com/drive/folders/visual"),
            paragraph("Usuários e Senhas - https://drive.google.com/drive/folders/users"),
            paragraph("KickOff em 05/02/2026"),
            paragraph("Entrega em 25/06/2026"),
            paragraph("SMTP Mailer – Protocolo de envoi de e-mail"),
            paragraph("Por segurança, o tempo de bloqueia aumenta para 24 horas."),
            paragraph("opções, referentes as ferramentas do WordPress."),
            paragraph("funcionalidades que foge do objetivo do presente documento."),
            paragraph('No menu "Plugins", verifique as atualizações disponíveis. ".'),
            paragraph("2.10 Indicadores14"),
            paragraph("A portal web é o principal canal e funcionam como um hub."),
        ],
        media={
            "media/image1.png": png_bytes(8, 8, blue=0xFF),
            "media/image2.png": png_bytes(16, 9, green=0xC0),
        },
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png"),
            RelationshipSpec(id="rIdImage2", target="media/image2.png"),
            RelationshipSpec(
                id="rId25",
                target="https://ondviajar.com.br/wp-admin/",
                kind="hyperlink",
                external=True,
            ),
            RelationshipSpec(
                id="rId2",
                target="https://drive.google.com/drive/folders/downloads",
                kind="hyperlink",
                external=True,
            ),
        ],
    )


def test_master_build_is_reproducible_and_auditable(tmp_path: Path) -> None:
    source = approved_source(tmp_path / "approved.docx")
    first = build_master(source, tmp_path / "one")
    second = build_master(source, tmp_path / "two")

    assert first.master.read_bytes() == second.master.read_bytes()
    package = open_docx_package(first.master)
    assert EXPECTED_TOKENS <= {run.text for item in package.paragraphs for run in item.runs}
    assert all(
        run.text == token
        for item in package.paragraphs
        for run in item.runs
        for token in EXPECTED_TOKENS
        if token in run.text
    )
    assert all("argel" not in (part.text or "").casefold() for part in package.parts)
    assert all("ondviajar" not in relation.target for relation in package.relationships)
    assert "word/media/image2.png" in first.diff.read_text(encoding="utf-8")
    assert "rId2: Disponibilizamos links para download." in first.diff.read_text(encoding="utf-8")
    assert "2.10 Indicadores14" in first.diff.read_text(encoding="utf-8")
    assert "A portal web" in first.diff.read_text(encoding="utf-8")
