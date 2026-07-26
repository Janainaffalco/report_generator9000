from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from fixtures.docx_builder import RelationshipSpec, build_docx, paragraph, png_bytes


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_context(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run_check(
    document: Path, context: Path | None, tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    command = [
        sys.executable,
        "-m",
        "report_generator9000.check",
        str(document),
    ]
    if context is not None:
        command.extend(["--context", str(context)])
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
        )
    completed.stdout = stdout_path.read_text(encoding="utf-8")
    completed.stderr = stderr_path.read_text(encoding="utf-8")
    return completed


def test_media_and_link_provenance_pass_on_a_fully_declared_document(
    tmp_path: Path,
) -> None:
    image1 = png_bytes(2, 2, red=0xC0, green=0x00, blue=0x00)
    image2 = png_bytes(2, 2, red=0x00, green=0xC0, blue=0x00)
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph(image="rIdImage1"),
            paragraph(image="rIdImage2"),
            paragraph("Referência do plugin", hyperlink="rIdBoiler"),
            paragraph("Acesso ao admin", hyperlink="rIdWpAdmin"),
        ],
        media={
            "media/image1.png": image1,
            "media/image2.png": image2,
        },
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png"),
            RelationshipSpec(id="rIdImage2", target="media/image2.png"),
            RelationshipSpec(
                id="rIdBoiler",
                target="https://plugin.example.com/ref/",
                kind="hyperlink",
                external=True,
            ),
            RelationshipSpec(
                id="rIdWpAdmin",
                target="https://cliente.com.br/wp-admin/",
                kind="hyperlink",
                external=True,
            ),
        ],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "media": [
                {
                    "digest": digest_of(image1),
                    "origin": "boilerplate",
                    "label": "cabecalho SEBRAE",
                },
                {
                    "digest": digest_of(image2),
                    "origin": "capture",
                    "label": "pagina inicial",
                },
            ],
            "boilerplate_links": ["https://plugin.example.com/ref/"],
            "input_urls": ["https://cliente.com.br/"],
        },
    )

    completed = run_check(document, context, tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GATE media-provenance: PASS" in completed.stdout
    assert "GATE link-provenance: PASS" in completed.stdout


def test_media_without_provenance_is_reported(tmp_path: Path) -> None:
    image = png_bytes(2, 2)
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph(image="rIdImage1")],
        media={"media/image1.png": image},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )

    completed = run_check(document, None, tmp_path)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE media-provenance: FAIL" in completed.stdout
    assert "media-without-provenance" in completed.stdout
    assert "word/media/image1.png" in completed.stdout


def test_capture_declared_for_this_run_passes_while_second_image_fails(
    tmp_path: Path,
) -> None:
    image1 = png_bytes(2, 2, red=0xC0, green=0x00, blue=0x00)
    image2 = png_bytes(2, 2, red=0x00, green=0x00, blue=0xC0)
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph(image="rIdImage1"),
            paragraph(image="rIdImage2"),
        ],
        media={
            "media/image1.png": image1,
            "media/image2.png": image2,
        },
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png"),
            RelationshipSpec(id="rIdImage2", target="media/image2.png"),
        ],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": digest_of(image1),
                    "origin": "capture",
                    "label": "pagina inicial",
                }
            ]
        },
    )

    completed = run_check(document, context, tmp_path)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE media-provenance: FAIL (1 violation)" in completed.stdout
    assert "media-without-provenance" in completed.stdout
    assert "word/media/image2.png" in completed.stdout
    assert "word/media/image1.png" not in completed.stdout


def test_ambiguous_provenance_is_reported(tmp_path: Path) -> None:
    image = png_bytes(2, 2)
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph(image="rIdImage1")],
        media={"media/image1.png": image},
        relationships=[
            RelationshipSpec(id="rIdImage1", target="media/image1.png")
        ],
    )
    digest = digest_of(image)
    context = write_context(
        tmp_path / "run.json",
        {
            "media": [
                {
                    "digest": digest,
                    "origin": "boilerplate",
                    "label": "cabecalho SEBRAE",
                },
                {
                    "digest": digest,
                    "origin": "capture",
                    "label": "pagina inicial",
                },
            ]
        },
    )

    completed = run_check(document, context, tmp_path)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE media-provenance: FAIL" in completed.stdout
    assert "ambiguous-provenance" in completed.stdout
    assert "word/media/image1.png" in completed.stdout
    assert "boilerplate" in completed.stdout
    assert "capture" in completed.stdout
    assert "cabecalho SEBRAE" in completed.stdout
    assert "pagina inicial" in completed.stdout


def test_link_without_provenance_third_party_wpadmin_among_boilerplate(
    tmp_path: Path,
) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[
            paragraph("Plugin A", hyperlink="rIdPluginA"),
            paragraph("Plugin B", hyperlink="rIdPluginB"),
            paragraph("Plugin C", hyperlink="rIdPluginC"),
            paragraph("Admin de terceiro", hyperlink="rIdOffender"),
        ],
        relationships=[
            RelationshipSpec(
                id="rIdPluginA",
                target="https://plugin-a.example.com/",
                kind="hyperlink",
                external=True,
            ),
            RelationshipSpec(
                id="rIdPluginB",
                target="https://plugin-b.example.com/",
                kind="hyperlink",
                external=True,
            ),
            RelationshipSpec(
                id="rIdPluginC",
                target="https://plugin-c.example.com/",
                kind="hyperlink",
                external=True,
            ),
            RelationshipSpec(
                id="rIdOffender",
                target="https://terceiro.com.br/wp-admin/",
                kind="hyperlink",
                external=True,
            ),
        ],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "boilerplate_links": [
                "https://plugin-a.example.com/",
                "https://plugin-b.example.com/",
                "https://plugin-c.example.com/",
            ],
            "input_urls": ["https://cliente.com.br/"],
        },
    )

    completed = run_check(document, context, tmp_path)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE link-provenance: FAIL (1 violation)" in completed.stdout
    assert "link-without-provenance" in completed.stdout
    assert "rIdOffender" in completed.stdout
    assert "https://terceiro.com.br/wp-admin/" in completed.stdout
    assert "rIdPluginA" not in completed.stdout
    assert "rIdPluginB" not in completed.stdout
    assert "rIdPluginC" not in completed.stdout


def test_wpadmin_link_derived_from_input_host_passes(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Acesso ao admin", hyperlink="rIdWpAdmin")],
        relationships=[
            RelationshipSpec(
                id="rIdWpAdmin",
                target="https://www.cliente.com.br/wp-admin/",
                kind="hyperlink",
                external=True,
            )
        ],
    )
    context = write_context(
        tmp_path / "run.json",
        {"input_urls": ["https://cliente.com.br/"]},
    )

    completed = run_check(document, context, tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GATE link-provenance: PASS" in completed.stdout


def test_mailto_target_not_declared_fails(tmp_path: Path) -> None:
    document = build_docx(
        tmp_path / "doc.docx",
        paragraphs=[paragraph("Fale conosco", hyperlink="rIdMailto")],
        relationships=[
            RelationshipSpec(
                id="rIdMailto",
                target="mailto:contato@example.com",
                kind="hyperlink",
                external=True,
            )
        ],
    )
    context = write_context(
        tmp_path / "run.json",
        {
            "boilerplate_links": ["https://plugin.example.com/ref/"],
            "input_urls": ["https://cliente.com.br/"],
        },
    )

    completed = run_check(document, context, tmp_path)

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "GATE link-provenance: FAIL" in completed.stdout
    assert "link-without-provenance" in completed.stdout
    assert "mailto:contato@example.com" in completed.stdout
