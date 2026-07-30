from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.dev.yaml"
MASTER = ROOT / "master-build-check" / "MASTER.docx"


def test_dev_compose_mounts_approved_master_read_only() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")

    environment = os.environ.copy()
    environment["REPORT_DEV_MASTER_PATH"] = str(MASTER)
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
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    config = json.loads(result.stdout)
    master_mount = next(
        (
            volume
            for volume in config["services"]["backend"]["volumes"]
            if volume["target"] == "/app/data/master/MASTER.docx"
        ),
        None,
    )
    assert master_mount is not None
    assert Path(master_mount["source"]).resolve() == MASTER.resolve()
    assert master_mount["read_only"] is True
