from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tests.ops_helpers import run_ops_cli

RUNNER = ROOT / "ops" / "ops_edit_batch.py"


def _run_batch(data_dir: Path, plan: dict) -> subprocess.CompletedProcess[str]:
    plan_path = data_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    env = {
        **os.environ,
        "KG_DATA_DIR": str(data_dir),
    }
    return subprocess.run(
        [sys.executable, str(RUNNER), str(plan_path)],
        capture_output=True,
        text=True,
        env=env,
    )


def test_ops_edit_batch_applies_multi_step_plan(tmp_path: Path) -> None:
    uid = "u_batch"
    proc = _run_batch(
        tmp_path,
        {
            "schema": "kg.ops_edit_batch.v1",
            "ops": [
                ["user-create", uid, "--email", "demo@example.com", "--commit", "--json"],
                ["notebook-create", uid, "Turns of Phrase", "--color", "#4F6470", "--commit", "--json"],
                ["card-add", uid, "file in", "--meaning", "排隊進入", "--commit", "--json"],
                ["card-move", uid, "file in", "--to-notebook", "Turns of Phrase", "--commit", "--json"],
                ["user-config-set", uid, "--active-notebook", "Turns of Phrase", "--commit", "--json"],
            ],
        },
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["count"] == 5
    state = json.loads(run_ops_cli(str(tmp_path), "world-state", uid, "--json").stdout)
    assert state["config"]["vocab_ui"]["active_notebook_id"] != "default"
    card = json.loads(run_ops_cli(str(tmp_path), "card-get", uid, "file in", "--json").stdout)["cards"][0]
    assert card["notebook_id"] != "default"


def test_ops_edit_batch_stops_on_first_failure(tmp_path: Path) -> None:
    uid = "u_batch_fail"
    proc = _run_batch(
        tmp_path,
        {
            "schema": "kg.ops_edit_batch.v1",
            "ops": [
                ["user-create", uid, "--commit", "--json"],
                ["notebook-create", uid, "Demo", "--commit", "--json"],
                ["card-move", uid, "missing card", "--to-notebook", "Demo", "--commit", "--json"],
                ["notebook-create", uid, "ShouldNotRun", "--commit", "--json"],
            ],
        },
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["count"] == 3
    assert payload["stoppedEarly"] is True
    state = json.loads(run_ops_cli(str(tmp_path), "world-state", uid, "--json").stdout)
    notebook_names = [nb["name"] for nb in state["notebooks"]]
    assert "Demo" in notebook_names
    assert "ShouldNotRun" not in notebook_names
