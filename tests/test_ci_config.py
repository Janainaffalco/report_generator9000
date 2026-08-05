from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_uses_the_web_package_manager_pin() -> None:
    package = json.loads((ROOT / "web" / "package.json").read_text("utf-8"))
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        "utf-8"
    )

    assert package["packageManager"] != "pnpm@11.13.0"
    assert "package_json_file: web/package.json" in workflow
    assert 'version: "11"' not in workflow


def test_container_build_does_not_wait_for_tests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        "utf-8"
    )

    assert "\n    needs: test\n" not in workflow


def test_python_job_receives_the_built_frontend_shell() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        "utf-8"
    )

    assert "actions/upload-artifact@v4" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "name: web-shell" in workflow
    assert "path: report_generator9000/web_dist" in workflow
