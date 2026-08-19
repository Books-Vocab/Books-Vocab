from __future__ import annotations

import importlib.util
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


def _load_batch_module():
    spec = importlib.util.spec_from_file_location("ops_edit_batch_under_test", RUNNER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ops_cli_ready() -> bool:
    """Whether `run_ops_cli` can actually run under this interpreter.

    The local gate's ops-pytest fallback runs all of `ops/tests` under
    `uv run --no-project`, which has no backend dependencies. Both tests then died
    on a JSONDecodeError parsing empty stdout — a BLOCK gate that could only ever
    be red, blocking every change that reached the fallback while saying nothing
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


@pytest.mark.parametrize(
    ("stop_on_error", "expected_count", "expected_stopped_early"),
    [(False, 2, False), (True, 1, True)],
)
def test_ops_edit_batch_honors_explicit_boolean_stop_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stop_on_error: bool,
    expected_count: int,
    expected_stopped_early: bool,
) -> None:
    module = _load_batch_module()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "schema": "kg.ops_edit_batch.v1",
        "stopOnError": stop_on_error,
        "ops": [["first"], ["second"]],
    }), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            returncode=1 if len(calls) == 1 else 0,
            stdout="",
            stderr="first failed",
        )

    monkeypatch.setattr(module, "_default_ops_edit_path", lambda: tmp_path / "ops_edit.py")
    monkeypatch.setattr(module, "_build_ops_edit_cmd", lambda _path: ["fake-ops-edit"])
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.main([str(plan_path)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["count"] == expected_count
    assert payload["stoppedEarly"] is expected_stopped_early
    assert [call[-1] for call in calls] == ["first", "second"][:expected_count]


@pytest.mark.parametrize("invalid_value", ["false", 0, {}, []])
def test_ops_edit_batch_rejects_non_boolean_stop_on_error_before_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_value: object,
) -> None:
    module = _load_batch_module()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "schema": "kg.ops_edit_batch.v1",
        "stopOnError": invalid_value,
        "ops": [["first"]],
    }), encoding="utf-8")

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid plan must not execute an operation")

    monkeypatch.setattr(module.subprocess, "run", fail_if_called)

    assert module.main([str(plan_path)]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == "plan.stopOnError 必須是 boolean"
    assert payload["count"] == 0
    assert payload["results"] == []


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
