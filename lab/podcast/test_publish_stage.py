#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""Closed-loop publish stage: a finished pipeline must auto-upload to S3 and
verify the series is live in the catalog index — no manual dashboard step.

根因:Track-B 後 podcast 走 S3-only,但 pipeline 跑完 subtitle 後不自動上傳
(上傳是 monitor dashboard 手動動作),既有 series 從未遷移 → bucket 空 →
/api/podcasts 回 []。本測試鎖定終端 `publish` stage 的契約:

  1. publish 是 STAGES 最後一段(緊接 subtitle),且 argparse choices 自動接受。
  2. publish 不在 _APPROVAL_GATES(使用者要全自動,合成完成即上傳)。
  3. upload rc=0 + verify 命中 → stage_publish 回 True。
  4. upload rc=0 但 verify 找不到 series → 重試耗盡回 False(不誤報成功)。
  5. verify 先失敗後成功 → 重試後回 True。
  6. PODCAST_BUCKET 未設 → loud-fail 回 False(非 crash)。
"""


import pipeline


class _FakeLog:
    def __init__(self):
        self.msgs = []

    def error(self, m):
        self.msgs.append(("error", m))

    def event(self, m):
        self.msgs.append(("event", m))


# --- stage ordering / gate contract ----------------------------------------

def test_publish_is_last_stage_after_subtitle():
    assert pipeline.STAGES[-1] == "publish"
    assert pipeline.STAGES.index("cover") == pipeline.STAGES.index("subtitle") + 1
    assert pipeline.STAGES.index("publish") == pipeline.STAGES.index("cover") + 1


def test_publish_not_gated():
    assert "publish" not in pipeline._APPROVAL_GATES


def test_stage_publish_callable():
    assert callable(pipeline.stage_publish)


# --- stage_publish behaviour ------------------------------------------------

def _patch_upload(monkeypatch, rc=0):
    class _Proc:
        returncode = rc

    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **k: _Proc())
    # upload_sh existence + bucket env
    monkeypatch.setattr(pipeline.Path, "is_file", lambda self: True)
    monkeypatch.setenv("PODCAST_BUCKET", "kg-podcasts-prod")
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)


def test_publish_succeeds_when_verify_hits(monkeypatch, tmp_path):
    ws = tmp_path / "flow_x"
    ws.mkdir()
    _patch_upload(monkeypatch, rc=0)
    monkeypatch.setattr(pipeline, "_verify_published", lambda sid: True)
    assert pipeline.stage_publish(ws, _FakeLog()) is True


def test_publish_fails_when_verify_never_hits(monkeypatch, tmp_path):
    ws = tmp_path / "flow_x"
    ws.mkdir()
    _patch_upload(monkeypatch, rc=0)
    monkeypatch.setattr(pipeline, "_verify_published", lambda sid: False)
    assert pipeline.stage_publish(ws, _FakeLog(), max_retries=2) is False


def test_publish_retries_then_succeeds(monkeypatch, tmp_path):
    ws = tmp_path / "flow_x"
    ws.mkdir()
    _patch_upload(monkeypatch, rc=0)
    calls = {"n": 0}

    def _verify(sid):
        calls["n"] += 1
        return calls["n"] >= 2  # first attempt misses, second hits

    monkeypatch.setattr(pipeline, "_verify_published", _verify)
    assert pipeline.stage_publish(ws, _FakeLog(), max_retries=3) is True
    assert calls["n"] == 2


def test_publish_loud_fails_without_bucket(monkeypatch, tmp_path):
    ws = tmp_path / "flow_x"
    ws.mkdir()
    monkeypatch.delenv("PODCAST_BUCKET", raising=False)
    log = _FakeLog()
    assert pipeline.stage_publish(ws, log) is False
    assert any(level == "error" for level, _ in log.msgs)


def test_publish_upload_failure_short_circuits_verify(monkeypatch, tmp_path):
    """upload rc != 0 must NOT call verify (short-circuit) and must retry."""
    ws = tmp_path / "flow_x"
    ws.mkdir()
    _patch_upload(monkeypatch, rc=1)
    verify_calls = {"n": 0}
    monkeypatch.setattr(pipeline, "_verify_published",
                        lambda sid: verify_calls.__setitem__("n", verify_calls["n"] + 1) or True)
    assert pipeline.stage_publish(ws, _FakeLog(), max_retries=2) is False
    assert verify_calls["n"] == 0  # never reached verify on rc!=0


def test_publish_loud_fails_when_upload_script_missing(monkeypatch, tmp_path):
    ws = tmp_path / "flow_x"
    ws.mkdir()
    monkeypatch.setenv("PODCAST_BUCKET", "kg-podcasts-prod")
    monkeypatch.setattr(pipeline.Path, "is_file", lambda self: False)
    log = _FakeLog()
    assert pipeline.stage_publish(ws, log) is False
    assert any("upload script missing" in m for level, m in log.msgs)


def test_publish_timeout_is_retried(monkeypatch, tmp_path):
    ws = tmp_path / "flow_x"
    ws.mkdir()
    monkeypatch.setenv("PODCAST_BUCKET", "kg-podcasts-prod")
    monkeypatch.setattr(pipeline.Path, "is_file", lambda self: True)
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)

    def _boom(*a, **k):
        raise pipeline.subprocess.TimeoutExpired(cmd="bash", timeout=1)

    monkeypatch.setattr(pipeline.subprocess, "run", _boom)
    monkeypatch.setattr(pipeline, "_verify_published", lambda sid: True)
    assert pipeline.stage_publish(ws, _FakeLog(), max_retries=2) is False


def test_verify_published_matches_series_in_index(monkeypatch):
    """_verify_published reads index.json from S3 and matches by id."""
    monkeypatch.setenv("PODCAST_BUCKET", "kg-podcasts-prod")
    import json as _json

    class _Body:
        def __init__(self, b): self._b = b
        def read(self): return self._b

    class _S3:
        def __init__(self, idx): self._idx = idx
        def get_object(self, Bucket, Key):
            return {"Body": _Body(_json.dumps(self._idx).encode())}

    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _S3([{"id": "flow_x"}, {"id": "other"}]))
    assert pipeline._verify_published("flow_x") is True
    assert pipeline._verify_published("missing") is False


def test_verify_published_false_when_index_unreadable(monkeypatch):
    monkeypatch.setenv("PODCAST_BUCKET", "kg-podcasts-prod")

    class _S3:
        def get_object(self, Bucket, Key):
            raise RuntimeError("NoSuchKey")

    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _S3())
    assert pipeline._verify_published("flow_x") is False
