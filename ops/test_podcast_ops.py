"""TDD for ops/podcast_ops.py — the headless podcast observability CLI.

Pure-disk subcommands (status / episodes / cost) are exercised against a
synthetic workspaces tree built in a tmp dir, so the suite needs no S3, no
boto3, no FastAPI — only stdlib + pytest. S3 subcommands (reconcile / series /
covers) are covered only for their graceful-degradation path (PODCAST_BUCKET
unset must error cleanly, never traceback).

Run:
    cd <repo root> && uv run --no-project --with pytest pytest ops/test_podcast_ops.py -v
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import podcast_ops as po  # noqa: E402


# ─── Fixtures: synthetic workspaces tree ─────────────────────────────────────

def _mk_ws(root: Path, name: str) -> Path:
    ws = root / name
    (ws / "scripts").mkdir(parents=True)
    (ws / "plan" / "episodes").mkdir(parents=True)
    return ws


def _ep_plan(ws: Path, n: int) -> None:
    (ws / "plan" / "episodes" / f"ep_{n}.md").write_text("plan\n")


def _ep_script(ws: Path, n: int) -> None:
    (ws / "scripts" / f"ep_{n}_script.md").write_text("script\n")


def _ep_audio(ws: Path, n: int, variant: str = "pro", nbytes: int = 1234) -> None:
    (ws / "scripts" / f"ep_{n}_{variant}.mp3").write_bytes(b"x" * nbytes)


def _ep_srt(ws: Path, n: int, variant: str = "pro") -> None:
    (ws / "scripts" / f"ep_{n}_{variant}.srt").write_text("1\n00:00\n")


def _overview(ws: Path) -> None:
    (ws / "plan" / "overview.md").write_text("# overview\n")


def _done_marker(ws: Path, stage: str) -> None:
    (ws / f".stage_{stage}_done").write_text("")


def _failed_log(ws: Path, stage: str) -> None:
    """A pipeline_log.jsonl whose latest stage_end for `stage` is success=false
    and no done-marker exists → status should resolve to 'failed'."""
    (ws / "pipeline_log.jsonl").write_text(
        json.dumps({"event": "stage_start", "stage": stage}) + "\n"
        + json.dumps({"event": "stage_end", "stage": stage, "success": False}) + "\n"
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A workspaces dir with four workspaces spanning the status cascade:
      - done_ws:    fully published (publish marker) → 'done'
      - failed_ws:  unresolved stage failure → 'failed'
      - awaiting_ws: plan complete, no scripts, not approved → 'awaiting'
      - fresh_ws:   empty → 'fresh'
    """
    root = tmp_path / "workspaces"
    root.mkdir()

    done = _mk_ws(root, "done_ws")
    _overview(done); _ep_plan(done, 1); _ep_script(done, 1)
    _ep_audio(done, 1); _ep_srt(done, 1); _done_marker(done, "publish")

    failed = _mk_ws(root, "failed_ws")
    _overview(failed); _ep_plan(failed, 1); _ep_script(failed, 1)
    _ep_audio(failed, 1); _failed_log(failed, "synthesize")

    awaiting = _mk_ws(root, "awaiting_ws")
    _overview(awaiting); _ep_plan(awaiting, 1)  # plan done, no script, no approval

    _mk_ws(root, "fresh_ws")  # nothing

    return root


# ─── status ──────────────────────────────────────────────────────────────────

def test_status_classifies_all_four(tree: Path):
    out = po.collect_status(tree)
    by_name = {w["name"]: w for w in out["workspaces"]}
    assert by_name["done_ws"]["status"] == "done"
    assert by_name["failed_ws"]["status"] == "failed"
    assert by_name["awaiting_ws"]["status"] == "awaiting"
    assert by_name["fresh_ws"]["status"] == "fresh"


def test_status_episode_count_and_progress(tree: Path):
    by_name = {w["name"]: w for w in po.collect_status(tree)["workspaces"]}
    assert by_name["done_ws"]["episode_count"] == 1
    assert by_name["fresh_ws"]["episode_count"] == 0
    # done_ws has all four gates for its single episode → progress == 1.0
    assert by_name["done_ws"]["progress"] == 1.0


def test_status_summary_counts(tree: Path):
    out = po.collect_status(tree)
    assert out["summary"]["total"] == 4
    assert out["summary"]["by_status"]["failed"] == 1
    assert out["summary"]["by_status"]["awaiting"] == 1


def test_status_failed_surfaces_reason(tree: Path):
    """v2: a failed workspace must say WHICH stage failed — the dogfood top
    complaint was 'failed but episodes all green, no clue why'."""
    by_name = {w["name"]: w for w in po.collect_status(tree)["workspaces"]}
    failed = by_name["failed_ws"]
    assert failed.get("failed_stage") == "synthesize"
    assert "synthesize" in failed.get("reason", "")
    # Non-failed rows carry no spurious reason.
    assert "reason" not in by_name["done_ws"]


def test_unresolved_failed_stage_ignores_resolved(tmp_path: Path):
    """A stage that failed then got its done-marker (rerun) is NOT the reason;
    the later unresolved failure is."""
    root = tmp_path / "workspaces"; root.mkdir()
    ws = _mk_ws(root, "mixed")
    (ws / "pipeline_log.jsonl").write_text(
        json.dumps({"event": "stage_end", "stage": "series-polish", "success": False}) + "\n"
        + json.dumps({"event": "stage_end", "stage": "publish", "success": False}) + "\n"
    )
    (ws / ".stage_series-polish_done").write_text("")  # resolved
    by_name = {w["name"]: w for w in po.collect_status(root)["workspaces"]}
    assert by_name["mixed"]["failed_stage"] == "publish"


def test_status_missing_dir_is_empty_not_crash(tmp_path: Path):
    out = po.collect_status(tmp_path / "nonexistent")
    assert out["workspaces"] == []
    assert out["summary"]["total"] == 0


def test_status_dedupes_audio_variants(tmp_path: Path):
    """An episode with BOTH pro and flash audio counts once."""
    root = tmp_path / "workspaces"; root.mkdir()
    ws = _mk_ws(root, "dual")
    _ep_audio(ws, 1, "pro"); _ep_audio(ws, 1, "flash")
    by_name = {w["name"]: w for w in po.collect_status(root)["workspaces"]}
    assert by_name["dual"]["episode_count"] == 1


# ─── exit-code contract (cron signal: 2=failed, 1=awaiting, 0=ok) ────────────

def test_main_exit_2_on_failed(tree: Path):
    rc = po.main(["status", "--workspaces-dir", str(tree), "--json"])
    assert rc == 2  # tree has a failed_ws


def test_main_exit_1_on_awaiting_only(tmp_path: Path):
    root = tmp_path / "workspaces"; root.mkdir()
    ws = _mk_ws(root, "awaiting_ws"); _overview(ws); _ep_plan(ws, 1)
    rc = po.main(["status", "--workspaces-dir", str(root), "--json"])
    assert rc == 1


def test_main_exit_0_when_clean(tmp_path: Path):
    root = tmp_path / "workspaces"; root.mkdir()
    ws = _mk_ws(root, "done_ws")
    _overview(ws); _ep_plan(ws, 1); _ep_script(ws, 1)
    _ep_audio(ws, 1); _ep_srt(ws, 1); _done_marker(ws, "publish")
    rc = po.main(["status", "--workspaces-dir", str(root), "--json"])
    assert rc == 0


# ─── JSON contract: banner→stderr, pure JSON→stdout ──────────────────────────

def test_json_stdout_is_pure_parseable(tree: Path):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        po.main(["status", "--workspaces-dir", str(tree), "--json"])
    parsed = json.loads(buf_out.getvalue())  # must parse with zero preamble
    assert parsed["summary"]["total"] == 4


# ─── episodes ────────────────────────────────────────────────────────────────

def test_episodes_per_gate_matrix(tree: Path):
    out = po.collect_episodes(tree / "done_ws")
    assert out["workspace"] == "done_ws"
    ep1 = next(e for e in out["episodes"] if e["ep"] == 1)
    assert ep1["plan"] and ep1["script"] and ep1["audio"] and ep1["subtitle"]
    assert ep1["variant"] == "pro"


def test_episodes_partial(tmp_path: Path):
    root = tmp_path / "workspaces"; root.mkdir()
    ws = _mk_ws(root, "partial")
    _ep_plan(ws, 3); _ep_script(ws, 3)  # plan+script, no audio/subtitle
    ep3 = next(e for e in po.collect_episodes(ws)["episodes"] if e["ep"] == 3)
    assert ep3["plan"] and ep3["script"]
    assert not ep3["audio"] and not ep3["subtitle"]


# ─── cost (no events.jsonl → 0, never crash) ─────────────────────────────────

def test_cost_zero_without_events(tree: Path):
    out = po.collect_cost(tree)
    assert out["total_usd"] == 0.0
    assert isinstance(out["by_workspace"], list)
    # Every workspace should appear even at $0 so producers see the full roster.
    assert len(out["by_workspace"]) == 4


def test_cost_single_workspace(tree: Path):
    out = po.collect_cost(tree, workspace="done_ws")
    assert out["scope"] == "done_ws"


# ─── covers (v2: present is a list, symmetric with missing) ──────────────────

def _cover(ws: Path) -> None:
    (ws / "plan").mkdir(parents=True, exist_ok=True)
    (ws / "plan" / "cover.png").write_bytes(b"\x89PNG")


def test_covers_present_and_missing_are_lists(tmp_path: Path):
    root = tmp_path / "workspaces"; root.mkdir()
    has = _mk_ws(root, "has_cover"); _ep_audio(has, 1); _cover(has)
    no = _mk_ws(root, "no_cover"); _ep_audio(no, 1)  # audio, no cover.png
    _mk_ws(root, "no_audio")  # skipped — not publishable
    out = po.collect_covers(root)
    assert out["present"] == ["has_cover"]      # list, not int
    assert out["missing"] == [{"workspace": "no_cover", "reason": "no_cover_png"}]


# ─── --json error contract (v2: failures emit JSON to stdout, not bare stderr)

def test_json_error_is_structured_on_stdout(tree: Path, monkeypatch):
    monkeypatch.delenv("PODCAST_BUCKET", raising=False)
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        rc = po.main(["reconcile", "--workspaces-dir", str(tree), "--json"])
    assert rc == 3
    payload = json.loads(buf_out.getvalue())  # stdout must be parseable JSON
    assert payload["ok"] is False
    assert payload["error"]


def test_text_error_still_goes_to_stderr(tree: Path, monkeypatch):
    """Non-JSON mode keeps the human error on stderr (unchanged)."""
    monkeypatch.delenv("PODCAST_BUCKET", raising=False)
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        rc = po.main(["reconcile", "--workspaces-dir", str(tree)])
    assert rc == 3
    assert buf_out.getvalue() == ""
    assert "reconcile" in buf_err.getvalue()


# ─── S3 subcommands: graceful degradation when PODCAST_BUCKET unset ──────────

def test_reconcile_without_bucket_errors_cleanly(tree: Path, monkeypatch):
    monkeypatch.delenv("PODCAST_BUCKET", raising=False)
    rc = po.main(["reconcile", "--workspaces-dir", str(tree), "--json"])
    assert rc != 0  # clean non-zero, not a traceback (pytest would catch raise)
