from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.dev.yaml"
MASTER = ROOT / "report_generator9000" / "assets" / "MASTER.docx"


def test_dev_compose_uses_the_versioned_master_from_the_source_mount() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")

    result = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    config = json.loads(result.stdout)
    assert MASTER.is_file()
    assert config["services"]["backend"]["environment"].get(
        "REPORT_MASTER_PATH"
    ) is None
    assert not any(
        volume["target"] == "/app/data/master/MASTER.docx"
        for volume in config["services"]["backend"]["volumes"]
    )
