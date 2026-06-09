from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

# Always prefer this workspace's source tree during tests.
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Force deterministic test env (do not inherit prod secrets/config).
os.environ["KG_DATA_DIR"] = "/tmp/kg_test_default"
os.environ["JWT_SECRET"] = "test-secret-key-for-ci-at-least-32-bytes"
os.environ["GEMINI_API_KEY"] = "fake-key"
# Pin LLM routing before api.py's load_dotenv() can inject a dev .env value:
# load_dotenv defaults to override=False, so pre-setting wins. Token-cost and
# quota assertions are written against gemini pricing. Tests that need to
# exercise provider switching MUST use monkeypatch.setenv/delenv (function
# scope, auto-reverts) — do not mutate os.environ at module scope.
for _k in [k for k in os.environ if k.startswith("LLM_PROVIDER_")]:
    del os.environ[_k]
os.environ["LLM_PROVIDER_DEFAULT"] = "gemini"


TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
TEST_ALGORITHM = "HS256"
TEST_PUBLIC_WEB_BASE_URL = "https://wordnexus.lol"
TEST_GOOGLE_REDIRECT_URI = TEST_PUBLIC_WEB_BASE_URL + "/auth/web/google/callback"
TEST_PRO_PRODUCT_ID = "com.wordnexus.pro.monthly"


def make_settings(tmp_path: Path):
    from kg.settings import KGSettings

    return KGSettings(
        data_dir=tmp_path,
        jwt_secret=TEST_JWT_SECRET,
        jwt_algorithm=TEST_ALGORITHM,
    )


def make_jwt(user_id: str, *, expires_in: timedelta = timedelta(hours=1)) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + expires_in,
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _swap_settings(new_settings):
    """Replace app.state.kg_settings and rebuild load/save closures."""
    import kg.podcast_progress as _pp
    from kg.api import app
    from kg.billing import default_subscription_payload
    from kg.user_store import CachedUserStore, normalize_users_payload

    app.state.kg_settings = new_settings
    _pp.set_data_dir(new_settings.data_dir)

    def _normalize(users):
        from kg.secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, default_subscription_payload, encrypt_fn=encrypt_fn)

    user_store = CachedUserStore(new_settings.users_file, _normalize)
    app.state.user_store = user_store
    app.state.load_users = lambda: user_store.load()
    app.state.save_users = lambda users: user_store.save(users)
    app.state.normalize_users_payload = _normalize


@pytest.fixture()
def admin_app_factory(tmp_path, monkeypatch):
    """Build an admin TestClient harness for the 7 admin-endpoint test modules.

    Each module previously hand-rolled a near-identical ``admin_app`` fixture:
    setenv KG_DATA_DIR → mkdir users/ → seed users.json → snapshot
    app.state.kg_settings → build KGSettings(admin_token/admin_password) →
    _swap_settings → yield SimpleNamespace(client, data_dir) → restore in finally.

    This factory folds in the few real axes of variation as keyword args:

    - ``users_seed``: dict written to users.json (default ``{"_meta": {}}``).
    - ``admin_token`` / ``admin_password``: KGSettings auth knobs.
    - ``inject_cookie``: when True, seed the TestClient with a signed
      ``admin_session`` cookie for ``admin_token`` (users-search pattern).
    - ``reset_audit``: when True, call ``admin_audit._reset()`` before/after
      and setenv KG_DATA_DIR (audit-endpoint pattern).
    - ``setup_log_dbs``: when True, redirect pipeline/judge/token/translate log
      SQLite singletons to tmp_path and reset them (observability/trends pattern).

    Returns a builder callable so a test module can build multiple settings
    shapes (e.g. login's password-enabled vs password-disabled).
    """
    from kg.api import app
    from kg.settings import KGSettings

    cleanups: list = []

    def _build(
        *,
        users_seed: dict | None = None,
        admin_token: str | None = None,
        admin_password: str = "",
        inject_cookie: bool = False,
        reset_audit: bool = False,
        setup_log_dbs: bool = False,
    ):
        data_dir = tmp_path
        (data_dir / "users").mkdir(exist_ok=True)
        users_file = data_dir / "users.json"
        users_file.write_text(json.dumps(users_seed if users_seed is not None else {"_meta": {}}))

        monkeypatch.setenv("KG_DATA_DIR", str(data_dir))

        if reset_audit:
            from kg import admin_audit
            admin_audit._reset()
            cleanups.append(admin_audit._reset)

        if setup_log_dbs:
            import kg.judge_log as jl
            import kg.pipeline_log as pl
            import kg.token_tracker as tt
            import kg.translate_log as tl
            pl.DATA_DIR = data_dir
            pl.DB_PATH = data_dir / "pipeline_runs.db"
            jl.DATA_DIR = data_dir
            jl.DB_PATH = data_dir / "judge_log.db"
            tt.DATA_DIR = data_dir
            tt.DB_PATH = data_dir / "token_usage.db"

            def _reset_log_dbs():
                pl._reset()
                jl._reset()
                tl._reset()
                if tt._conn is not None:
                    tt._conn.close()
                    tt._conn = None

            _reset_log_dbs()
            cleanups.append(_reset_log_dbs)

        original_settings = app.state.kg_settings
        original_load = app.state.load_users
        original_save = app.state.save_users

        def _restore_settings():
            app.state.kg_settings = original_settings
            app.state.load_users = original_load
            app.state.save_users = original_save

        cleanups.append(_restore_settings)

        test_settings = KGSettings(
            data_dir=data_dir,
            jwt_secret=TEST_JWT_SECRET,
            admin_token=admin_token,
            admin_password=admin_password,
        )
        _swap_settings(test_settings)

        if inject_cookie:
            from kg.admin_handlers import _sign_cookie
            cookie = _sign_cookie(admin_token)
            client = TestClient(app, raise_server_exceptions=False, cookies={"admin_session": cookie})
        else:
            client = TestClient(app, raise_server_exceptions=False)

        return SimpleNamespace(client=client, data_dir=data_dir)

    try:
        yield _build
    finally:
        for fn in reversed(cleanups):
            fn()


@pytest.fixture()
def translate_data_dir(tmp_path, monkeypatch):
    """Point translate_log's SQLite DB at a per-test tmp dir.

    The autouse ``_isolate_translate_log`` already clears rows + resets the
    singleton, but it runs (and opens a conn) under the default KG_DATA_DIR.
    translate-cache modules that need their DB physically isolated under
    tmp_path opt into this: it setenvs KG_DATA_DIR then resets so the next
    ``_get_conn`` re-opens under tmp_path. (The post-yield reset is provided
    by the autouse fixture's teardown.)
    """
    import kg.translate_log as tl

    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    tl._reset()
    yield


@pytest.fixture()
def isolate_pipeline_db(tmp_path, monkeypatch):
    """Point pipeline_log at a fresh temp DB and reset its singleton.

    Shared by the pipeline_log test modules (start/step/run lifecycle +
    telemetry recording). The DB filename inside tmp_path is irrelevant —
    each test gets a unique tmp_path, so a single name suffices.
    """
    from kg import pipeline_log

    monkeypatch.setattr(pipeline_log, "DB_PATH", tmp_path / "pipeline_runs.db")
    pipeline_log._reset()
    yield
    pipeline_log._reset()


class _DummyEmbeddingStore:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    def has(self, card_id: str) -> bool:
        return card_id in self._ids

    def add(self, card_id: str, text: str) -> None:
        self._ids.add(card_id)

    def add_batch(self, items: list) -> None:
        for card_id, text in items:
            self.add(card_id, text)

    def find_similar(self, card_id: str, k: int = 3):
        return []


# Provider-routing determinism: ambient env that biases per-call-type routing.
ROUTING_PREFIX = "LLM_PROVIDER_"
ROUTING_MODEL_ENV = ("GEMINI_MODEL", "DEEPSEEK_MODEL")


@pytest.fixture()
def clean_routing_env(monkeypatch):
    """Strip ambient provider-routing env so each test is deterministic."""
    for name in list(os.environ):
        if name.startswith(ROUTING_PREFIX) or name in ROUTING_MODEL_ENV:
            monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_translate_log():
    """Clear translate_log between tests to prevent cache cross-contamination."""
    import kg.translate_log as tl
    tl._reset()
    conn = tl._get_conn()
    conn.execute("DELETE FROM translate_log")
    conn.commit()
    yield
    tl._reset()


@pytest.fixture(autouse=True)
def _isolate_podcast_progress():
    """Reset podcast_progress singleton so each test's KG_DATA_DIR fixture
    gets a fresh DB file under its tmp_path."""
    import kg.podcast_progress as pp
    pp._reset()
    yield
    pp._reset()


@pytest.fixture(autouse=True)
def _isolate_rate_limiters():
    """Reset the process-wide rate-limiter singletons between tests.

    `api_limiter` / `translate_limiter` are module-level instances driven by
    `rate_limit_middleware` on every TestClient request. Their sliding-window
    state is keyed on the last 16 chars of the Authorization header (or client
    host for unauthenticated calls), so a full pytest session accumulates
    admissions across unrelated tests fast enough to trip the 60-req window —
    surfacing as spurious `429` in podcast endpoint tests. Clearing both
    limiters per test makes the suite order-independent."""
    from kg.rate_limit import api_limiter, translate_limiter
    api_limiter.reset()
    translate_limiter.reset()
    yield
    api_limiter.reset()
    translate_limiter.reset()


@pytest.fixture(autouse=True)
def _isolate_observability_cooldown():
    """Clear observability_alerts in-memory alert cooldown between tests.

    `_cooldown_state` is a module-level dict that suppresses duplicate Sentry
    alerts for 30 minutes. `/api/system/info` triggers `run_all_checks()`
    piggyback-style, so any test hitting that endpoint stamps cooldowns that
    leak into later cooldown-sensitive assertions. Resetting per test keeps
    the suite order-independent (test_observability_alerts.py keeps its own
    module-scoped fixture; this guards every other file)."""
    from kg import observability_alerts
    observability_alerts._cooldown_state.clear()
    yield
    observability_alerts._cooldown_state.clear()


ADMIN_TOKEN = "test-admin-token-value"


def make_admin_client(tmp_path, monkeypatch, *, setup_logs, teardown_logs):
    """Shared admin TestClient factory for admin-endpoint tests.

    Builds a tmp data_dir + users.json, sets KG_DATA_DIR, swaps in test
    settings with an admin token, and yields an admin TestClient. Callers
    supply `setup_logs(data_dir, monkeypatch)` to patch their specific log
    module's DATA_DIR/DB_PATH (and prime its connection) and `teardown_logs()`
    to release it.
    """
    from kg.api import app
    from kg.settings import KGSettings

    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}, "u1": {"config": {}}}))

    monkeypatch.setenv("KG_DATA_DIR", str(data_dir))
    setup_logs(data_dir, monkeypatch)

    original_settings = app.state.kg_settings
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings
        teardown_logs()


@pytest.fixture()
def isolated_api(tmp_path):
    import kg.api as api_mod
    import kg.deps as deps_mod
    from kg.api import app
    from kg.settings import KGSettings

    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    users_file.write_text(
        json.dumps(
            {
                user_id: {"config": {}},
                "other_user": {
                    "config": {},
                    "provider": "google",
                    "email": "other@example.com",
                },
            }
        )
    )

    users_data = json.loads(users_file.read_text())
    users_data[user_id]["subscription"] = {
        "is_active": True,
        "status": "active",
        "plan_name": "Books & Vocab Pro",
        "trial_days": 7,
        "will_renew": True,
    }
    users_file.write_text(json.dumps(users_data))

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
            users_file=users_file,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save
