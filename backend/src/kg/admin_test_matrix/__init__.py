"""Admin test-matrix package.

Re-exports the public API so callers can keep importing from
``kg.admin_test_matrix`` unchanged after the module-to-package split.

``LAST_TEST_RUN`` and its accessors live here directly (not in a submodule)
so external code that mutates ``kg.admin_test_matrix.LAST_TEST_RUN`` shares
the same binding observed by ``get_last_test_run``/``store_last_test_run``.
"""

from __future__ import annotations

from typing import Any

from .catalog import (
    TEST_MATRIX_COLUMNS,
    TEST_MATRIX_ITEM_MAP,
    TEST_MATRIX_ITEMS,
    build_test_catalog,
    selected_nodeids,
)
from .results import bucket_status, item_results
from .runner import CASE_LINE_RE, run_pytest_matrix

LAST_TEST_RUN: dict[str, Any] | None = None


def store_last_test_run(result: dict[str, Any]) -> dict[str, Any]:
    global LAST_TEST_RUN
    LAST_TEST_RUN = result
    return result


def get_last_test_run() -> dict[str, Any] | None:
    return LAST_TEST_RUN


__all__ = [
    "CASE_LINE_RE",
    "LAST_TEST_RUN",
    "TEST_MATRIX_COLUMNS",
    "TEST_MATRIX_ITEM_MAP",
    "TEST_MATRIX_ITEMS",
    "bucket_status",
    "build_test_catalog",
    "get_last_test_run",
    "item_results",
    "run_pytest_matrix",
    "selected_nodeids",
    "store_last_test_run",
]
