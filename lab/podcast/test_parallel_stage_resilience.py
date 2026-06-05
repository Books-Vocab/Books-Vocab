#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""平行 stage(scriptwrite / script-review)的韌性 + 失敗可觀測性。

兩個 CONFIRMED 缺陷的回歸測試:

A. ProcessPool worker 子程序 OOM/SIGKILL/segfault → worker 來不及 return,
   `future.result()` 拋 BrokenProcessPool 穿出 `with ProcessPoolExecutor`,
   已完成 sibling 的結果全丟、stage 非 graceful 炸掉。
   修法:future.result() 包 try/except,把該 episode 標記失敗、保住其他結果、
   stage graceful 收尾回報哪些失敗。

B. worker 子程序傳 log=None → 子程序內 `if log:` 全跳過 → 失敗不落
   pipeline_log.jsonl(dashboard grep '"error"' 依賴源)。
   修法:worker 子程序內各自建 PipelineLog(workspace)(append-safe)傳入,
   讓平行 stage 失敗也落 pipeline_log.jsonl。

跑法:
    uv run --with pytest --with ebooklib --with beautifulsoup4 \
        pytest lab/podcast/test_parallel_stage_resilience.py -v
"""

import json


import pipeline


# ─── helpers ─────────────────────────────────────────────────────────────


class _Log:
    """最小 PipelineLog stub —— 記下 error/event 呼叫供斷言。"""

    def __init__(self):
        self.errors: list[str] = []
        self.events: list[str] = []

    def event(self, msg, *a, **k):
        self.events.append(msg)

    def error(self, msg, *a, **k):
        self.errors.append(msg)


class _FakeFuture:
    """模擬 concurrent.futures.Future:result() 可正常回傳或拋例外。"""

    def __init__(self, result=None, exc: BaseException | None = None):
        self._result = result
        self._exc = exc

    def result(self, timeout=None):
        if self._exc is not None:
            raise self._exc
        return self._result


def _make_episode_plans(workspace, ep_nums):
    (workspace / "plan" / "episodes").mkdir(parents=True, exist_ok=True)
    (workspace / "scripts").mkdir(parents=True, exist_ok=True)
    for n in ep_nums:
        (workspace / "plan" / "episodes" / f"ep_{n:02d}.md").write_text(f"# ep {n}\n")


def _make_scripts(workspace, ep_nums):
    (workspace / "scripts").mkdir(parents=True, exist_ok=True)
    for n in ep_nums:
        (workspace / "scripts" / f"ep_{n}_script.md").write_text(
            f"Speaker1: hello ep {n}\nEND_OF_SCRIPT\n"
        )


def _patch_pool(monkeypatch, results_by_ep, crash_eps):
    """把 ProcessPoolExecutor + as_completed 換成同步 fake。

    results_by_ep: {ep_num: bool} —— worker 正常回傳的 (ep, success)。
    crash_eps: set[ep_num] —— 這些 episode 的 future.result() 拋 BrokenProcessPool
                              (模擬子程序 OOM/SIGKILL)。
    """
    from concurrent.futures.process import BrokenProcessPool

    submitted: dict[object, int] = {}

    class _FakePool:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, workspace, n):
            if n in crash_eps:
                fut = _FakeFuture(exc=BrokenProcessPool("A process terminated abruptly"))
            else:
                fut = _FakeFuture(result=(n, results_by_ep[n]))
            submitted[fut] = n
            return fut

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", _FakePool)
    # as_completed 同步回傳所有 submit 過的 future
    monkeypatch.setattr(pipeline, "as_completed", lambda futs: list(futs))
    return submitted


# ─── A. ProcessPool 子程序 crash 不丟整 stage ────────────────────────────


def test_scriptwriters_broken_pool_does_not_lose_siblings(tmp_path, monkeypatch):
    """一個 worker future 拋 BrokenProcessPool:
    - 其他 episode 的成功結果仍保留(stage 不整個炸)
    - crash 的 episode 被標記失敗
    - stage graceful 回 False 並 log 哪些失敗(而非穿出例外)
    """
    ws = tmp_path / "ws"
    _make_episode_plans(ws, [1, 2, 3])
    # ep1/ep3 worker 正常成功;ep2 子程序 crash(BrokenProcessPool)
    _patch_pool(monkeypatch, results_by_ep={1: True, 3: True}, crash_eps={2})

    log = _Log()
    # 不可拋例外 —— 必須 graceful
    ok = pipeline.stage_scriptwriters(ws, log, max_parallel=3)

    assert ok is False, "有 episode 失敗時 stage 應回 False"
    # crash 的 ep2 被當失敗回報
    assert any("2" in e for e in log.errors), f"應 log ep2 失敗,實際 errors={log.errors}"
    # 注意:ep1/ep3 成功 → 不應出現在 failed 列表(sibling 結果保住)
    failed_log = " ".join(log.errors)
    assert "1" not in failed_log.replace("EP", "").replace("ep", "") or "Failed episodes: [2]" in failed_log


def test_scriptwriters_all_crash_graceful(tmp_path, monkeypatch):
    """全部 worker crash 也不可穿出例外 —— graceful 回 False。"""
    ws = tmp_path / "ws"
    _make_episode_plans(ws, [1, 2])
    _patch_pool(monkeypatch, results_by_ep={}, crash_eps={1, 2})

    log = _Log()
    ok = pipeline.stage_scriptwriters(ws, log, max_parallel=2)
    assert ok is False
    assert log.errors, "全 crash 應 log error"


def test_script_review_broken_pool_does_not_lose_siblings(tmp_path, monkeypatch):
    """script-review stage 同樣:一個 worker crash 不丟其他結果、graceful 收尾。"""
    ws = tmp_path / "ws"
    _make_scripts(ws, [1, 2, 3])
    _patch_pool(monkeypatch, results_by_ep={1: True, 3: True}, crash_eps={2})

    log = _Log()
    ok = pipeline.stage_script_review(ws, log, max_parallel=3)

    assert ok is False, "有 episode 失敗時應回 False(不穿出例外)"
    assert any("2" in e for e in log.errors), f"應 log ep2 失敗,實際 errors={log.errors}"


def test_scriptwriters_generic_exception_also_caught(tmp_path, monkeypatch):
    """非 BrokenProcessPool 的一般 Exception 也要被捕(graceful),不穿出。"""
    ws = tmp_path / "ws"
    _make_episode_plans(ws, [1, 2])

    submitted: dict[object, int] = {}

    class _FakePool:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, workspace, n):
            if n == 2:
                fut = _FakeFuture(exc=RuntimeError("unexpected worker death"))
            else:
                fut = _FakeFuture(result=(n, True))
            submitted[fut] = n
            return fut

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", _FakePool)
    monkeypatch.setattr(pipeline, "as_completed", lambda futs: list(futs))

    log = _Log()
    ok = pipeline.stage_scriptwriters(ws, log, max_parallel=2)
    assert ok is False
    assert any("2" in e for e in log.errors)


# ─── B. worker 子程序失敗落 pipeline_log.jsonl ───────────────────────────


def test_worker_builds_pipeline_log_so_failures_are_logged(tmp_path, monkeypatch):
    """worker 失敗時應落 pipeline_log.jsonl 的 error 記錄。

    根因:worker 傳 log=None → _run_claude_subprocess 內 `if log:` 全跳過 →
    失敗細節不進 pipeline_log.jsonl。修法:worker 自建 PipelineLog(workspace)。

    驗證:讓 _run_claude_with_retry 把收到的 log 拿來呼叫 .error,
    然後檢查 pipeline_log.jsonl 真的多了 error 行。
    """
    ws = tmp_path / "ws"
    ws.mkdir()

    captured_logs = []

    def fake_retry(cmd, workspace, label, log, timeout, prompt=None):
        # worker 不該再傳 None —— 應傳一個會落 pipeline_log.jsonl 的 PipelineLog
        captured_logs.append(log)
        assert log is not None, "worker 不應再傳 log=None"
        log.error(f"{label} failed (simulated)", reason="boom")
        return False, 1.0

    monkeypatch.setattr(pipeline, "_run_claude_with_retry", fake_retry)

    ep_num, success = pipeline.run_scriptwriter(ws, 1)
    assert success is False
    assert ep_num == 1

    # worker 收到的必須是真的 PipelineLog(會寫 pipeline_log.jsonl)
    assert isinstance(captured_logs[0], pipeline.PipelineLog)

    log_path = ws / "pipeline_log.jsonl"
    assert log_path.exists(), "worker 失敗應產生 pipeline_log.jsonl"
    lines = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    errs = [e for e in lines if e.get("event") == "error"]
    assert errs, f"pipeline_log.jsonl 應有 error 記錄,實際={lines}"
    assert "1" in errs[0]["msg"] or "EP1" in errs[0]["msg"]


def test_script_reviewer_builds_pipeline_log(tmp_path, monkeypatch):
    """script reviewer worker 同樣自建 PipelineLog,失敗落 pipeline_log.jsonl。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    def fake_retry(cmd, workspace, label, log, timeout, prompt=None):
        assert log is not None, "worker 不應再傳 log=None"
        assert isinstance(log, pipeline.PipelineLog)
        log.error(f"{label} failed (simulated)")
        return False, 1.0

    monkeypatch.setattr(pipeline, "_run_claude_with_retry", fake_retry)

    ep_num, success = pipeline.run_script_reviewer(ws, 2)
    assert success is False

    log_path = ws / "pipeline_log.jsonl"
    assert log_path.exists()
    lines = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert any(e.get("event") == "error" for e in lines)


def test_pipeline_log_append_is_isolated_per_instance(tmp_path):
    """多程序 append 安全性的代理測試:多個獨立 PipelineLog(同 workspace)各自
    append 短行到同一 pipeline_log.jsonl,不互相覆蓋、每行都是完整 JSON。

    真實多程序用 O_APPEND(open("a"))保證每次 write 原子 append 到 EOF;
    此測試在單程序內以多 instance 模擬「無共享 offset、各自 append」的語意,
    確認 PipelineLog 設計不持有跨 instance 共享狀態。
    """
    n = 50
    for i in range(n):
        # 每個 instance 模擬一個 worker 子程序各自建 log
        log = pipeline.PipelineLog(tmp_path)
        log.error(f"worker {i} failed")

    log_path = tmp_path / "pipeline_log.jsonl"
    lines = [l for l in log_path.read_text().splitlines() if l.strip()]
    assert len(lines) == n, f"應有 {n} 行,實際 {len(lines)}(行被覆蓋/吞掉)"
    # 每行都是完整可解析 JSON(無 interleave 撕裂)
    msgs = {json.loads(l)["msg"] for l in lines}
    assert msgs == {f"worker {i} failed" for i in range(n)}
