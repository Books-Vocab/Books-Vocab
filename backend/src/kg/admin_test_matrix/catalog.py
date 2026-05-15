from __future__ import annotations

from typing import Any

TEST_MATRIX_COLUMNS = ["Unit", "Integration", "Robustness", "Contract"]
TEST_MATRIX_ITEMS: list[dict[str, Any]] = [
    {
        "id": "vocab_graph",
        "domain": "Vocab/Graph",
        "column": "Integration",
        "label": "Vocab + Graph API",
        "summary": "Covers vocab lifecycle sync and graph-link API behavior together.",
        "nodeids": [
            "tests/test_api_surface.py::test_vocab_lifecycle_and_since_sync",
            "tests/test_api_surface.py::test_graph_links_returns_active_only",
        ],
    },
    {
        "id": "translate_contract",
        "domain": "Vocab/Graph",
        "column": "Contract",
        "label": "Translate API Contract",
        "summary": "Checks response shape and error handling for translate endpoints.",
        "nodeids": ["tests/test_api_surface.py::test_translate_endpoints_success_and_error"],
    },
    {
        "id": "auth_linking",
        "domain": "User/Auth",
        "column": "Integration",
        "label": "Auth Linking",
        "summary": "Validates Google and Apple identity linking on the same user.",
        "nodeids": ["tests/test_api_surface.py::test_auth_verify_links_google_and_apple_by_email"],
    },
    {
        "id": "account_robustness",
        "domain": "User/Auth",
        "column": "Robustness",
        "label": "Config + Account Robustness",
        "summary": "Stresses config persistence, account deletion, and integrity behavior.",
        "nodeids": [
            "tests/test_robustness.py::TestBatchA_UsersJsonLock",
            "tests/test_robustness.py::TestBatchA_AccountDeletion",
        ],
    },
    {
        "id": "storage_backfill",
        "domain": "Storage",
        "column": "Integration",
        "label": "Embedding Backfill",
        "summary": "Verifies cards without embeddings are detected and backfilled correctly.",
        "nodeids": ["tests/test_robustness.py::TestBatchC_EmbeddingBackfill"],
    },
    {
        "id": "storage_atomicity",
        "domain": "Storage",
        "column": "Robustness",
        "label": "CardStore Atomicity",
        "summary": "Protects atomic writes, counts, and migration behavior for stored data.",
        "nodeids": [
            "tests/test_robustness.py::TestBatchC_CardStoreCount",
        ],
    },
    {
        "id": "pipeline_locking",
        "domain": "Pipeline",
        "column": "Robustness",
        "label": "Pipeline Locking",
        "summary": "Checks per-user lock creation and skip behavior under contention.",
        "nodeids": ["tests/test_robustness.py::TestBatchD_UserLockAtomic"],
    },
    {
        "id": "admin_contract",
        "domain": "Admin",
        "column": "Contract",
        "label": "Admin Endpoints",
        "summary": "Confirms admin token enforcement and test-matrix APIs stay intact.",
        "nodeids": [
            "tests/test_api_surface.py::test_admin_endpoints_enforce_token_and_return_stats",
            "tests/test_api_surface.py::test_admin_test_matrix_endpoints",
        ],
    },
    {
        "id": "auth_contract",
        "domain": "User/Auth",
        "column": "Contract",
        "label": "Auth API Contract",
        "summary": "Checks auth verify payload shape and revoked-token rejection behavior.",
        "nodeids": [
            "tests/test_api_surface.py::test_auth_verify_response_contract",
            "tests/test_api_surface.py::test_revoked_token_rejected",
        ],
    },
    {
        "id": "vocab_concurrent",
        "domain": "Vocab/Graph",
        "column": "Robustness",
        "label": "Vocab Concurrent Write",
        "summary": "Stresses concurrent vocab writes to catch lost-update issues.",
        "nodeids": ["tests/test_robustness.py::TestBatchE_VocabConcurrentWrite"],
    },
    {
        "id": "pipeline_integration",
        "domain": "Pipeline",
        "column": "Integration",
        "label": "Pipeline Integration",
        "summary": "Runs pipeline flow end-to-end and checks response schema coverage.",
        "nodeids": ["tests/test_pipeline_integration.py::TestPipelineIntegration"],
    },
]
TEST_MATRIX_ITEM_MAP = {item["id"]: item for item in TEST_MATRIX_ITEMS}


def selected_nodeids(item_ids: list[str]) -> list[str]:
    nodeids: list[str] = []
    seen: set[str] = set()
    for item_id in item_ids:
        item = TEST_MATRIX_ITEM_MAP.get(item_id)
        if not item:
            continue
        for nodeid in item["nodeids"]:
            if nodeid not in seen:
                nodeids.append(nodeid)
                seen.add(nodeid)
    return nodeids


def build_test_catalog() -> dict[str, Any]:
    domains = list(dict.fromkeys(item["domain"] for item in TEST_MATRIX_ITEMS))
    rows: list[dict[str, Any]] = []
    for domain in domains:
        row_cells: list[dict[str, Any] | None] = []
        for column in TEST_MATRIX_COLUMNS:
            cell = next(
                (item for item in TEST_MATRIX_ITEMS if item["domain"] == domain and item["column"] == column),
                None,
            )
            row_cells.append(cell)
        rows.append({"domain": domain, "cells": row_cells})
    return {"columns": TEST_MATRIX_COLUMNS, "rows": rows, "items": TEST_MATRIX_ITEMS}
