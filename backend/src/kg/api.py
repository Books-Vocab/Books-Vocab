"""FastAPI server for Knowledge Graph — lightweight bridge for BooksBrowser.

App factory, middleware stack, and route wiring.
Endpoint functions live in their respective routers/*.py files.
Shared dependencies live in deps.py.

Usage:
    uvicorn kg.api:app --reload --port 8000
"""

from __future__ import annotations

import atexit
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

# Memory ring-buffer log handler for the admin dashboard.
# Re-exported so existing tests (from kg.api import _mem_log) keep working.
from .mem_log import _MemoryLogHandler, install_memory_log_handler  # noqa: F401

_mem_log = install_memory_log_handler(maxlen=1000)

from .app_router_composition import build_app_routers, include_app_routers
from .app_runtime_state import install_runtime_user_state
from .app_middleware import _anon_rate_limit_key, install_app_middlewares
from .app_exception_handlers import (
    _redact_validation_body,
    _redact_validation_payload,
    install_app_exception_handlers,
)
from .api_compat import *  # noqa: F401,F403 - stable kg.api compatibility surface
from .api_compat import (
    _build_entitlements_response,
    _card_store,
    _current_admin_grant_record,
    _default_subscription_payload,
)
from .rate_limit import api_limiter, translate_limiter
from .service_factories import clear_store_cache
from .settings import KGSettings, load_settings

load_dotenv()

# Initialize Sentry early so module-level errors and the lifespan are captured.
# No-op when SENTRY_DSN is unset.
from .sentry_init import init_sentry  # noqa: E402

init_sentry()


def create_app(settings: KGSettings | None = None) -> FastAPI:
    atexit.register(clear_store_cache)

    settings = settings or load_settings()

    # Sync quota limits with settings
    from .quota_service import configure_limits
    configure_limits(pro=settings.pro_daily_limit_usd, free=settings.free_daily_limit_usd)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("KG API starting up")
        # Fail loud if a second worker boots: quota reservations, translate
        # singleflight and pipeline_log are all process-local and only
        # correct under --workers 1. Lock under the injected settings'
        # data_dir so a test app never touches the real backend/data/.
        from .worker_guard import assert_single_worker
        assert_single_worker(settings.data_dir / ".worker.lock")
        # Crash recovery: sweep orphaned 'running' pipeline runs → 'interrupted'.
        # Explicit startup step (not a side-effect of first DB access) so reads
        # stay write-free. Safe only post single-worker lock: workers must not
        # cross-mark each other's runs (see worker_guard).
        from .pipeline_log import reap_orphaned_runs
        reaped = reap_orphaned_runs()
        if reaped:
            logger.info("Reaped %d orphaned pipeline run(s) → interrupted", reaped)
        yield
        logger.info("KG API shutting down")
        from .worker_guard import release_worker_lock
        release_worker_lock()
        from .service_factories import reset_async_clients, reset_clients
        reset_clients()
        await reset_async_clients()

    app = FastAPI(title="Knowledge Graph API", version="0.1.0", lifespan=lifespan)
    app.state.kg_settings = settings

    # --- user store helpers ---
    runtime_user_state = install_runtime_user_state(
        app,
        settings,
        default_subscription_payload_fn=_default_subscription_payload,
    )

    # --- middleware stack ---
    from . import sentry_init as _sentry_init
    from .request_context import request_id_var

    install_app_middlewares(
        app,
        cors_origins=settings.cors_origins,
        rate_limit_trusted_hops=settings.rate_limit_trusted_hops,
        request_id_var=request_id_var,
        tag_request_id=_sentry_init.tag_request_id,
        api_limiter=api_limiter,
        translate_limiter=translate_limiter,
    )
    install_app_exception_handlers(app, logger=logger)

    # --- routers ---
    def _settings_fn() -> KGSettings:
        return app.state.kg_settings

    def _users_lock_file_fn() -> Path:
        return app.state.kg_settings.users_lock_file

    app_routers = build_app_routers(
        runtime_settings_fn=_settings_fn,
        runtime_users_lock_file_fn=_users_lock_file_fn,
        load_users_fn=runtime_user_state.load_users,
        save_users_fn=runtime_user_state.save_users,
        mem_log_getter=_mem_log.get,
        card_store_factory=_card_store,
        build_entitlements_response_fn=_build_entitlements_response,
        current_admin_grant_record_fn=_current_admin_grant_record,
    )
    include_app_routers(app, app_routers)

    # NOTE: the legacy public /api/podcast-media/ StaticFiles mount was removed
    # (2026-05). It served podcast audio/subtitles WITHOUT auth — a public-read
    # bypass of the authenticated /api/podcasts/{series_id}/{ep_num}/audio
    # endpoint. Production deprecation logs showed zero hits over a 12-day
    # window while the authenticated endpoint served all traffic, confirming
    # every shipped client had migrated. Do NOT reintroduce an unauthenticated
    # mount — route podcast media through the authenticated router instead.

    # --- public static assets (官網 design-system CSS + brand fonts) ---
    # Served at /static/* for the public pages (privacy/terms/support/guide). The
    # files live in backend/static/ so the rsync-only-backend/ deploy ships them;
    # kg-tokens.css / kg-components.css are GENERATED by ops/gen_web_tokens.py
    # (drift from the iOS SoT is guarded by ops/token_drift_check.py). This is a
    # read-only public asset mount — unlike the removed podcast-media mount, it
    # serves no user data, only design-system stylesheets and brand fonts.
    from fastapi.staticfiles import StaticFiles
    _static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # Pin the podcast_progress singleton to the same per-instance data_dir
    # as the rest of the app state — keeps test isolation honest when
    # conftest swaps the settings without touching env vars.
    from . import podcast_progress as _progress_store
    _progress_store.set_data_dir(settings.data_dir)

    return app


app = create_app()
