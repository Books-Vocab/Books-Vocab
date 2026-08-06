from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tests.ops_helpers import run_ops_cli

RUNNER = ROOT / "ops" / "ops_edit_batch.py"


def _ops_cli_ready() -> bool:
    """Whether `run_ops_cli` can actually run under this interpreter.

    The cutover gate's ops-pytest fallback runs all of `ops/tests` under
    `uv run --no-project`, which has no backend dependencies. Both tests then died
    on a JSONDecodeError parsing empty stdout — a BLOCK gate that could only ever
    be red, blocking every cutover that reached the fallback while saying nothing
    about the change under test (IMP-20260806-041d07).

    The probe deliberately targets `run_ops_cli`, NOT `ops_edit_batch.py`: the
    batch runner starts fine without the backend env (measured: rc=0, 939 bytes of
    JSON), and it is the LATER `run_ops_cli` assertions that fail, because
    `ops_cli.py` imports `httpx`. Probing the runner would have been a check
    kinder than the thing it guards — green while the guarded code still dies.

    Shape follows test_demo_ios_spec_emitter.py's `_backend_cli_ready`: the
    sandbox run says so out loud instead of failing, and a run that HAS the deps
    still executes every assertion.
    """
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); "
         "from backend.tests.ops_helpers import run_ops_cli; "
         "import tempfile; "
         "p = run_ops_cli(tempfile.mkdtemp(), 'world-state', 'probe', '--json'); "
         "sys.exit(p.returncode)" % str(ROOT)],
        capture_output=True, text=True,
    )
    return probe.returncode == 0


REQUIRES_BACKEND = pytest.mark.skipif(
    not _ops_cli_ready(),
    reason="backend deps unavailable to sys.executable (sandbox `uv run --no-project`) "
           "— run with `uv run --project backend --with pytest` to exercise these",
)


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


@REQUIRES_BACKEND
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


@REQUIRES_BACKEND
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
