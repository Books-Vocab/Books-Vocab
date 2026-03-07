from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAST_TEST_RUN: dict[str, Any] | None = None
CASE_LINE_RE = re.compile(
    r"^(?P<case>tests/\S+::\S+)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAILED|XPASSED)\b"
)
TEST_MATRIX_COLUMNS = ["Unit", "Integration", "Robustness", "Contract"]
TEST_MATRIX_ITEMS: list[dict[str, Any]] = [
    {
        "id": "renderer_truncation",
        "domain": "Rendering",
        "column": "Unit",
        "label": "Renderer Truncation",
        "summary": "Fast renderer-only check for text truncation behavior.",
        "nodeids": ["tests/test_renderer_truncation.py"],
    },
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
        "label": "Mochi + CardStore Atomicity",
        "summary": "Protects atomic writes, counts, and migration behavior for stored data.",
        "nodeids": [
            "tests/test_robustness.py::TestBatchB_MochiAtomicStorage",
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


def bucket_status(status: str) -> str:
    s = status.upper()
    if s in {"FAILED", "XPASSED"}:
        return "failed"
    if s == "ERROR":
        return "errors"
    if s in {"SKIPPED", "XFAILED"}:
        return "skipped"
    return "passed"


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


def item_results(cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_item: list[dict[str, Any]] = []
    for item in TEST_MATRIX_ITEMS:
        matched = [c for c in cases if any(c["id"].startswith(prefix) for prefix in item["nodeids"])]
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for c in matched:
            counts[c["bucket"]] += 1
        if not matched:
            status = "not_run"
        elif counts["failed"] > 0 or counts["errors"] > 0:
            status = "failed"
        elif counts["passed"] > 0:
            status = "passed"
        else:
            status = "skipped"
        by_item.append({
            "id": item["id"],
            "status": status,
            "counts": counts,
            "total": len(matched),
        })
    return by_item


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


def run_pytest_matrix(selected_items: list[str] | None = None) -> dict[str, Any]:
    """Run pytest and build matrix data grouped by test module."""
    project_root = Path(__file__).resolve().parent.parent.parent
    started = datetime.now(tz=timezone.utc)
    run_id = started.strftime("%Y%m%d%H%M%S")
    tests_dir = project_root / "tests"
    selected_items = selected_items or []
    nodeids = selected_nodeids(selected_items)

    if not tests_dir.exists():
        finished = datetime.now(tz=timezone.utc)
        return {
            "runId": run_id,
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
            "durationSeconds": round((finished - started).total_seconds(), 3),
            "returnCode": 127,
            "outcome": "failed",
            "totals": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0, "total": 1},
            "matrix": [],
            "cases": [],
            "selectedItems": selected_items,
            "itemResults": item_results([]),
            "stdoutTail": [],
            "stderrTail": [f"tests directory not found at {tests_dir}"],
        }

    cmd = [sys.executable, "-m", "pytest", "-vv", "--maxfail=0", "--disable-warnings"]
    if nodeids:
        cmd.extend(nodeids)
    else:
        cmd.append("tests")

    try:
        proc = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "PY_COLORS": "0"},
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return_code = 124
    except Exception as exc:
        finished = datetime.now(tz=timezone.utc)
        return {
            "runId": run_id,
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
            "durationSeconds": round((finished - started).total_seconds(), 3),
            "returnCode": 127,
            "outcome": "failed",
            "totals": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0, "total": 1},
            "matrix": [],
            "cases": [],
            "selectedItems": selected_items,
            "itemResults": item_results([]),
            "stdoutTail": [],
            "stderrTail": [f"{type(exc).__name__}: {exc}"],
        }

    finished = datetime.now(tz=timezone.utc)
    duration = round((finished - started).total_seconds(), 3)

    cases: list[dict[str, str]] = []
    matrix: dict[str, dict[str, Any]] = {}
    for line in (stdout + "\n" + stderr).splitlines():
        match = CASE_LINE_RE.match(line.strip())
        if not match:
            continue
        case_id = match.group("case")
        status = match.group("status")
        module = case_id.split("::", 1)[0]
        bucket = bucket_status(status)
        cases.append({
            "id": case_id,
            "module": module,
            "status": status,
            "bucket": bucket,
        })
        if module not in matrix:
            matrix[module] = {
                "module": module,
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "total": 0,
            }
        matrix[module][bucket] += 1
        matrix[module]["total"] += 1

    matrix_rows = sorted(matrix.values(), key=lambda row: row["module"])
    totals = {
        "passed": sum(row["passed"] for row in matrix_rows),
        "failed": sum(row["failed"] for row in matrix_rows),
        "errors": sum(row["errors"] for row in matrix_rows),
        "skipped": sum(row["skipped"] for row in matrix_rows),
    }
    totals["total"] = totals["passed"] + totals["failed"] + totals["errors"] + totals["skipped"]

    outcome = "passed" if return_code == 0 else "failed"
    return {
        "runId": run_id,
        "startedAt": started.isoformat(),
        "finishedAt": finished.isoformat(),
        "durationSeconds": duration,
        "returnCode": return_code,
        "outcome": outcome,
        "totals": totals,
        "selectedItems": selected_items,
        "matrix": matrix_rows,
        "cases": cases,
        "itemResults": item_results(cases),
        "stdoutTail": (stdout.splitlines()[-60:] if stdout else []),
        "stderrTail": (stderr.splitlines()[-60:] if stderr else []),
    }


def store_last_test_run(result: dict[str, Any]) -> dict[str, Any]:
    global LAST_TEST_RUN
    LAST_TEST_RUN = result
    return result


def get_last_test_run() -> dict[str, Any] | None:
    return LAST_TEST_RUN
