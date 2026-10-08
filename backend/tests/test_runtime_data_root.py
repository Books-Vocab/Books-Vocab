"""Runtime SQLite stores stay on the data root the app lifespan locked.

The lifespan takes the single-worker lock on ``settings.data_dir`` and sweeps
that directory's orphaned rows at startup.  Every later runtime read/write of
the same stores must land in that directory too: if ``KG_DATA_DIR`` points
elsewhere, rows written there are invisible to the next startup's sweep and
stay non-terminal forever (and the process touches a root it holds no lock on).
The same holds for the quota ledger, translate cache, judge/LLM-error logs,
admin audit trail and podcast progress: an app built on one root must never
split its state with whatever ``KG_DATA_DIR`` happens to name.
"""

from __future__ import annotations

import ast
import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import kg
from kg import (
    admin_audit,
    judge_log,
    llm_error_log,
    pipeline_log,
    podcast_progress,
    quota_service,
    runtime_data_root,
    token_tracker,
    translate_log,
    worker_guard,
)
from kg import vocab_add_link_operation as operations
from kg.api import create_app
from kg.settings import KGSettings

_RUNTIME_STORES = (
    operations,
    pipeline_log,
    token_tracker,
    judge_log,
    llm_error_log,
    translate_log,
    admin_audit,
    podcast_progress,
)


def _reset_runtime_stores() -> None:
    for store in _RUNTIME_STORES:
        store.reset()


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "users.json").write_text("{}")
    # A sentinel root nothing may create: any runtime access through
    # KG_DATA_DIR would mkdir it on first connection.
    sentinel = tmp_path / "kg-data-dir-sentinel"
    monkeypatch.setenv("KG_DATA_DIR", str(sentinel))
    _reset_runtime_stores()
    yield locked, sentinel
    _reset_runtime_stores()


def _settings(data_dir: Path) -> KGSettings:
    return KGSettings(
        data_dir=data_dir,
        jwt_secret="test-secret-key-for-ci-at-least-32-bytes",
        admin_token="adm-secret",
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )


def _statuses(db: Path, table: str, key: str, value: str) -> list[str]:
    with closing(sqlite3.connect(db)) as conn:
        return [row[0] for row in conn.execute(f"SELECT status FROM {table} WHERE {key} = ?", (value,))]


def _start_add_link_operation_and_pipeline_run() -> str:
    operation, created = operations.create_operation(
        user_id="u1", notebook_id="default", idempotency_key="k1", payload={"target_word": "x"}
    )
    assert created
    operations.start_operation(operation["operation_id"])
    pipeline_log.start_run("run-1", "u1", "default", "manual")
    pipeline_log.start_step("run-1", "translate")
    return operation["operation_id"]


def test_runtime_reads_and_writes_use_the_locked_data_root(roots):
    locked, sentinel = roots

    with TestClient(create_app(_settings(locked))):
        operation_id = _start_add_link_operation_and_pipeline_run()
        assert operations.get_operation("u1", operation_id)["status"] == "running"
        assert [run["run_id"] for run in pipeline_log.get_runs("u1")] == ["run-1"]

    assert not sentinel.exists(), "runtime opened the KG_DATA_DIR root instead of the locked settings.data_dir"
    assert _statuses(locked / operations._DB_FILENAME, "vocab_add_link_operations", "operation_id", operation_id) == [
        "running"
    ]
    assert _statuses(locked / pipeline_log._DB_FILENAME, "pipeline_runs", "run_id", "run-1") == ["running"]


def test_restart_on_the_locked_root_terminalizes_what_the_previous_process_left_running(roots):
    locked, sentinel = roots

    with TestClient(create_app(_settings(locked))):
        operation_id = _start_add_link_operation_and_pipeline_run()
    operations.reset()
    pipeline_log.reset()  # the process died; only SQLite survives

    with TestClient(create_app(_settings(locked))):
        pass

    assert _statuses(locked / operations._DB_FILENAME, "vocab_add_link_operations", "operation_id", operation_id) == [
        "interrupted"
    ]
    assert _statuses(locked / pipeline_log._DB_FILENAME, "pipeline_runs", "run_id", "run-1") == ["interrupted"]
    assert not sentinel.exists()


def test_binding_lives_exactly_as_long_as_the_worker_lock(roots):
    locked, sentinel = roots
    assert runtime_data_root.bound() is None

    with TestClient(create_app(_settings(locked))):
        assert runtime_data_root.bound() == locked
        assert runtime_data_root.current() == locked

    # Lock released: the process no longer owns the root, so nothing stays bound
    # and module-level callers resolve KG_DATA_DIR again.
    assert runtime_data_root.bound() is None
    assert runtime_data_root.current() == sentinel


def test_release_only_drops_the_binding_it_was_given(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path / "env"))
    first, second = tmp_path / "first", tmp_path / "second"
    try:
        runtime_data_root.bind(first)
        runtime_data_root.bind(second)
        runtime_data_root.release(first)  # stale release from an app that was replaced
        assert runtime_data_root.current() == second

        runtime_data_root.release(second)
        assert runtime_data_root.bound() is None
        assert runtime_data_root.current() == tmp_path / "env"
    finally:
        runtime_data_root.release(first)
        runtime_data_root.release(second)


def _record_translate_call() -> None:
    translate_log.record(
        user_id="u1",
        operation="translate",
        word="word",
        context="",
        context_hash="ctx",
        source_lang="en",
        target_lang="zh-Hant",
        response_raw="{}",
        latency_ms=1,
    )


def _record_translate_cache_hit() -> None:
    translate_log.record_cache_hit(
        user_id="u1",
        operation="translate",
        word="word",
        context_hash="ctx",
        source_lang="en",
        target_lang="zh-Hant",
    )


def _record_judge_reject() -> None:
    judge_log.record(
        user_id="u1",
        notebook_id="default",
        from_id="from",
        to_id="to",
        similarity=0.5,
        verdict="reject",
        confidence=0.9,
        accepted=False,
    )


def _upsert_podcast_progress() -> None:
    podcast_progress.upsert(
        user_id="u1",
        series_id="series",
        ep_num=1,
        position_sec=1,
        duration_sec=2,
        updated_at="2026-01-01T00:00:00Z",
    )


def _create_add_link_operation() -> None:
    operations.create_operation(user_id="u1", notebook_id="default", idempotency_key="k1", payload={"target_word": "x"})


@pytest.mark.parametrize(
    ("db_name", "write"),
    [
        pytest.param("token_usage.db", lambda: token_tracker.record("u1", "translate", 1, 1), id="token_tracker"),
        pytest.param("judge_log.db", _record_judge_reject, id="judge_log"),
        pytest.param(
            "llm_errors.db",
            lambda: llm_error_log.record(user_id="u1", call_type="translate", error_class="RateLimitError"),
            id="llm_error_log",
        ),
        pytest.param("translate_log.db", _record_translate_call, id="translate_log"),
        pytest.param("translate_log.db", _record_translate_cache_hit, id="translate_cache_hit"),
        pytest.param(
            "admin_audit.db",
            lambda: admin_audit.record_audit(admin_uid="admin", action="grant_pro", target_uid="u1"),
            id="admin_audit",
        ),
        pytest.param("podcast_progress.db", _upsert_podcast_progress, id="podcast_progress"),
        pytest.param(
            "pipeline_runs.db",
            lambda: pipeline_log.start_run("run-1", "u1", "default", "manual"),
            id="pipeline_log",
        ),
        pytest.param("vocab_add_link_operations.db", _create_add_link_operation, id="vocab_add_link_operation"),
    ],
)
def test_every_runtime_store_writes_under_the_locked_root(roots, db_name: str, write: Callable[[], object]):
    locked, sentinel = roots

    with TestClient(create_app(_settings(locked))):
        write()

    assert (locked / db_name).exists(), f"{db_name} was not written under the locked settings.data_dir"
    assert not sentinel.exists(), f"{db_name} opened the KG_DATA_DIR root instead of the locked settings.data_dir"


def test_quota_reads_the_usage_recorded_on_the_locked_root(roots, monkeypatch):
    locked, sentinel = roots
    user_id = "u-quota-locked-root"
    # Spend recorded on this root by an earlier process; the env now names another root.
    monkeypatch.setenv("KG_DATA_DIR", str(locked))
    token_tracker.record(user_id, "translate", 100_000, 100_000)
    token_tracker.reset()
    monkeypatch.setenv("KG_DATA_DIR", str(sentinel))

    with TestClient(create_app(_settings(locked))):
        fraction = quota_service.get_quota_state(user_id)["fraction"]

    assert fraction < 1.0, "quota read an empty ledger: the user's spend on the locked root was not counted"
    assert not sentinel.exists()


def test_podcast_progress_follows_the_bound_root_without_an_override(roots, tmp_path):
    _locked, sentinel = roots
    root = tmp_path / "bound"
    root.mkdir()
    podcast_progress.reset()  # drop any create_app override: only the binding is left
    runtime_data_root.bind(root)
    try:
        _upsert_podcast_progress()
    finally:
        runtime_data_root.release(root)

    assert (root / "podcast_progress.db").exists()
    assert not sentinel.exists()


def test_aborted_shutdown_still_releases_the_binding_and_the_worker_lock(roots):
    locked, _sentinel = roots
    app = create_app(_settings(locked))

    async def _start_then_abort() -> None:
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        assert runtime_data_root.bound() == locked
        aborted = RuntimeError("server task torn down before a clean shutdown")
        await lifespan.__aexit__(RuntimeError, aborted, aborted.__traceback__)

    try:
        asyncio.run(_start_then_abort())
        assert runtime_data_root.bound() is None, "an aborted shutdown left the runtime stores bound to the root"
        assert worker_guard._lock_fd is None, "an aborted shutdown kept the worker lock"
    finally:
        runtime_data_root.release(locked)
        worker_guard.release_worker_lock()


# Runtime code resolves the data root through runtime_data_root.current() and
# settings through app.state.kg_settings.  Per-call ops_shared.data_dir() /
# load_settings() re-read the environment and silently diverge from the root
# the app was built on.  Exempt: CLIs and ops tools (env semantics by design),
# the resolvers themselves, and the composition root.  Module-level
# ``DATA_DIR = data_dir()`` seeds stay allowed: they are only the test hook.
_SRC_DIR = Path(kg.__file__).resolve().parent
_EXEMPT_FILES = {"api.py", "orphan_scan.py", "runtime_data_root.py", "settings.py"}
# Settings still read per call (#2090 residuals, neither resolves a data path).
# Each entry must keep naming a live call site, so the list can only shrink.
_DEFERRED_LOAD_SETTINGS = {
    "pipeline_service/steps.py": "judge_confidence_threshold per judge run; plumbing goes through runner.py",
    "service_factories.py": "create_embedding_store model/dim fallback; env re-read pinned by test_embedding_edges",
}


def _function_level_calls(path: Path, home_module: str, func: str) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    func_names: set[str] = set()
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            from_home = (node.module or "").split(".")[-1] == home_module
            for alias in node.names:
                if from_home and alias.name == func:
                    func_names.add(alias.asname or alias.name)
                elif node.module in (None, "kg") and alias.name == home_module:
                    module_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            module_names.update(a.asname for a in node.names if a.asname and a.name == f"kg.{home_module}")

    def _is_home_module(value: ast.expr) -> bool:
        # `ops_shared.data_dir()` via an alias, or dotted `kg.ops_shared.data_dir()`.
        return (isinstance(value, ast.Name) and value.id in module_names) or (
            isinstance(value, ast.Attribute) and value.attr == home_module
        )

    lines: list[int] = []

    class _Visitor(ast.NodeVisitor):
        depth = 0

        def _function_scope(self, node: ast.AST) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _function_scope

        def visit_Call(self, node: ast.Call) -> None:
            target = node.func
            if self.depth and (
                (isinstance(target, ast.Name) and target.id in func_names)
                or (isinstance(target, ast.Attribute) and target.attr == func and _is_home_module(target.value))
            ):
                lines.append(node.lineno)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return lines


def _runtime_call_sites(home_module: str, func: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(_SRC_DIR.rglob("*.py")):
        rel = path.relative_to(_SRC_DIR).as_posix()
        if rel in _EXEMPT_FILES or rel.startswith("ops_"):
            continue
        if lines := _function_level_calls(path, home_module, func):
            found[rel] = lines
    return found


def test_runtime_code_never_rereads_the_data_root_from_the_environment():
    assert _runtime_call_sites("ops_shared", "data_dir") == {}


def test_runtime_code_reads_settings_per_call_only_at_the_deferred_sites():
    assert set(_runtime_call_sites("settings", "load_settings")) == set(_DEFERRED_LOAD_SETTINGS)
