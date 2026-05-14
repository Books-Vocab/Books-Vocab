"""Admin route handler wiring — creates admin endpoint functions with injected dependencies."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import Cookie, Header, Query

from .admin_assets import ADMIN_HTML, ADMIN_TESTS_HTML, ADMIN_USER_DETAIL_HTML
from .admin_handlers import (
    admin_actor_fingerprint,
    admin_audit_response,
    admin_grant_pro_access_response,
    admin_host_metrics_response,
    admin_last_test_run_response,
    admin_logs_response,
    admin_revoke_pro_access_response,
    admin_run_tests_response,
    admin_stats_response,
    admin_test_catalog_response,
    admin_tests_ui_response,
    admin_ui_response,
    admin_user_entitlement_response,
)
from .admin_test_matrix import (
    build_test_catalog,
    get_last_test_run,
    run_pytest_matrix,
    store_last_test_run,
)
from .api_models import AdminGrantRequest, AdminTestRunRequest


def create_admin_handlers(
    *,
    runtime_settings_fn: Callable,
    runtime_users_lock_file_fn: Callable,
    load_users_fn: Callable,
    save_users_fn: Callable,
    mem_log_getter: Callable,
    card_store_factory: Callable,
    build_entitlements_response_fn: Callable,
    current_admin_grant_record_fn: Callable,
) -> dict[str, Callable]:
    """Create all admin endpoint handler functions with dependencies wired in.

    Returns a dict whose keys match the ``admin_*`` parameter names
    expected by :func:`route_registration.register_routes`.
    """

    def admin_ui():
        """Admin dashboard UI."""
        return admin_ui_response(
            admin_html=ADMIN_HTML,
            admin_token=runtime_settings_fn().admin_token,
        )

    def admin_stats():
        """Return per-user token + vocab stats for admin dashboard."""
        from .token_tracker import get_all_stats

        settings = runtime_settings_fn()
        return admin_stats_response(
            load_users=load_users_fn,
            get_all_stats=get_all_stats,
            build_entitlements_response=build_entitlements_response_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            data_dir=settings.data_dir,
            card_store_factory=card_store_factory,
            jwt_secret=settings.jwt_secret,
        )

    def admin_logs(n: int = 200, level: str | None = None):
        """Return recent in-memory log entries for the admin dashboard."""
        return admin_logs_response(
            log_getter=mem_log_getter,
            n=n,
            level=level,
        )

    def admin_user_entitlement(user_id: str):
        """Return one user's computed Pro entitlement plus raw admin grant metadata."""
        return admin_user_entitlement_response(
            user_id,
            load_users=load_users_fn,
            build_entitlements_response=build_entitlements_response_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
        )

    def _actor_from_request(
        token: str | None,
        authorization: str | None,
        admin_session: str | None,
    ) -> str:
        return admin_actor_fingerprint(
            token=token,
            authorization=authorization,
            cookie_token=admin_session,
            admin_token=runtime_settings_fn().admin_token,
        )

    def admin_grant_pro_access(
        req: AdminGrantRequest,
        user_id: str,
        token: str | None = Query(None),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ):
        """Manually grant Pro access for a user through the admin surface."""
        actor = _actor_from_request(token, authorization, admin_session)
        return admin_grant_pro_access_response(
            user_id,
            req,
            users_lock_file=runtime_users_lock_file_fn(),
            load_users=load_users_fn,
            save_users=save_users_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            build_entitlements_response=build_entitlements_response_fn,
            admin_uid=actor,
        )

    def admin_revoke_pro_access(
        user_id: str,
        token: str | None = Query(None),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ):
        """Remove manual Pro access for a user through the admin surface."""
        actor = _actor_from_request(token, authorization, admin_session)
        return admin_revoke_pro_access_response(
            user_id,
            users_lock_file=runtime_users_lock_file_fn(),
            load_users=load_users_fn,
            save_users=save_users_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            build_entitlements_response=build_entitlements_response_fn,
            admin_uid=actor,
        )

    def admin_run_tests(req: AdminTestRunRequest | None = None):
        """Run test suite and return matrix view data."""
        return admin_run_tests_response(
            req=req,
            run_pytest_matrix=run_pytest_matrix,
            store_last_test_run=store_last_test_run,
        )

    def admin_last_test_run():
        """Get latest test run result for matrix page."""
        return admin_last_test_run_response(
            get_last_test_run=get_last_test_run,
        )

    def admin_test_catalog():
        """Return clickable test-matrix catalog."""
        return admin_test_catalog_response(
            build_test_catalog=build_test_catalog,
        )

    def admin_tests_ui():
        """Minimal grayscale test matrix dashboard."""
        return admin_tests_ui_response(
            admin_tests_html=ADMIN_TESTS_HTML,
            admin_token=runtime_settings_fn().admin_token,
        )

    def _safe_user_dir(uid: str) -> Path:
        """Resolve user directory, rejecting path traversal."""
        users_root = runtime_settings_fn().data_dir / "users"
        user_dir = (users_root / uid).resolve()
        if not str(user_dir).startswith(str(users_root.resolve())):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid user_id")
        return user_dir

    def admin_graph_density(user_id: str, notebook_id: str = "default"):
        """Return time-series graph density data for a user."""
        from .admin_graph_density import compute_graph_density
        return compute_graph_density(_safe_user_dir(user_id), notebook_id, user_id=user_id)

    def admin_graph_playback(user_id: str, notebook_id: str = "default"):
        """Return full graph nodes + edges with timestamps for playback."""
        from .admin_graph_playback import compute_graph_playback
        return compute_graph_playback(_safe_user_dir(user_id), notebook_id, user_id=user_id)

    def admin_pipeline_runs(user_id: str, limit: int = 20):
        """Return pipeline run history for a user."""
        from .pipeline_log import get_runs
        return {"user_id": user_id, "runs": get_runs(user_id, limit=min(limit, 100))}

    def admin_judge_stats(user_id: str):
        """Return per-user judge acceptance stats."""
        from .judge_log import get_acceptance_stats
        return get_acceptance_stats(user_id=user_id)

    def admin_translate_history(
        user_id: str,
        limit: int = 50,
        q: str | None = None,
        op: str | None = None,
    ):
        """Return translate/explain call history for a user, with optional search/filter.

        Query params:
          - ``q``: case-insensitive substring filter over word/context.
          - ``op``: exact operation filter (``translate_quick`` /
            ``translate_phrase`` / ``translate_explain``).
        """
        from .translate_log import get_log
        return {
            "user_id": user_id,
            "history": get_log(user_id, limit=min(limit, 200), q=q, op=op),
            "q": q or "",
            "op": op or "",
        }

    def admin_user_activity(user_id: str, hours: int = 24):
        """Return merged recent-activity timeline (translate + pipeline + judge)."""
        from .admin_user_activity import get_user_activity
        return get_user_activity(user_id, hours=hours)

    def admin_user_usage(user_id: str, range: str = "24h"):
        """Return per-type usage breakdown for a user, filtered by time range."""
        from .admin_handlers import admin_user_usage_response
        return admin_user_usage_response(user_id, range_=range)

    def admin_host_metrics():
        """Return real-time host metrics for admin dashboard."""
        return admin_host_metrics_response()

    def admin_users_search(q: str = "", limit: int = 50):
        """Search users by uid prefix / email substring / display name substring."""
        from .admin_users_search import search_users
        return search_users(load_users_fn(), q=q, limit=limit)

    def admin_observability():
        """Return site-wide aggregated observability metrics (24h / 7d)."""
        from .admin_observability import collect_observability
        return collect_observability()

    def admin_log_retention_run():
        """Manually trigger log-retention pruners across all 4 log DBs."""
        from .log_retention import run_all
        return run_all()

    def admin_audit(since: str | None = None, limit: int = 100):
        """Return recent admin mutation audit log entries."""
        return admin_audit_response(since=since, limit=limit)

    def admin_user_detail_ui():
        """User detail page UI."""
        return admin_ui_response(
            admin_html=ADMIN_USER_DETAIL_HTML,
            admin_token=runtime_settings_fn().admin_token,
        )

    async def admin_orphans_scan():
        """Return a read-only data-consistency scan report.

        ``orphan_scan.scan`` is synchronous + heavy I/O (walks every users/<uid>
        directory, opens 5 SQLite databases, parses ``graph_*.json``). Running
        it directly on the FastAPI event loop blocks every other request for
        the duration of the scan, so we hand it off to a worker thread via
        ``run_in_threadpool``.
        """
        from starlette.concurrency import run_in_threadpool

        from .orphan_scan import scan
        return await run_in_threadpool(
            scan, data_dir=runtime_settings_fn().data_dir
        )

    return {
        "admin_ui": admin_ui,
        "admin_stats": admin_stats,
        "admin_logs": admin_logs,
        "admin_user_entitlement": admin_user_entitlement,
        "admin_grant_pro_access": admin_grant_pro_access,
        "admin_revoke_pro_access": admin_revoke_pro_access,
        "admin_run_tests": admin_run_tests,
        "admin_last_test_run": admin_last_test_run,
        "admin_test_catalog": admin_test_catalog,
        "admin_tests_ui": admin_tests_ui,
        "admin_graph_density": admin_graph_density,
        "admin_graph_playback": admin_graph_playback,
        "admin_pipeline_runs": admin_pipeline_runs,
        "admin_judge_stats": admin_judge_stats,
        "admin_translate_history": admin_translate_history,
        "admin_user_activity": admin_user_activity,
        "admin_user_usage": admin_user_usage,
        "admin_host_metrics": admin_host_metrics,
        "admin_users_search": admin_users_search,
        "admin_observability": admin_observability,
        "admin_log_retention_run": admin_log_retention_run,
        "admin_audit": admin_audit,
        "admin_user_detail_ui": admin_user_detail_ui,
        "admin_orphans_scan": admin_orphans_scan,
    }
