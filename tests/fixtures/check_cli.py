"""Drive the `check` entry point the way a developer does, and read it back."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_context(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run_check(
    document: Path, context: Path | None = None
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "report_generator9000.check",
        str(document),
    ]
    if context is not None:
        command.extend(["--context", str(context)])
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
