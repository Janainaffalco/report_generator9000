from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.check_cli import run_check, write_context
from report_generator9000.run_context import (
    Artifact,
    Pendencia,
    RunContext,
    load_run_context,
)


FIXTURE = Path(__file__).parent / "fixtures" / "minimal.docx"


def test_load_reads_every_declared_field(tmp_path: Path) -> None:
    location = write_context(
        tmp_path / "run.json",
        {
            "pasta": "115-2026",
            "media": [
                {
                    "digest": "AB12",
                    "origin": "boilerplate",
                    "label": "cabecalho SEBRAE",
                },
                {
                    "digest": "cd34",
                    "origin": "gated",
                    "label": "paleta",
                    "source": "gated/115-2026/paleta.png",
                },
            ],
            "boilerplate_links": ["https://w3techs.example/"],
            "input_origins": ["https://cliente.example/"],
            "drop_folder": "gated/115-2026",
            "capture_folder": "outputs/115-2026_CLIENTE/capturas",
            "output_paths": ["outputs/115-2026_CLIENTE/RELATORIO.docx"],
            "blocks": ["PÁGINA HOME", "CABEÇALHO"],
            "pendencias": [
                {
                    "slot": "paleta",
                    "classification": "GATED",
                    "reason": "não fornecida",
                    "evidence": "ef56",
                }
            ],
        },
    )

    context = load_run_context(location)

    assert context.pasta == "115-2026"
    assert context.media == (
        Artifact(digest="ab12", origin="boilerplate", label="cabecalho SEBRAE"),
        Artifact(
            digest="cd34",
            origin="gated",
            label="paleta",
            source="gated/115-2026/paleta.png",
        ),
    )
    assert context.boilerplate_links == frozenset({"https://w3techs.example/"})
    assert context.input_origins == frozenset({"https://cliente.example/"})
    assert context.drop_folder == "gated/115-2026"
    assert context.capture_folder == "outputs/115-2026_CLIENTE/capturas"
    assert context.output_paths == ("outputs/115-2026_CLIENTE/RELATORIO.docx",)
    assert context.blocks == ("PÁGINA HOME", "CABEÇALHO")
    assert context.pendencias == (
        Pendencia(
            slot="paleta",
            classification="GATED",
            reason="não fornecida",
            evidence="ef56",
        ),
    )


def test_an_empty_context_declares_nothing() -> None:
    context = RunContext()

    assert context.pasta == ""
    assert context.media == ()
    assert context.pendencias == ()
    assert context.media_by_digest() == {}


def test_media_is_grouped_and_filtered_by_origin() -> None:
    boilerplate = Artifact(digest="aa", origin="boilerplate", label="marca")
    capture = Artifact(digest="bb", origin="capture", label="home")
    reused = Artifact(digest="bb", origin="gated", label="home again")
    context = RunContext(media=(boilerplate, capture, reused))

    assert context.artifacts_of("capture") == (capture,)
    assert context.media_by_digest()["bb"] == (capture, reused)


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"pasta": "115-2026", "tema": "x"}, "unknown field(s) tema"),
        (
            {"media": [{"digest": "aa", "origin": "invented", "label": "x"}]},
            "'invented' is not one of",
        ),
        ({"media": [{"origin": "capture", "label": "x"}]}, "missing required field digest"),
        (
            {
                "pendencias": [
                    {
                        "slot": "paleta",
                        "classification": "MAYBE",
                        "reason": "r",
                        "evidence": "e",
                    }
                ]
            },
            "'MAYBE' is not one of",
        ),
        ({"blocks": "PÁGINA HOME"}, "expected a list of strings"),
        ({"pasta": 115}, "expected a string"),
    ],
)
def test_a_malformed_context_names_the_field_it_rejected(
    tmp_path: Path, document: dict, expected: str
) -> None:
    location = write_context(tmp_path / "run.json", document)

    with pytest.raises(ValueError) as failure:
        load_run_context(location)

    assert expected in str(failure.value)


def test_invalid_json_is_reported_with_the_file(tmp_path: Path) -> None:
    location = tmp_path / "run.json"
    location.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError) as failure:
        load_run_context(location)

    assert "invalid JSON" in str(failure.value)
    assert "run.json" in str(failure.value)


def test_check_refuses_a_malformed_context(tmp_path: Path) -> None:
    location = write_context(tmp_path / "run.json", {"pasta": "1", "tema": "x"})

    completed = run_check(FIXTURE, location)

    assert completed.returncode == 2
    assert "unknown field(s) tema" in completed.stderr
