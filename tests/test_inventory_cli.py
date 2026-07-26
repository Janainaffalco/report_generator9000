from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile


FIXTURE = Path(__file__).parent / "fixtures" / "minimal.docx"
FIXTURE_GENERATOR = FIXTURE.with_name("generate_minimal_docx.py")


def run_command(
    command: list[str], stdout_path: Path, stderr_path: Path
) -> subprocess.CompletedProcess[str]:
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        return subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )


def test_inventory_reports_package_media_relationships_and_slots(
    tmp_path: Path,
) -> None:
    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    completed = run_command(
        [
            sys.executable,
            "-m",
            "report_generator9000.inventory",
            str(FIXTURE),
        ],
        stdout_path,
        stderr_path,
    )

    output = stdout_path.read_text(encoding="utf-8")
    errors = stderr_path.read_text(encoding="utf-8")
    assert completed.returncode == 0, errors
    assert "PARTS (5)" in output
    assert "word/media/sample.png" in output
    assert "334f169f3f0085d4faf032624c21f5abe4def7b2a18bd598401f55563b645ab9" in output
    assert "2 x 3 px" in output
    assert "rIdImage" in output
    assert "word/media/sample.png" in output
    assert "rIdExternal" in output
    assert "https://example.com/" in output
    assert "SLOTS (1)" in output
    assert "999999 x 888888 EMU" in output


def test_fixture_generator_reproduces_committed_document(tmp_path: Path) -> None:
    generated = tmp_path / "generated.docx"
    stdout_path = tmp_path / "generator-stdout.txt"
    stderr_path = tmp_path / "generator-stderr.txt"

    completed = run_command(
        [sys.executable, str(FIXTURE_GENERATOR), "--output", str(generated)],
        stdout_path,
        stderr_path,
    )

    assert completed.returncode == 0, stderr_path.read_text(encoding="utf-8")
    with ZipFile(generated) as generated_package, ZipFile(
        FIXTURE
    ) as committed_package:
        assert generated_package.namelist() == committed_package.namelist()
        assert all(
            (
                part.create_system,
                part.date_time,
                part.external_attr,
                part.compress_type,
            )
            == (3, (2026, 1, 1, 0, 0, 0), 0o600 << 16, ZIP_STORED)
            for part in generated_package.infolist()
        )
        for name in generated_package.namelist():
            assert generated_package.read(name) == committed_package.read(name)
