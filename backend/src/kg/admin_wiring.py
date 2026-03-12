"""Admin route handler wiring — creates admin endpoint functions with injected dependencies."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Header

from .admin_assets import ADMIN_HTML, ADMIN_TESTS_HTML
from .admin_handlers import (
    admin_grant_pro_access_response,
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

    def admin_ui(token: str | None = None, authorization: str | None = Header(None)):
        """Admin dashboard UI."""
        return admin_ui_response(
            token,
            admin_token=runtime_settings_fn().admin_token,
            admin_html=ADMIN_HTML,
            authorization=authorization,
        )

    def admin_stats(token: str | None = None, authorization: str | None = Header(None)):
        """Return per-user token + vocab stats for admin dashboard."""
        from .token_tracker import get_all_stats

        settings = runtime_settings_fn()
        return admin_stats_response(
            token,
            admin_token=settings.admin_token,
            load_users=load_users_fn,
            get_all_stats=get_all_stats,
            build_entitlements_response=build_entitlements_response_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            data_dir=settings.data_dir,
            card_store_factory=card_store_factory,
            authorization=authorization,
            jwt_secret=settings.jwt_secret,
        )

    def admin_logs(token: str | None = None, n: int = 200, level: str | None = None, authorization: str | None = Header(None)):
        """Return recent in-memory log entries for the admin dashboard."""
        return admin_logs_response(
            token,
            admin_token=runtime_settings_fn().admin_token,
            log_getter=mem_log_getter,
            n=n,
            level=level,
            authorization=authorization,
        )

    def admin_user_entitlement(user_id: str, token: str | None = None, authorization: str | None = Header(None)):
        """Return one user's computed Pro entitlement plus raw admin grant metadata."""
        return admin_user_entitlement_response(
            token,
            user_id,
            admin_token=runtime_settings_fn().admin_token,
            load_users=load_users_fn,
            build_entitlements_response=build_entitlements_response_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            authorization=authorization,
        )

    def admin_grant_pro_access(req: AdminGrantRequest, user_id: str, token: str | None = None, authorization: str | None = Header(None)):
        """Manually grant Pro access for a user through the admin surface."""
        return admin_grant_pro_access_response(
            token,
            user_id,
            req,
            admin_token=runtime_settings_fn().admin_token,
            users_lock_file=runtime_users_lock_file_fn(),
            load_users=load_users_fn,
            save_users=save_users_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            build_entitlements_response=build_entitlements_response_fn,
            authorization=authorization,
        )

    def admin_revoke_pro_access(user_id: str, token: str | None = None, authorization: str | None = Header(None)):
        """Remove manual Pro access for a user through the admin surface."""
        return admin_revoke_pro_access_response(
            token,
            user_id,
            admin_token=runtime_settings_fn().admin_token,
            users_lock_file=runtime_users_lock_file_fn(),
            load_users=load_users_fn,
            save_users=save_users_fn,
            current_admin_grant_record=current_admin_grant_record_fn,
            build_entitlements_response=build_entitlements_response_fn,
            authorization=authorization,
        )

    def admin_run_tests(req: AdminTestRunRequest | None = None, token: str | None = None, authorization: str | None = Header(None)):
        """Run test suite and return matrix view data."""
        return admin_run_tests_response(
            token,
            admin_token=runtime_settings_fn().admin_token,
            req=req,
            run_pytest_matrix=run_pytest_matrix,
            store_last_test_run=store_last_test_run,
            authorization=authorization,
        )

    def admin_last_test_run(token: str | None = None, authorization: str | None = Header(None)):
        """Get latest test run result for matrix page."""
        return admin_last_test_run_response(
            token,
            admin_token=runtime_settings_fn().admin_token,
            get_last_test_run=get_last_test_run,
            authorization=authorization,
        )

    def admin_test_catalog(token: str | None = None, authorization: str | None = Header(None)):
        """Return clickable test-matrix catalog."""
        return admin_test_catalog_response(
            token,
            admin_token=runtime_settings_fn().admin_token,
            build_test_catalog=build_test_catalog,
            authorization=authorization,
        )

    def admin_tests_ui(token: str | None = None, authorization: str | None = Header(None)):
        """Minimal grayscale test matrix dashboard."""
        return admin_tests_ui_response(
            token,
            admin_token=runtime_settings_fn().admin_token,
            admin_tests_html=ADMIN_TESTS_HTML,
            authorization=authorization,
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
    }
