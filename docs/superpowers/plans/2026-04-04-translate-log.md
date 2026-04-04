# Translate Log Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 新增 translate_log 模組，記錄翻譯 LLM 調用並���供跨用戶 cache retrieve。
**Architecture:** 新建 translate_log.py（SQLite singleton），修改 translate_service.py 在 LLM 調用前後加入 lookup/record。
**Tech Stack:** SQLite WAL, hashlib SHA256, time.monotonic

---

### Task 1: translate_log 模組

**Files:**
- Create: `backend/src/kg/translate_log.py`
- Test: `backend/tests/test_translate_log.py`

- [ ] **Step 1: 寫 failing test — record + lookup + get_log**
```python
import pytest
from kg.translate_log import record, lookup, get_log, _reset

@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    _reset()
    yield
    _reset()

def test_record_and_lookup():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="The story evokes memories.", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起","p":"v.","r":"evoke"}', latency_ms=150,
    )
    hit = lookup("evoke", "abc123", "en", "zh-Hant", "translate_quick")
    assert hit == '{"t":"喚起","p":"v.","r":"evoke"}'

def test_lookup_miss():
    assert lookup("evoke", "abc123", "en", "zh-Hant", "translate_quick") is None

def test_cross_user_cache():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="ctx", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起"}', latency_ms=100,
    )
    # Different user, same cache key → hit
    hit = lookup("evoke", "abc123", "en", "zh-Hant", "translate_quick")
    assert hit == '{"t":"喚起"}'

def test_different_context_no_hit():
    record(
        user_id="u1", operation="translate_quick", word="bank",
        context="river bank", context_hash="river_hash",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"河岸"}', latency_ms=100,
    )
    assert lookup("bank", "finance_hash", "en", "zh-Hant", "translate_quick") is None

def test_different_operation_no_hit():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="ctx", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起"}', latency_ms=100,
    )
    # Same word+context but different operation → no hit
    assert lookup("evoke", "abc123", "en", "zh-Hant", "translate_explain") is None

def test_get_log():
    record(
        user_id="u1", operation="translate_quick", word="evoke",
        context="ctx", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起"}', latency_ms=100,
    )
    record(
        user_id="u2", operation="translate_explain", word="bank",
        context="river", context_hash="def456",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"e":"解釋"}', latency_ms=200,
    )
    logs = get_log("u1")
    assert len(logs) == 1
    assert logs[0]["word"] == "evoke"
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd projects/kg && python -m pytest backend/tests/test_translate_log.py -v`
Expected: ImportError (module doesn't exist)

- [ ] **Step 3: 寫 translate_log.py**

遵循 judge_log.py pattern，但 **DB_PATH 改為 lazy 計算**（在 `_get_conn()` 內讀 env，而非模組層級常數），確保測試 `monkeypatch.setenv("KG_DATA_DIR", ...)` 生效：

```python
"""Translate/explain LLM call log + cross-user cache (SQLite singleton)."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

def _db_path() -> Path:
    data_dir = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
    return data_dir / "translate_log.db"

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db = _db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(db), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA synchronous=NORMAL;")
        _conn.execute("PRAGMA busy_timeout=30000;")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS translate_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                operation   TEXT NOT NULL,
                word        TEXT NOT NULL,
                context     TEXT,
                context_hash TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                response_raw TEXT NOT NULL,
                latency_ms  INTEGER,
                created_at  TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_tl_cache ON translate_log(word, context_hash, source_lang, target_lang, operation)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_tl_user ON translate_log(user_id, created_at)")
        _conn.commit()
    return _conn

def _reset() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None

def lookup(word: str, context_hash: str, source_lang: str, target_lang: str, operation: str) -> str | None:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT response_raw FROM translate_log WHERE word=? AND context_hash=? AND source_lang=? AND target_lang=? AND operation=? LIMIT 1",
            (word, context_hash, source_lang, target_lang, operation),
        ).fetchone()
    return row[0] if row else None

def record(*, user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms) -> None:
    if not user_id:
        return
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO translate_log (user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, int(latency_ms or 0), now),
        )
        conn.commit()

def get_log(user_id: str, *, limit: int = 200) -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM translate_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    cols = ["id","user_id","operation","word","context","context_hash","source_lang","target_lang","response_raw","latency_ms","created_at"]
    return [dict(zip(cols, row)) for row in rows]
```

- [ ] **Step 4: ��� test 確認通過**

- [ ] **Step 5: Commit**
`api: add translate_log module — structured LLM call logging + cache`

---

### Task 2: 接入 translate_service

**Files:**
- Modify: `backend/src/kg/translate_service.py:110-133` (`_run_llm_translate`)
- Test: `backend/tests/test_translate_service.py`

- [ ] **Step 1: 寫 failing test — cache hit 跳過 LLM**
```python
import hashlib

def _compute_context_hash(context: str) -> str:
    return hashlib.sha256((context or "").encode()).hexdigest()[:16]

@pytest.mark.asyncio
async def test_cache_hit_skips_llm(tmp_path, monkeypatch):
    """When translate_log has a cached result, LLM should not be called."""
    import kg.translate_log as tl
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    tl._reset()

    from kg.translate_service import _context_around_word
    ctx = _context_around_word("The story evokes memories.", "evoke")
    ctx_hash = _compute_context_hash(ctx)

    tl.record(
        user_id="u_other", operation="translate_quick", word="evoke",
        context=ctx, context_hash=ctx_hash,
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"喚起","p":"v.","r":"evoke"}', latency_ms=100,
    )

    client = _fake_async_client('{"t":"SHOULD NOT BE CALLED"}')
    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    result = await run_quick_translate(
        req, {"id": "u_test"},
        llm=TrackedLLM(client, "u_test"),
        logger=SimpleNamespace(error=lambda *a, **kw: None),
    )
    assert result.t == "喚起"  # from cache, not LLM
    client.chat.completions.create.assert_not_called()

    tl._reset()

@pytest.mark.asyncio
async def test_cache_miss_calls_llm_and_records(tmp_path, monkeypatch):
    """On cache miss, LLM is called and result is recorded to translate_log."""
    import kg.translate_log as tl
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    tl._reset()

    client = _fake_async_client('{"t":"喚起","p":"v.","r":"evoke"}')
    req = TranslateRequest(word="evoke", context="The story evokes memories.")
    result = await run_quick_translate(
        req, {"id": "u_test"},
        llm=TrackedLLM(client, "u_test"),
        logger=SimpleNamespace(error=lambda *a, **kw: None),
    )
    assert result.t == "喚起"
    client.chat.completions.create.assert_called_once()

    # Verify recorded
    logs = tl.get_log("u_test")
    assert len(logs) == 1
    assert logs[0]["word"] == "evoke"
    assert logs[0]["operation"] == "translate_quick"

    tl._reset()
```

- [ ] **Step 2: 跑 test 確認失敗**
Expected: FAIL (cache logic not yet wired)

- [ ] **Step 3: 修��� _run_llm_translate**

在 `translate_service.py` 中：

```python
# 新增 imports（檔案頂部）
import hashlib
import time
from . import translate_log

# 新增 helper
def _compute_context_hash(context: str) -> str:
    return hashlib.sha256((context or "").encode()).hexdigest()[:16]

# 修改 _run_llm_translate（替換 L110-133）
async def _run_llm_translate(*, req, user, llm, model, prompt_fn, operation, logger=None):
    source_lang, target_lang = resolve_translation_langs(req, user)
    ctx = _context_around_word(req.context, req.word)
    word_key = req.word.strip().lower()
    ctx_hash = _compute_context_hash(ctx)

    # Cache lookup
    cached = translate_log.lookup(word_key, ctx_hash, source_lang, target_lang, operation)
    if cached is not None:
        return _parse_json_payload(cached)

    # LLM call with latency tracking
    t0 = time.monotonic()
    response = await llm.chat_async(
        operation, model=model,
        messages=[{"role": "user", "content": prompt_fn(req, source_lang, target_lang)}],
        temperature=0.3, response_format={"type": "json_object"},
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    if not response.choices:
        if logger:
            logger.error("%s: Gemini returned empty choices.", operation)
        raise ExternalServiceError("Gemini returned empty response")

    raw = response.choices[0].message.content
    translate_log.record(
        user_id=llm.user_id, operation=operation,
        word=word_key, context=ctx, context_hash=ctx_hash,
        source_lang=source_lang, target_lang=target_lang,
        response_raw=raw or "", latency_ms=latency_ms,
    )
    return _parse_json_payload(raw)
```

注意：`word_key = req.word.strip().lower()` 用於 cache key + record，確保大小寫不敏感。`ctx` 用 `_context_around_word` 截斷後的結果做 hash，與 prompt_fn 內部截斷一致（冪等）。

- [ ] **Step 4: 跑 test 確認通過**
Run: `cd projects/kg && python -m pytest backend/tests/test_translate_service.py -v`

- [ ] **Step 5: Commit**
`api: wire translate_log cache into translate service`

---

### Task 3: 全量測試 + 既有測試不破

**Files:**
- All test files

- [ ] **Step 1: 跑全部測試**
Run: `cd projects/kg && python -m pytest backend/tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: 修正任何 regression**

- [ ] **Step 3: Commit（如有修正）**
