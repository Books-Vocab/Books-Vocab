#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi",
#     "uvicorn[standard]",
#     "python-multipart",
#     "pytest",
# ]
# ///
"""Phase 3 — dashboard 端的 gate 狀態 + AWAITING 狀態機。

pipeline 在計畫後 / 腳本後各停一道 gate(Phase 2)。dashboard 必須:
  1. 從磁碟推導每道 gate 的三態:passed / awaiting / pending。
  2. 把「等核准」升級成 workspace 狀態 `awaiting`,讓側欄一眼看出需要你。

關鍵:gate 標記(.plan_approved/.script_approved)是新增的,既有 legacy
workspace 有 scripts/audio 卻無標記 —— 不可被誤判成 awaiting。判準用「下一相
是否已有產物」當 de-facto 核准:
  gate1 passed  ⇔ n_script>0 或 .plan_approved 存在
  gate1 awaiting⇔ plan 完成 且 n_script==0 且未 passed
  gate2 passed  ⇔ n_audio>0 或 .script_approved 存在
  gate2 awaiting⇔ scripts 完成(n_script==target>0)且 n_audio==0 且未 passed
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402


def _mk(ws: Path, rel: str, content: str = "x") -> None:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _plan(ws: Path, n: int) -> None:
    _mk(ws, "plan/overview.md", "# overview")
    for i in range(1, n + 1):
        _mk(ws, f"plan/episodes/ep_{i:02d}.md")


def _g(states: list[dict], key: str) -> str:
    return next(s["state"] for s in states if s["key"] == key)


# ─── _gate_states 純三態 ───
def test_gates_pending_when_no_plan(tmp_path):
    g = server._gate_states(tmp_path, has_plan=False, n_script=0, n_audio=0, target=0)
    assert _g(g, "plan") == "pending"
    assert _g(g, "script") == "pending"


def test_gate1_awaiting_plan_done_no_scripts(tmp_path):
    g = server._gate_states(tmp_path, has_plan=True, n_script=0, n_audio=0, target=8)
    assert _g(g, "plan") == "awaiting"
    assert _g(g, "script") == "pending"  # scripts 未完成 → gate2 還沒輪到


def test_gate1_passed_when_scripts_exist(tmp_path):
    g = server._gate_states(tmp_path, has_plan=True, n_script=3, n_audio=0, target=8)
    assert _g(g, "plan") == "passed"  # de-facto:有腳本=計畫已放行


def test_gate1_passed_when_marker_even_without_scripts(tmp_path):
    (tmp_path / ".plan_approved").write_text("ok")
    g = server._gate_states(tmp_path, has_plan=True, n_script=0, n_audio=0, target=8)
    assert _g(g, "plan") == "passed"


def test_gate2_awaiting_scripts_complete_no_audio(tmp_path):
    g = server._gate_states(tmp_path, has_plan=True, n_script=8, n_audio=0, target=8)
    assert _g(g, "plan") == "passed"
    assert _g(g, "script") == "awaiting"


def test_gate2_pending_scripts_incomplete(tmp_path):
    g = server._gate_states(tmp_path, has_plan=True, n_script=3, n_audio=0, target=8)
    assert _g(g, "script") == "pending"


def test_gate2_passed_when_audio_exists(tmp_path):
    g = server._gate_states(tmp_path, has_plan=True, n_script=8, n_audio=5, target=8)
    assert _g(g, "script") == "passed"


# ─── _workspace_summary 狀態升級 ───
def test_summary_awaiting_plan(tmp_path):
    ws = tmp_path / "awplan_abcd1234"
    _plan(ws, 8)  # plan 完成,無腳本,無標記
    s = server._workspace_summary(ws, None)
    assert s["status"] == "awaiting"
    assert _g(s["gates"], "plan") == "awaiting"


def test_summary_awaiting_script(tmp_path):
    ws = tmp_path / "awscript_abcd1234"
    _plan(ws, 3)
    for i in (1, 2, 3):
        _mk(ws, f"scripts/ep_{i}_script.md")
    s = server._workspace_summary(ws, None)
    assert s["status"] == "awaiting"
    assert _g(s["gates"], "script") == "awaiting"


def test_summary_legacy_with_audio_not_awaiting(tmp_path):
    """legacy:有腳本+音頻、無 gate 標記 → 不可誤判 awaiting。"""
    ws = tmp_path / "legacy_abcd1234"
    _plan(ws, 3)
    for i in (1, 2, 3):
        _mk(ws, f"scripts/ep_{i}_script.md")
        _mk(ws, f"scripts/ep_{i}_pro.mp3", "AA")
    s = server._workspace_summary(ws, None)
    assert s["status"] != "awaiting"
    assert _g(s["gates"], "plan") == "passed"
    assert _g(s["gates"], "script") == "passed"


def test_summary_running_beats_awaiting(tmp_path):
    ws = tmp_path / "runaw_abcd1234"
    _plan(ws, 8)
    s = server._workspace_summary(ws, {"job_id": "j1", "label": "x", "kind": "pipeline"})
    assert s["status"] == "running"


# ─── approve endpoint guards(spawn 前就攔截,不啟動子行程)───
def test_approve_rejects_unknown_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "appro_abcd1234"
    _plan(ws, 3)
    with pytest.raises(server.HTTPException) as e:
        server.approve_gate("appro_abcd1234", gate="bogus")
    assert e.value.status_code == 400


def test_approve_rejects_pending_gate(tmp_path, monkeypatch):
    """無計畫(gate plan = pending)時核准 plan → 409,不可核准不存在的工作。"""
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "appro2_abcd1234"
    ws.mkdir()
    with pytest.raises(server.HTTPException) as e:
        server.approve_gate("appro2_abcd1234", gate="plan")
    assert e.value.status_code == 409


# ─── per-ws 併發守衛:同一 workspace 不可同時兩個 pipeline.py ───
class _FakeJob:
    def __init__(self, jid, ws=None, status="running", kind="pipeline", label="x"):
        self.id = jid
        self.label = label
        self.kind = kind
        self.status = status
        self.metadata = {"workspace": ws} if ws else {}


def test_active_job_via_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    (tmp_path / "w_abcd1234").mkdir()
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [_FakeJob("j1", ws="w_abcd1234")])
    j = server._active_job_for_ws("w_abcd1234")
    assert j and j["job_id"] == "j1"


def test_active_job_via_sidecar(tmp_path, monkeypatch):
    """route 2:job metadata 無 workspace,靠 <ws>/.pipeline_job_id 配對。"""
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "w2_abcd1234"
    ws.mkdir()
    (ws / ".pipeline_job_id").write_text("jS\n")
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [_FakeJob("jS")])
    j = server._active_job_for_ws("w2_abcd1234")
    assert j and j["job_id"] == "jS"


def test_active_job_none(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    (tmp_path / "w3_abcd1234").mkdir()
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [])
    assert server._active_job_for_ws("w3_abcd1234") is None


def test_approve_rejected_when_job_running(tmp_path, monkeypatch):
    """已有 running job 的 ws 再次 approve → 409,且不 spawn、不寫 gate 標記。"""
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "busy_abcd1234"
    _plan(ws, 3)
    for i in (1, 2, 3):
        _mk(ws, f"scripts/ep_{i}_script.md")  # scripts 完成 → gate script awaiting(過 readiness)
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [_FakeJob("jR", ws="busy_abcd1234")])

    def _no_spawn(*a, **k):
        raise AssertionError("must not spawn while a job is running for this ws")
    monkeypatch.setattr(server.jobs, "spawn", _no_spawn)

    with pytest.raises(server.HTTPException) as e:
        server.approve_gate("busy_abcd1234", gate="script")
    assert e.value.status_code == 409
    assert not (ws / ".script_approved").exists()  # 守衛在寫標記之前


def test_resume_rejected_when_job_running(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "busy2_abcd1234"
    _plan(ws, 3)
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [_FakeJob("jR", ws="busy2_abcd1234")])
    monkeypatch.setattr(server.jobs, "spawn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no spawn")))
    with pytest.raises(server.HTTPException) as e:
        server.resume_workspace("busy2_abcd1234")
    assert e.value.status_code == 409


def test_rerun_rejected_when_job_running(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "busy3_abcd1234"
    _plan(ws, 3)
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [_FakeJob("jR", ws="busy3_abcd1234")])
    monkeypatch.setattr(server.jobs, "spawn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no spawn")))
    with pytest.raises(server.HTTPException) as e:
        server.rerun_stage("busy3_abcd1234", stage="synthesize", episode=1, drop_marker=False)
    assert e.value.status_code == 409


def test_upload_rejected_when_job_running(tmp_path, monkeypatch):
    """upload 也要守:rsync 與 pipeline 同時跑會競寫 scripts/。"""
    monkeypatch.setattr(server, "WORKSPACES_DIR", tmp_path)
    ws = tmp_path / "busy4_abcd1234"
    _plan(ws, 3)
    _mk(ws, "scripts/ep_1_pro.mp3", "AA")  # 過 upload 的 422 守衛
    monkeypatch.setattr(server.jobs, "list", lambda limit=200: [_FakeJob("jR", ws="busy4_abcd1234")])
    monkeypatch.setattr(server.jobs, "spawn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no spawn")))
    with pytest.raises(server.HTTPException) as e:
        server.upload_workspace("busy4_abcd1234")
    assert e.value.status_code == 409
