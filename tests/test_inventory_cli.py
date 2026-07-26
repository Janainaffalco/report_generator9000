from __future__ import annotations

import hashlib
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
    assert "537e43d17939422e642cfd94104652ab2231df979714283f29c156df1db2eef1" in output
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
    with ZipFile(generated) as package:
        assert all(part.compress_type == ZIP_STORED for part in package.infolist())
    assert (
        hashlib.sha256(generated.read_bytes()).hexdigest()
        == "2875cec5da6cb30c91f883ac55227b04a3483380f792dfc47943fe3fc62a518e"
    )
    assert generated.read_bytes() == FIXTURE.read_bytes()
