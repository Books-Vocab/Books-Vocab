from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "ops" / "demo"


def test_emit_backend_check_uses_the_shipped_non_stub_contract():
    """The backend CLI documents and returns its real dry-run contract."""
    source = (DEMO_DIR / "build_demo.py").read_text(encoding="utf-8")
    assert "Phase A" not in source
    assert '"mode": "stub"' not in source

    result = subprocess.run(
        [
            "uv",
            "run",
            "--locked",
            "python",
            "../ops/demo/build_demo.py",
            "emit-backend",
            "--check",
            "--json",
        ],
        cwd=ROOT / "backend",
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["mode"] == "ok"
    assert payload["target"] == "emit-backend"
    assert payload["check"] is True
    assert payload["commit"] is False
    assert payload["result"]["drift"] is False
    assert payload["result"]["expectation_schema"] == "kg.ops_world_expectation.v1"
    assert payload["result"]["expectation_path"] == "ops/demo/demo_expectation.json"
