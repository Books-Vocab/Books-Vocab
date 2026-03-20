# Backend Tech Debt Reduction Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Systematically reduce KG backend technical debt across 5 phases — from connection safety to architecture cleanup.

**Architecture:** Bottom-up approach: fix infrastructure (stores/locks) first, then extract constants/exceptions, then decompose modules, then add tests, and finally migrate GraphStore to SQLite.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy, SQLite, Pydantic, asyncio

---

## Phase 1: Store Connection Management + Lock Safety

### Task 1.1: Add `close()` to all Store classes

**Files:**
- Modify: `backend/src/kg/cards.py:57-62` (CardStore.__init__)
- Modify: `backend/src/kg/notebook.py:34-46` (NotebookStore.__init__)
- Modify: `backend/src/kg/daily_stats.py:28-39` (DailyReviewStatsStore.__init__)
- Test: `backend/tests/test_store_lifecycle.py` (create)

- [ ] **Step 1: Write failing test for CardStore.close()**

```python
# backend/tests/test_store_lifecycle.py
"""Tests for store lifecycle (open/close)."""
import pytest
from pathlib import Path
from kg.cards import CardStore


def test_card_store_close_disposes_engine(tmp_path: Path):
    store = CardStore(tmp_path / "cards.db")
    store.add("hello", "你好")
    store.close()
    assert store.engine is None


def test_card_store_double_close_is_safe(tmp_path: Path):
    store = CardStore(tmp_path / "cards.db")
    store.close()
    store.close()  # should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_store_lifecycle.py -v`
Expected: AttributeError — CardStore has no `close` method.

- [ ] **Step 3: Implement close() on CardStore**

Add to `backend/src/kg/cards.py` after the `save()` method (line 397):

```python
def close(self) -> None:
    """Dispose the SQLAlchemy engine and release connections."""
    if self.engine is not None:
        self.engine.dispose()
        self.engine = None
```

- [ ] **Step 4: Add close() to NotebookStore and DailyReviewStatsStore**

Same pattern in `backend/src/kg/notebook.py` (end of NotebookStore class) and `backend/src/kg/daily_stats.py` (end of DailyReviewStatsStore class):

```python
def close(self) -> None:
    """Dispose the SQLAlchemy engine and release connections."""
    if self.engine is not None:
        self.engine.dispose()
        self.engine = None
```

- [ ] **Step 5: Add tests for NotebookStore and DailyReviewStatsStore close**

Append to `backend/tests/test_store_lifecycle.py`:

```python
from kg.notebook import NotebookStore
from kg.daily_stats import DailyReviewStatsStore


def test_notebook_store_close(tmp_path: Path):
    store = NotebookStore(tmp_path / "notebooks.db")
    store.close()
    assert store.engine is None


def test_daily_stats_store_close(tmp_path: Path):
    store = DailyReviewStatsStore(tmp_path / "stats.db")
    store.close()
    assert store.engine is None
```

- [ ] **Step 6: Run all tests**

Run: `cd backend && python -m pytest tests/test_store_lifecycle.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/kg/cards.py backend/src/kg/notebook.py backend/src/kg/daily_stats.py backend/tests/test_store_lifecycle.py
git commit -m "api: add close() to Store classes for connection lifecycle management"
```

---

### Task 1.2: Fix Store Cache eviction to close disposed stores

**Files:**
- Modify: `backend/src/kg/service_factories.py:19-33`
- Test: `backend/tests/test_service_factories.py` (create)

- [ ] **Step 1: Write failing test for eviction cleanup**

```python
# backend/tests/test_service_factories.py
"""Tests for store cache eviction behavior."""
from pathlib import Path
from unittest.mock import MagicMock

from kg.service_factories import _get_cached, _STORE_CACHE, _STORE_CACHE_LOCK, clear_store_cache


def test_evicted_store_is_closed(tmp_path: Path):
    """When cache exceeds max, evicted store's close() should be called."""
    import kg.service_factories as sf
    old_max = sf._STORE_CACHE_MAX

    try:
        clear_store_cache()
        sf._STORE_CACHE_MAX = 2

        mock1 = MagicMock()
        mock2 = MagicMock()
        mock3 = MagicMock()

        _get_cached("a", lambda: mock1)
        _get_cached("b", lambda: mock2)
        _get_cached("c", lambda: mock3)  # should evict mock1

        mock1.close.assert_called_once()
        mock2.close.assert_not_called()
    finally:
        sf._STORE_CACHE_MAX = old_max
        clear_store_cache()


def test_clear_store_cache_closes_all():
    """clear_store_cache() should close all cached stores."""
    import kg.service_factories as sf
    clear_store_cache()

    mock1 = MagicMock()
    mock2 = MagicMock()
    _get_cached("x", lambda: mock1)
    _get_cached("y", lambda: mock2)

    clear_store_cache()
    mock1.close.assert_called_once()
    mock2.close.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_service_factories.py -v`
Expected: FAIL — close() never called on evicted stores.

- [ ] **Step 3: Implement eviction cleanup**

In `backend/src/kg/service_factories.py`, modify `_get_cached` and `clear_store_cache`:

```python
def _get_cached(key: str, factory):
    with _STORE_CACHE_LOCK:
        if key in _STORE_CACHE:
            _STORE_CACHE.move_to_end(key)
            return _STORE_CACHE[key]
        instance = factory()
        _STORE_CACHE[key] = instance
        while len(_STORE_CACHE) > _STORE_CACHE_MAX:
            _, evicted = _STORE_CACHE.popitem(last=False)
            _close_store(evicted)
        return instance


def _close_store(store: object) -> None:
    """Best-effort close for evicted stores."""
    close_fn = getattr(store, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            logger.debug("Failed to close evicted store %s", type(store).__name__, exc_info=True)


def clear_store_cache() -> None:
    with _STORE_CACHE_LOCK:
        for store in _STORE_CACHE.values():
            _close_store(store)
        _STORE_CACHE.clear()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_service_factories.py tests/test_store_lifecycle.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/service_factories.py backend/tests/test_service_factories.py
git commit -m "api: close evicted stores in cache to prevent connection leaks"
```

---

### Task 1.3: Fix asyncio.Lock lazy initialization race

**Files:**
- Modify: `backend/src/kg/deps.py:59-68`
- Test: `backend/tests/test_user_locks.py` (create)

- [ ] **Step 1: Write test for lock initialization safety**

```python
# backend/tests/test_user_locks.py
"""Tests for user lock management."""
import asyncio
import pytest
from kg.deps import get_user_lock, _USER_LOCKS


@pytest.fixture(autouse=True)
def _reset_locks():
    _USER_LOCKS.clear()
    yield
    _USER_LOCKS.clear()


@pytest.mark.asyncio
async def test_get_user_lock_returns_same_lock():
    lock1 = await get_user_lock("user_a")
    lock2 = await get_user_lock("user_a")
    assert lock1 is lock2


@pytest.mark.asyncio
async def test_concurrent_lock_creation():
    """Multiple concurrent calls for same user should get same lock."""
    results = await asyncio.gather(
        get_user_lock("user_b"),
        get_user_lock("user_b"),
        get_user_lock("user_b"),
    )
    assert results[0] is results[1] is results[2]
```

- [ ] **Step 2: Run test — may pass but validates behavior**

Run: `cd backend && python -m pytest tests/test_user_locks.py -v`

- [ ] **Step 3: Verify lazy init is already race-free**

The existing lazy pattern (`_get_locks_mutex()`) is actually safe in asyncio's single-threaded cooperative model: there's no `await` between the `None` check and assignment, so no coroutine can interleave. The real issue is that `_USER_LOCKS_MUTEX: asyncio.Lock | None = None` type annotation allows `None`, making callers awkward.

The simplest safe fix: keep lazy init but add a docstring clarifying why it's safe, and type-narrow the return:

In `backend/src/kg/deps.py`, update the docstring on `_get_locks_mutex`:

```python
def _get_locks_mutex() -> asyncio.Lock:
    """Lazy-init the mutex. Safe because asyncio is single-threaded:
    no await between the None check and assignment, so no interleaving."""
    global _USER_LOCKS_MUTEX
    if _USER_LOCKS_MUTEX is None:
        _USER_LOCKS_MUTEX = asyncio.Lock()
    return _USER_LOCKS_MUTEX
```

Do NOT move `asyncio.Lock()` to module level — Python 3.12 raises `RuntimeError` if no event loop is running.

- [ ] **Step 4: Run full test suite**

Run: `cd backend && python -m pytest tests/test_user_locks.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/deps.py backend/tests/test_user_locks.py
git commit -m "api: fix asyncio.Lock lazy init race in user lock management"
```

---

## Phase 2: Settings Constants Extraction + Unified Exceptions

### Task 2.1: Extract hardcoded constants to KGSettings

**Files:**
- Modify: `backend/src/kg/settings.py:11-32`
- Modify: `backend/src/kg/translate_service.py:104,125,143` (model name)
- Modify: `backend/src/kg/judge.py:44` (model name)
- Modify: `backend/src/kg/vocab_graph.py:11-12` (thresholds)
- Modify: `backend/src/kg/vocab_service.py:26-27` (batch limits) — check actual location
- Test: `backend/tests/test_settings.py` (create)

- [ ] **Step 1: Write test for new settings fields**

```python
# backend/tests/test_settings.py
"""Tests for KGSettings defaults."""
from kg.settings import KGSettings
from pathlib import Path


def test_settings_has_llm_defaults():
    s = KGSettings(data_dir=Path("/tmp"), jwt_secret="x" * 16)
    assert s.gemini_model == "gemini-2.5-flash-lite"
    assert s.gemini_temperature == 0.3
    assert s.judge_temperature == 0.1
    assert s.similarity_threshold == 0.70
    assert s.candidate_k == 20
    assert s.max_batch_size == 500
    assert s.max_word_length == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_settings.py -v`
Expected: FAIL — KGSettings has no `gemini_model` field.

- [ ] **Step 3: Add fields to KGSettings**

In `backend/src/kg/settings.py`, add after `free_daily_limit_usd` (line 25):

```python
    # LLM
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_temperature: float = 0.3
    judge_temperature: float = 0.1

    # Graph
    similarity_threshold: float = 0.70
    candidate_k: int = 20

    # Vocab
    max_batch_size: int = 500
    max_word_length: int = 200
```

- [ ] **Step 4: Run test**

Run: `cd backend && python -m pytest tests/test_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/settings.py backend/tests/test_settings.py
git commit -m "api: extract hardcoded LLM/graph/vocab constants to KGSettings"
```

**Note:** Wiring these settings through the call chain (translate_service, judge, vocab_graph, etc.) is a follow-up. The constants now have a canonical home; callers can be migrated incrementally without breaking changes. Each caller currently reads module-level constants, so migrating them is mechanical but touches many files — do it per-module in separate commits.

---

### Task 2.2: Create unified exception hierarchy

**Files:**
- Create: `backend/src/kg/exceptions.py`
- Test: `backend/tests/test_exceptions.py` (create)

- [ ] **Step 1: Write test for exception hierarchy**

```python
# backend/tests/test_exceptions.py
"""Tests for custom exception hierarchy."""
from kg.exceptions import (
    KGError,
    QuotaExceededError,
    ExternalServiceError,
    LLMParseError,
    NotFoundError,
)


def test_hierarchy():
    assert issubclass(QuotaExceededError, KGError)
    assert issubclass(ExternalServiceError, KGError)
    assert issubclass(LLMParseError, ExternalServiceError)
    assert issubclass(NotFoundError, KGError)


def test_quota_exceeded_has_reset():
    err = QuotaExceededError(reset_seconds=3600)
    assert err.reset_seconds == 3600
    assert err.status_code == 429


def test_not_found_has_entity():
    err = NotFoundError("User", "abc123")
    assert "User" in str(err)
    assert err.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_exceptions.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create exception module**

```python
# backend/src/kg/exceptions.py
"""Unified exception hierarchy for KG backend.

Service-layer code raises these; the FastAPI exception handler
in api.py converts them to HTTP responses.
"""
from __future__ import annotations


class KGError(Exception):
    """Base for all KG domain errors."""

    status_code: int = 500

    def to_detail(self) -> dict:
        return {"code": type(self).__name__, "detail": str(self)}


class NotFoundError(KGError):
    status_code = 404

    def __init__(self, entity: str, identifier: str | None = None):
        self.entity = entity
        self.identifier = identifier
        msg = f"{entity} not found" if not identifier else f"{entity} '{identifier}' not found"
        super().__init__(msg)


class QuotaExceededError(KGError):
    status_code = 429

    def __init__(self, reset_seconds: int):
        self.reset_seconds = reset_seconds
        super().__init__(f"Quota exceeded, resets in {reset_seconds}s")

    def to_detail(self) -> dict:
        return {"code": "quota_exhausted", "reset_seconds": self.reset_seconds}


class ExternalServiceError(KGError):
    """Wraps failures from Gemini, Mochi, App Store, etc."""
    status_code = 502


class LLMParseError(ExternalServiceError):
    """LLM returned unparseable output."""
    status_code = 502
```

- [ ] **Step 4: Run test**

Run: `cd backend && python -m pytest tests/test_exceptions.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/exceptions.py backend/tests/test_exceptions.py
git commit -m "api: add unified exception hierarchy (KGError, QuotaExceededError, etc.)"
```

**Note:** Migrating existing `HTTPException` raises to these custom exceptions is incremental work. Start with the most-used paths (quota checks in deps.py, 404s in admin_handlers.py) in follow-up commits.

---

## Phase 3: Decompose pipeline_service + deps.py

### Task 3.1: Extract pipeline step runner helper

The 4 `try/except _step_errors` blocks in `run_pipeline_background()` are near-identical. Extract a helper.

**Files:**
- Modify: `backend/src/kg/pipeline_service.py:268-337`
- Test: `backend/tests/test_pipeline_step_runner.py` (create)

- [ ] **Step 1: Write test for step runner**

```python
# backend/tests/test_pipeline_step_runner.py
"""Tests for pipeline step execution helper."""
import logging
import pytest
from kg.pipeline_service import _run_step


@pytest.mark.asyncio
async def test_run_step_success():
    called = []

    async def step():
        called.append(True)

    await _run_step("test_user", "TestStep", step, logger=logging.getLogger("test"))
    assert called == [True]


@pytest.mark.asyncio
async def test_run_step_catches_errors():
    async def failing_step():
        raise ValueError("boom")

    # Should not raise
    await _run_step("test_user", "FailStep", failing_step, logger=logging.getLogger("test"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline_step_runner.py -v`
Expected: FAIL — `_run_step` does not exist.

- [ ] **Step 3: Implement _run_step helper**

Add to `backend/src/kg/pipeline_service.py` before `run_pipeline_background`:

```python
_STEP_ERRORS = (OpenAIError, OSError, ValueError, RuntimeError)


async def _run_step(
    uid: str,
    name: str,
    coro_fn,
    *,
    logger: logging.Logger,
    retry: bool = False,
    retryable_exceptions: tuple = (OpenAIError, OSError),
) -> None:
    """Execute a pipeline step with uniform error handling."""
    try:
        if retry:
            await async_retry(
                coro_fn, max_attempts=2,
                retryable_exceptions=retryable_exceptions,
                step_name=name, uid=uid,
            )
        else:
            await coro_fn()
    except _STEP_ERRORS as exc:
        logger.error("[%s] %s failed: %s", uid, name, exc, exc_info=True)
```

- [ ] **Step 4: Refactor run_pipeline_background to use _run_step**

Replace the 5 try/except blocks inside `run_pipeline_background` with calls to `_run_step`. The `async_retry` wrapper variant uses `retry=True`:

```python
            await _run_step(uid, "Enrich", lambda: _step_enrich(
                uid, user, card_store_factory=card_store_factory,
                gemini_client_factory=gemini_client_factory, logger=logger,
                force=force_enrich, notebook_id=notebook_id,
            ), logger=logger, retry=True)

            await _run_step(uid, "Embed", lambda: _step_embed(
                uid, user, card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory,
                embedding_store_factory=embedding_store_factory,
                logger=logger, notebook_id=notebook_id,
            ), logger=logger, retry=True)

            await _run_step(uid, "Link", lambda: _step_link(
                uid, user, card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory,
                gemini_client_factory=gemini_client_factory, logger=logger,
                link_kind_enum=link_kind_enum, notebook_id=notebook_id,
            ), logger=logger, retry=True)

            await _run_step(uid, "Difficulty", lambda: _step_difficulty(
                uid, user, card_store_factory=card_store_factory,
                logger=logger, notebook_id=notebook_id,
            ), logger=logger)

            with _PIPELINE_RUNNING_LOCK:
                _PIPELINE_RUNNING[uid] = False
            logger.info("[%s] Core pipeline done, clients unblocked.", uid)

            await _run_step(uid, "ExternalSync", lambda: _step_external_sync(
                uid, user, card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory, logger=logger,
                jwt_secret=jwt_secret, notebook_id=notebook_id,
            ), logger=logger)
```

- [ ] **Step 5: Run pipeline tests**

Run: `cd backend && python -m pytest tests/test_pipeline_step_runner.py tests/test_pipeline_service.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/pipeline_service.py backend/tests/test_pipeline_step_runner.py
git commit -m "api: extract _run_step helper to eliminate pipeline error-handling duplication"
```

---

### Task 3.2: Split deps.py — extract quota helpers

`deps.py` has 269 lines mixing auth, factories, quota, and billing wrappers. Extract quota helpers.

**Files:**
- Create: `backend/src/kg/deps_quota.py`
- Modify: `backend/src/kg/deps.py:198-243`

- [ ] **Step 1: Create deps_quota.py with extracted code**

```python
# backend/src/kg/deps_quota.py
"""Quota check helpers extracted from deps.py."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException, Response


def _is_pro(user: dict) -> bool:
    from .billing import current_pro_entitlement_record
    return bool(current_pro_entitlement_record(user.get("record")).get("is_active"))


def _with_quota_check(
    user: dict, call_type: str, response: Response | None, handler: Callable[[], Any],
) -> Any:
    from .quota_service import check_and_get_quota
    pro = _is_pro(user)
    quota = check_and_get_quota(user["id"], call_type, is_pro=pro)
    if quota["exceeded"]:
        raise HTTPException(
            429,
            detail={"code": "quota_exhausted", "reset_seconds": quota["reset_seconds"]},
            headers={"X-Quota-Fraction": "0.0", "X-Quota-Reset": str(quota["reset_seconds"])},
        )
    result = handler()
    if response is not None:
        response.headers["X-Quota-Fraction"] = str(quota["fraction"])
        response.headers["X-Quota-Reset"] = str(quota["reset_seconds"])
    return result


def _check_quota(user: dict, call_type: str, response: Response | None) -> dict:
    from .quota_service import check_and_get_quota
    pro = _is_pro(user)
    quota = check_and_get_quota(user["id"], call_type, is_pro=pro)
    if quota["exceeded"]:
        raise HTTPException(
            429,
            detail={"code": "quota_exhausted", "reset_seconds": quota["reset_seconds"]},
            headers={"X-Quota-Fraction": "0.0", "X-Quota-Reset": str(quota["reset_seconds"])},
        )
    return quota


def _apply_quota_headers(response: Response | None, quota: dict) -> None:
    if response is not None:
        response.headers["X-Quota-Fraction"] = str(quota["fraction"])
        response.headers["X-Quota-Reset"] = str(quota["reset_seconds"])
```

- [ ] **Step 2: Update deps.py to re-export from deps_quota**

Replace the quota section in `deps.py` (lines 198-243) with:

```python
# ---------------------------------------------------------------------------
# Quota helpers (extracted to deps_quota.py)
# ---------------------------------------------------------------------------

from .deps_quota import _is_pro, _with_quota_check, _check_quota, _apply_quota_headers  # noqa: F401
```

- [ ] **Step 3: Run full test suite to verify no breakage**

Run: `cd backend && python -m pytest -x -q`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/kg/deps_quota.py backend/src/kg/deps.py
git commit -m "api: extract quota helpers from deps.py to deps_quota.py"
```

---

### Task 3.3: Deduplicate admin grant/revoke logic

**Files:**
- Modify: `backend/src/kg/admin_handlers.py:189-272`

- [ ] **Step 1: Extract shared admin grant mutation helper**

Add to `backend/src/kg/admin_handlers.py` before the grant/revoke functions:

```python
def _mutate_admin_grant(
    token: str | None,
    user_id: str,
    *,
    admin_token: str,
    users_lock_file: Path,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    save_users: Callable[[dict[str, dict[str, Any]]], None],
    current_admin_grant_record: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_entitlements_response: Callable[[dict[str, Any] | None], Any],
    authorization: str | None = None,
    grant_updates: dict[str, Any] | None = None,
) -> AdminUserEntitlementResponse:
    """Shared logic for granting/revoking admin Pro access."""
    require_admin(token, admin_token=admin_token, authorization=authorization)

    with FileLock(str(users_lock_file)):
        users = load_users()
        record = users.get(user_id)
        if not isinstance(record, dict) or user_id.startswith("_"):
            raise HTTPException(status_code=404, detail="User not found")

        admin_grant = current_admin_grant_record(record)
        if grant_updates:
            admin_grant.update(grant_updates)
        record["admin_grant"] = admin_grant
        save_users(users)

    return AdminUserEntitlementResponse(
        user_id=user_id,
        pro=build_entitlements_response(record).pro,
        admin_grant=AdminGrantStatusResponse(**admin_grant),
    )
```

- [ ] **Step 2: Simplify grant and revoke to use the helper**

```python
def admin_grant_pro_access_response(
    token, user_id, req, *, admin_token, users_lock_file, load_users, save_users,
    current_admin_grant_record, build_entitlements_response, authorization=None,
):
    now_iso = datetime.now(tz=UTC).isoformat()
    return _mutate_admin_grant(
        token, user_id,
        admin_token=admin_token, users_lock_file=users_lock_file,
        load_users=load_users, save_users=save_users,
        current_admin_grant_record=current_admin_grant_record,
        build_entitlements_response=build_entitlements_response,
        authorization=authorization,
        grant_updates={
            "is_active": True,
            "plan_name": admin_grant.get("plan_name") or "Books & Vocab Pro",
            "status": "active",
            "source": "admin",
            "expires_at": req.expires_at,
            "granted_at": now_iso,
            "granted_by": (req.granted_by or "admin").strip() or "admin",
            "reason": req.reason.strip() if isinstance(req.reason, str) and req.reason.strip() else None,
            "last_synced_at": now_iso,
        },
    )


def admin_revoke_pro_access_response(
    token, user_id, *, admin_token, users_lock_file, load_users, save_users,
    current_admin_grant_record, build_entitlements_response, authorization=None,
):
    now_iso = datetime.now(tz=UTC).isoformat()
    return _mutate_admin_grant(
        token, user_id,
        admin_token=admin_token, users_lock_file=users_lock_file,
        load_users=load_users, save_users=save_users,
        current_admin_grant_record=current_admin_grant_record,
        build_entitlements_response=build_entitlements_response,
        authorization=authorization,
        grant_updates={
            "is_active": False,
            "status": "inactive",
            "source": "admin",
            "last_synced_at": now_iso,
        },
    )
```

- [ ] **Step 3: Run admin tests**

Run: `cd backend && python -m pytest tests/ -k admin -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/src/kg/admin_handlers.py
git commit -m "api: deduplicate admin grant/revoke via shared _mutate_admin_grant helper"
```

---

## Phase 4: Notebook API Integration Tests

### Task 4.1: Add notebook CRUD endpoint tests

**Files:**
- Create: `backend/tests/test_notebook_api.py`

- [ ] **Step 1: Write notebook CRUD integration tests**

```python
# backend/tests/test_notebook_api.py
"""Integration tests for notebook CRUD API endpoints."""
import pytest
from pathlib import Path


@pytest.fixture()
def notebook_env(tmp_path: Path):
    """Isolated API client with auth for notebook testing."""
    from kg.api import create_app
    from kg.settings import KGSettings
    from fastapi.testclient import TestClient
    import json

    jwt_secret = "test-secret-1234567890"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    users_dir = data_dir / "users" / "test_user"
    users_dir.mkdir(parents=True)

    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({
        "test_user": {"provider": "google", "provider_user_id": "g123", "email": "t@t.com"}
    }))

    settings = KGSettings(data_dir=data_dir, jwt_secret=jwt_secret)
    app = create_app(settings)
    client = TestClient(app)

    import jwt as pyjwt
    from datetime import datetime, UTC, timedelta
    token = pyjwt.encode(
        {"sub": "test_user", "provider": "google", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)},
        jwt_secret, algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


def test_list_notebooks_empty(notebook_env):
    client, headers = notebook_env
    resp = client.get("/api/notebooks", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_create_notebook(notebook_env):
    client, headers = notebook_env
    resp = client.post("/api/notebooks", json={"name": "Test Book", "color": "#FF0000"}, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Book"
    assert data["color"] == "#FF0000"
    assert "id" in data


def test_update_notebook(notebook_env):
    client, headers = notebook_env
    create = client.post("/api/notebooks", json={"name": "Old"}, headers=headers)
    nb_id = create.json()["id"]

    resp = client.patch(f"/api/notebooks/{nb_id}", json={"name": "New"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_delete_notebook(notebook_env):
    client, headers = notebook_env
    create = client.post("/api/notebooks", json={"name": "ToDelete"}, headers=headers)
    nb_id = create.json()["id"]

    resp = client.delete(f"/api/notebooks/{nb_id}", headers=headers)
    assert resp.status_code == 200


def test_delete_default_notebook_fails(notebook_env):
    client, headers = notebook_env
    resp = client.delete("/api/notebooks/default", headers=headers)
    assert resp.status_code in (400, 403, 422)


def test_delete_nonexistent_notebook(notebook_env):
    client, headers = notebook_env
    resp = client.delete("/api/notebooks/nonexistent123", headers=headers)
    # Should be idempotent or 404
    assert resp.status_code in (200, 404)
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/test_notebook_api.py -v`

- [ ] **Step 3: Fix any failures, iterate**

Adjust test expectations based on actual API behavior (response shapes, status codes).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_notebook_api.py
git commit -m "api: add notebook CRUD endpoint integration tests"
```

---

### Task 4.2: Add daily-stats and review endpoint tests

**Files:**
- Create: `backend/tests/test_daily_stats_api.py`

- [ ] **Step 1: Write daily-stats endpoint tests**

Use the same fixture pattern as `test_notebook_api.py`. Cover:
- `GET /api/vocab/daily-stats` — empty state
- `PATCH /api/vocab/daily-stats` — push stats, then GET to verify
- `PATCH /api/vocab/review` — push review state

- [ ] **Step 2: Run and iterate**

Run: `cd backend && python -m pytest tests/test_daily_stats_api.py -v`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_daily_stats_api.py
git commit -m "api: add daily-stats and review endpoint integration tests"
```

---

## Phase 5: GraphStore SQLite Migration

> **Scope warning:** This is the largest task. It replaces JSON-based GraphStore with SQLite, affecting graph.py, service_factories.py, and all graph consumers. Consider whether the current user base justifies this investment.

### Task 5.1: Define SQLite-backed GraphLink model

**Files:**
- Modify: `backend/src/kg/graph.py`
- Test: `backend/tests/test_graph_sqlite.py` (create)

- [ ] **Step 1: Write test for SQLite GraphStore**

```python
# backend/tests/test_graph_sqlite.py
"""Tests for SQLite-backed GraphStore."""
from pathlib import Path
from kg.graph import GraphStore, LinkKind


def test_add_and_retrieve_link(tmp_path: Path):
    store = GraphStore(tmp_path / "graph.db")
    link = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "opposites")
    assert link.id
    found = store.get_links_for("a")
    assert len(found) == 1
    assert found[0].from_id == "a"


def test_has_link(tmp_path: Path):
    store = GraphStore(tmp_path / "graph.db")
    store.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "related")
    assert store.has_link("a", "b")
    assert store.has_link("b", "a")  # bidirectional
    assert not store.has_link("a", "c")


def test_deprecate_and_restore(tmp_path: Path):
    store = GraphStore(tmp_path / "graph.db")
    store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "test")
    store.deprecate_links_for("a")
    assert store.get_links_for("a") == []  # active only
    assert store.link_count() == 0


def test_candidates(tmp_path: Path):
    store = GraphStore(tmp_path / "graph.db")
    store.add_candidate("x", "y", 0.85)
    candidates = store.pop_candidates()
    assert len(candidates) == 1
    assert store.pop_candidates() == []  # cleared


def test_persistence(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    store1 = GraphStore(db_path)
    store1.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "test")
    store1.close()

    store2 = GraphStore(db_path)
    assert store2.has_link("a", "b")
    store2.close()
```

- [ ] **Step 2: Run test — will fail (constructor signature changed)**

Run: `cd backend && python -m pytest tests/test_graph_sqlite.py -v`

- [ ] **Step 3: Implement SQLite-backed GraphStore**

Rewrite `backend/src/kg/graph.py`:
- Keep `GraphLink`, `CandidatePair`, `LinkKind` models unchanged
- Replace GraphStore internals: `__init__` takes a single `db_path: Path`
- Use SQLModel tables for `graph_link` and `candidate_pair`
- Keep the same public API: `add_link`, `get_links_for`, `has_link`, `all_links`, `link_count`, `add_candidate`, `pop_candidates`, `requeue_candidates`, `candidate_count`, `deprecate_links_for`, `restore_links_for`, `remove_candidates_for`, `close`
- Remove `_from_index`, `_to_index`, `_save_links`, `_save_candidates`, `_load`

**Key design decisions:**
- Queries replace in-memory indexes (SQLite indexes on from_id, to_id)
- Write-through: no batch save, each mutation is a commit
- Migration: add `_migrate_from_json()` that imports legacy JSON files on first open

- [ ] **Step 4: Update service_factories.py**

Change `create_graph_store` to pass a single `db_path` instead of `links_path` + `candidates_path`:

```python
def create_graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    key = f"graph:{user_dir}:{notebook_id}"
    nb_dir = user_dir / "notebooks" / notebook_id
    nb_dir.mkdir(parents=True, exist_ok=True)
    db_path = nb_dir / "graph.db"
    # Legacy migration: if JSON files exist, they'll be imported on first open
    return _get_cached(key, lambda: GraphStore(db_path))
```

- [ ] **Step 5: Run full test suite**

Run: `cd backend && python -m pytest -x -q`

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/graph.py backend/src/kg/service_factories.py backend/tests/test_graph_sqlite.py
git commit -m "api: migrate GraphStore from JSON to SQLite for scalability"
```

---

## Execution Notes

- **Each phase is independent** — earlier phases don't block later ones, though Phase 1 (store lifecycle) makes Phase 5 (GraphStore migration) cleaner.
- **Phase 5 is optional** — JSON GraphStore works fine for current scale (~hundreds of links per user). Only invest if users grow to thousands of vocabulary items.
- **Wiring constants** (Phase 2 follow-up): After adding fields to KGSettings, threading them through the dependency chain is mechanical but touches many files. Do this incrementally, one module at a time, with tests.
- **Run `python -m pytest -x -q` after every commit** to catch regressions early.
