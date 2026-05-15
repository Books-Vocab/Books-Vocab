"""Admin test-matrix handlers — run pytest matrix, fetch results, render UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.responses import HTMLResponse

from .auth import _set_admin_cookie


def admin_run_tests_response(
    *,
    req: Any,
    run_pytest_matrix: Callable[..., dict[str, Any]],
    store_last_test_run: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    selected = req.itemIds if req else []
    return store_last_test_run(run_pytest_matrix(selected_items=selected))


def admin_last_test_run_response(
    *,
    get_last_test_run: Callable[[], dict[str, Any] | None],
) -> dict[str, Any]:
    last_run = get_last_test_run()
    if last_run is None:
        return {"status": "idle"}
    return last_run


def admin_test_catalog_response(
    *,
    build_test_catalog: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    return build_test_catalog()


def admin_tests_ui_response(
    *,
    admin_token: str,
    admin_tests_html: str,
) -> HTMLResponse:
    return _set_admin_cookie(HTMLResponse(admin_tests_html), admin_token)
