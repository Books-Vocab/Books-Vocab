"""Close-wave anchor identity, exact-path commit, and recovery helpers."""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import io
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted delivery functions."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]


def _delivery_anchor_commit(
    primary: Path,
    *,
    applied_ids: list[str],
    already_committed: bool = False,
    anchor_base_sha: str | None = None,
    already_committed_sha: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Commit only the closure rows materialized by ``anchor``.

    ``backlog.py anchor`` intentionally writes data but does not invent a git
    commit.  The coordinator is the owner of the wave's one metadata commit.  The
    path check is the safety boundary: a concurrent edit in primary must never be
    swept into this automatic commit.
    """
    expected_paths: set[str] = set()
    for ticket_id in applied_ids:
        if not isinstance(ticket_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id):
            return EXIT_BLOCK, {
                "error": "anchor receipt contains an unsafe ticket id",
                "ticket_id": ticket_id,
            }
        expected_paths.add(f"docs/runbook/backlog/{ticket_id}.json")

    rc, changed = _git(["diff", "--name-only", "HEAD", "--"], cwd=primary)
    if rc != EXIT_OK:
        return EXIT_BLOCK, {"error": f"cannot inspect anchor diff: {changed}"}
    untracked_rc, untracked = _git(
        ["ls-files", "--others", "--exclude-standard", "--"], cwd=primary
    )
    if untracked_rc != EXIT_OK:
        return EXIT_BLOCK, {"error": f"cannot inspect untracked files: {untracked}"}
    paths = {
        line for line in (changed + "\n" + untracked).splitlines() if line
    }
    if not paths and expected_paths and already_committed:
        recovered_sha = _delivery_anchor_identity(
            primary, expected_paths, base_sha=anchor_base_sha,
            expected_sha=already_committed_sha,
        )
        if recovered_sha is None:
            recovered_sha = _delivery_anchor_history_identity(
                primary, expected_paths, base_sha=anchor_base_sha,
                expected_sha=already_committed_sha,
            )
        if recovered_sha is None:
            return EXIT_BLOCK, {
                "error": "anchor manifest claimed a committed anchor, but primary "
                         "does not contain that exact commit",
                "expected_sha": already_committed_sha,
                "anchor_base_sha": anchor_base_sha,
                "expected_paths": sorted(expected_paths),
                "paths": [],
            }
        return EXIT_OK, {
            "committed": False,
            "already_committed": True,
            "recovered": False,
            "paths": [],
            "sha": recovered_sha,
        }
    if not paths and expected_paths:
        recovered_sha = _delivery_anchor_identity(
            primary, expected_paths, base_sha=anchor_base_sha,
        )
        if recovered_sha is None and already_committed_sha:
            recovered_sha = _delivery_anchor_history_identity(
                primary, expected_paths, base_sha=anchor_base_sha,
                expected_sha=already_committed_sha,
            )
        if recovered_sha is not None:
            return EXIT_OK, {
                "committed": False,
                "already_committed": True,
                "recovered": True,
                "paths": [],
                "sha": recovered_sha,
            }
        return EXIT_BLOCK, {
            "error": "anchor receipt declared applied tickets but primary has no changes",
            "missing_paths": sorted(expected_paths),
            "paths": [],
        }
    if not paths:
        return EXIT_OK, {"committed": False, "noop": True, "paths": []}
    outside = sorted(paths - expected_paths)
    missing = sorted(expected_paths - paths)
    if outside or missing:
        return EXIT_BLOCK, {
            "error": "primary changed paths do not exactly match the anchor receipt; "
                     "refusing to commit another session's work",
            "outside_paths": outside,
            "missing_paths": missing,
            "paths": sorted(paths),
            "expected_paths": sorted(expected_paths),
        }
    add_rc, add_output = _git_mutation(
        ["add", "--", *sorted(expected_paths)],
        cwd=primary,
        label="delivery-anchor-stage",
    )
    if add_rc != EXIT_OK:
        return EXIT_BLOCK, {"error": f"could not stage anchor output: {add_output}"}
    commit_rc, commit_output = _git_mutation(
        [
            "commit",
            "-m",
            _DELIVERY_ANCHOR_SUBJECT,
        ],
        cwd=primary,
        label="delivery-anchor-commit",
    )
    if commit_rc != EXIT_OK:
        return EXIT_BLOCK, {
            "error": f"could not commit anchor output: {commit_output}",
            "paths": sorted(paths),
        }
    tip_rc, tip = _git(["rev-parse", "HEAD"], cwd=primary)
    return (EXIT_OK if tip_rc == EXIT_OK else EXIT_BLOCK), {
        "committed": True,
        "paths": sorted(paths),
        "sha": tip if tip_rc == EXIT_OK else None,
        "output": commit_output[-2000:],
    }


def _delivery_anchor_and_commit(
    args: argparse.Namespace, primary: Path, allowed: set[str], slug: str,
    manifest_path: Path | None,
) -> tuple[int, list[dict[str, Any]]]:
    """Linearize the primary-side anchor and its exact-path metadata commit."""
    steps: list[dict[str, Any]] = []
    with _main_advance_lock(primary):
        dirty_recovery_allowed = _delivery_anchor_recovery_dirty_allowed(
            primary, manifest_path,
        )
        ff_refusal = _primary_ff_ready(
            primary,
            _delivery_operation_base(getattr(args, "base", "main")),
            branch=f"close-wave:{slug}",
            worktree=str(primary),
            allow_dirty=dirty_recovery_allowed,
        )
        if ff_refusal is not None:
            reason, extra = ff_refusal
            steps.append({"name": "anchor-guard", "error": reason, **extra})
            return EXIT_BLOCK, steps
        dirty = _delivery_primary_dirty(primary)
        if dirty and not dirty_recovery_allowed:
            steps.append({
                "name": "anchor-guard",
                "error": "primary became dirty before anchor",
                "dirty_files": dirty,
            })
            return EXIT_BLOCK, steps
        rrc, records = _delivery_registry_records(args, primary=primary)
        if rrc != EXIT_OK:
            steps.append({"name": "anchor-guard", "rc": rrc,
                          "error": "could not read the worktree registry"})
            return EXIT_BLOCK, steps
        # Other Delivery Teams may still have active child/integration worktrees.
        # The finalization lock serializes their primary side effects, while this
        # wave only resolves the explicit branches in `allowed` below.

        persisted: dict[str, Any] | None = None
        marker: dict[str, Any] = {}
        saved_ids: list[str] = []
        already_committed = False
        already_committed_sha: str | None = None
        anchor_base_sha_rc, current_head = _git(["rev-parse", "HEAD"], cwd=primary)
        if anchor_base_sha_rc != EXIT_OK or not current_head:
            steps.append({"name": "anchor-guard",
                          "error": "could not capture primary HEAD before anchor"})
            return EXIT_BLOCK, steps
        anchor_base_sha = current_head
        if manifest_path is not None:
            persisted = _delivery_load_json(manifest_path)
            if persisted is None:
                steps.append({"name": "anchor-guard",
                              "error": "integration manifest disappeared before anchor receipt was saved"})
                return EXIT_BLOCK, steps
            raw_marker = persisted.get("close_wave")
            if raw_marker is not None and not isinstance(raw_marker, dict):
                steps.append({"name": "anchor-guard",
                              "error": "integration manifest has malformed close_wave marker"})
                return EXIT_BLOCK, steps
            marker = dict(raw_marker or {})
            stored_base = marker.get("anchor_base_sha")
            if stored_base is not None:
                if not isinstance(stored_base, str) or not stored_base:
                    steps.append({"name": "anchor-guard",
                                  "error": "integration manifest has malformed anchor_base_sha"})
                    return EXIT_BLOCK, steps
                anchor_base_sha = stored_base
            raw_ids = marker.get("anchor_ids")
            if raw_ids is not None:
                if not isinstance(raw_ids, list) or any(
                    not isinstance(ticket_id, str) for ticket_id in raw_ids
                ):
                    steps.append({"name": "anchor-guard",
                                  "error": "integration manifest has malformed anchor_ids"})
                    return EXIT_BLOCK, steps
                saved_ids = list(raw_ids)
            already_committed = marker.get("anchor_committed") is True
            if (stored_base is not None and stored_base != current_head
                    and not already_committed):
                phase_marker = marker.get("phases")
                anchor_phase = (phase_marker.get("anchor")
                                if isinstance(phase_marker, dict) else None)
                recovery_ids = list(saved_ids)
                if (not recovery_ids and isinstance(anchor_phase, dict)):
                    phase_ids = anchor_phase.get("applied_ticket_ids")
                    if ("applied_ticket_ids" in anchor_phase
                            and (not isinstance(phase_ids, list)
                                 or any(not isinstance(ticket_id, str)
                                        for ticket_id in phase_ids))):
                        steps.append({
                            "name": "anchor-guard",
                            "error": "integration manifest has malformed recovery ticket ids",
                            "field": "phases.anchor.applied_ticket_ids",
                        })
                        return EXIT_BLOCK, steps
                    if isinstance(phase_ids, list) and phase_ids:
                        recovery_ids = list(phase_ids)
                    elif anchor_phase.get("status") in {"started", "blocked"}:
                        expected_ids = marker.get("expected_ticket_ids", [])
                        if (not isinstance(expected_ids, list)
                                or any(not isinstance(ticket_id, str)
                                       for ticket_id in expected_ids)):
                            steps.append({
                                "name": "anchor-guard",
                                "error": "integration manifest has malformed recovery ticket ids",
                                "field": "close_wave.expected_ticket_ids",
                            })
                            return EXIT_BLOCK, steps
                        recovery_ids = list(expected_ids)
                if any(not isinstance(ticket_id, str) for ticket_id in recovery_ids):
                    steps.append({
                        "name": "anchor-guard",
                        "error": "integration manifest has malformed recovery ticket ids",
                        "field": "close_wave.recovery_ids",
                    })
                    return EXIT_BLOCK, steps
                recovery_paths = {
                    f"docs/runbook/backlog/{ticket_id}.json"
                    for ticket_id in recovery_ids
                    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
                }
                recovered_sha = (
                    _delivery_anchor_history_identity(
                        primary, recovery_paths, base_sha=stored_base,
                    ) if recovery_paths else None
                )
                if recovered_sha is not None:
                    saved_ids = recovery_ids
                    already_committed_sha = recovered_sha
                elif (
                    _delivery_anchor_noop_recovery_is_safe(
                        primary, marker, stored_base=stored_base,
                        current_head=current_head,
                    )
                    or _delivery_anchor_recovery_is_safe(primary, marker)
                    or dirty_recovery_allowed
                ):
                    # The old anchor phase is durable, but its queue rows prove
                    # that no metadata was consumed.  For a completed noop,
                    # the metadata-only descendant proof above is the durable
                    # identity; for an interrupted real anchor the queue proof
                    # remains the identity. Rebase idempotently either way.
                    anchor_base_sha = current_head
                else:
                    steps.append({
                        "name": "anchor-guard",
                        "error": "primary moved after the persisted anchor base and "
                                 "does not contain the exact recoverable anchor commit",
                        "anchor_base_sha": stored_base,
                        "current_head": current_head,
                    })
                    return EXIT_BLOCK, steps
            raw_commit_sha = marker.get("anchor_commit_sha")
            if raw_commit_sha is not None:
                if not isinstance(raw_commit_sha, str) or not raw_commit_sha:
                    steps.append({"name": "anchor-guard",
                                  "error": "integration manifest has malformed anchor_commit_sha"})
                    return EXIT_BLOCK, steps
                already_committed_sha = raw_commit_sha
            if already_committed and already_committed_sha is None:
                steps.append({"name": "anchor-guard",
                              "error": "committed anchor marker has no anchor_commit_sha"})
                return EXIT_BLOCK, steps
            marker = _delivery_update_phase_marker(
                marker, "anchor", status="started",
                operation_base=anchor_base_sha, landed_sha=current_head,
                expected_ticket_ids=marker.get("expected_ticket_ids", []),
                applied_ticket_ids=saved_ids, queue_state="pending",
            )
            persisted["close_wave"] = {
                **marker,
                "anchor_base_sha": anchor_base_sha,
                "anchor_ids": saved_ids,
                "anchor_committed": already_committed,
            }
            try:
                _integrate_save(manifest_path, persisted)
            except OSError as exc:
                steps.append({"name": "anchor-guard",
                              "error": f"could not persist anchor base before anchor: {exc}"})
                return EXIT_BLOCK, steps

        anchor_rc, anchor_payload = _delivery_json_tool(
            primary / "ops" / "backlog.py",
            primary,
            [
                "anchor", "--store", str(primary / "docs" / "runbook" / "backlog"),
                "--queue", str(_anchor_queue(primary)),
                "--branches", *sorted(allowed), "--commit",
            ],
            label=f"anchor:{slug}",
            expected_schema="kg.backlog.anchor.v1",
            required_keys=("applied", "problems"),
            receipt_validator=_delivery_require_anchor_receipt,
        )
        steps.append({"name": "anchor", "rc": anchor_rc, "payload": anchor_payload})
        applied = anchor_payload.get("applied")
        if anchor_rc != EXIT_OK or anchor_payload.get("problems"):
            return anchor_rc or EXIT_BLOCK, steps
        if not isinstance(applied, list) or any(
            not isinstance(ticket_id, str) for ticket_id in applied
        ):
            steps.append({"name": "anchor-guard",
                          "error": "anchor receipt has malformed applied ids"})
            return EXIT_BLOCK, steps
        if saved_ids and applied and list(applied) != saved_ids:
            steps.append({"name": "anchor-guard",
                          "error": "anchor receipt disagrees with persisted anchor_ids",
                          "persisted_anchor_ids": saved_ids,
                          "receipt_anchor_ids": applied})
            return EXIT_BLOCK, steps
        if not applied and saved_ids:
            applied = list(saved_ids)
        if not applied and manifest_path is not None:
            # A child may have written every expected ticket and drained the queue
            # before its process died, so the retry's anchor receipt legitimately
            # has no applied list.  Only recover that narrow state when the phase
            # is durable, the queue is empty, and the tracked dirty set is exactly
            # the persisted expected ticket documents.
            recovery_marker = persisted.get("close_wave") if persisted else None
            recovery_phase = (
                recovery_marker.get("phases", {}).get("anchor")
                if isinstance(recovery_marker, dict)
                and isinstance(recovery_marker.get("phases"), dict)
                else None
            )
            expected_recovery = (
                recovery_marker.get("expected_ticket_ids", [])
                if isinstance(recovery_marker, dict) else []
            )
            expected_recovery_paths = {
                f"docs/runbook/backlog/{ticket_id}.json"
                for ticket_id in expected_recovery
                if isinstance(ticket_id, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
            }
            dirty_recovery_paths = set(_porcelain_paths(
                "\n".join(_delivery_primary_dirty(primary))
            ))
            if (
                isinstance(recovery_phase, dict)
                and recovery_phase.get("status") in {"started", "blocked"}
                and not recovery_phase.get("applied_ticket_ids")
                and expected_recovery
                and len(expected_recovery_paths) == len(expected_recovery)
                and not _read_anchor_queue(primary)
                and dirty_recovery_paths == expected_recovery_paths
            ):
                applied = list(expected_recovery)
        if manifest_path is not None:
            marker = _delivery_update_phase_marker(
                persisted.get("close_wave"), "anchor", status="started",
                operation_base=anchor_base_sha, landed_sha=anchor_base_sha,
                expected_ticket_ids=(persisted.get("close_wave") or {}).get(
                    "expected_ticket_ids", []),
                applied_ticket_ids=applied,
                acceptance_receipt=anchor_payload,
                queue_state="consumed" if applied else "pending",
            )
            persisted["close_wave"] = {
                **marker,
                "anchor_base_sha": anchor_base_sha,
                "anchor_ids": applied,
                "anchor_committed": already_committed,
            }
            try:
                _integrate_save(manifest_path, persisted)
            except OSError as exc:
                steps.append({"name": "anchor-guard",
                              "error": f"could not persist anchor receipt: {exc}"})
                return EXIT_BLOCK, steps

        anchor_commit_rc, anchor_commit = _delivery_anchor_commit(
            primary,
            applied_ids=applied,
            already_committed=already_committed,
            anchor_base_sha=anchor_base_sha,
            already_committed_sha=already_committed_sha,
        )
        steps.append({"name": "anchor-commit", "rc": anchor_commit_rc,
                      "payload": anchor_commit})
        if anchor_commit_rc == EXIT_OK and manifest_path is not None:
            committed_sha = anchor_commit.get("sha")
            if applied and (not isinstance(committed_sha, str) or not committed_sha):
                steps.append({"name": "anchor-guard",
                              "error": "anchor commit succeeded without an identifiable commit sha"})
                return EXIT_BLOCK, steps
            persisted = _delivery_load_json(manifest_path)
            if persisted is None:
                steps.append({"name": "anchor-guard",
                              "error": "integration manifest disappeared after anchor commit"})
                return EXIT_BLOCK, steps
            marker = _delivery_update_phase_marker(
                persisted.get("close_wave"), "anchor", status="completed",
                operation_base=anchor_base_sha, landed_sha=committed_sha,
                expected_ticket_ids=(persisted.get("close_wave") or {}).get(
                    "expected_ticket_ids", []),
                applied_ticket_ids=applied,
                acceptance_receipt=anchor_payload,
                queue_state="consumed", anchor_commit=committed_sha,
            )
            close_wave = {
                **marker,
                "anchor_base_sha": anchor_base_sha,
                "anchor_ids": applied,
                "anchor_committed": bool(applied),
                **({"anchor_commit_sha": committed_sha}
                   if isinstance(committed_sha, str) and committed_sha else {}),
            }
            if not applied and anchor_commit.get("noop") is True:
                close_wave["anchor_noop"] = True
                close_wave.pop("anchor_commit_sha", None)
            elif applied:
                close_wave.pop("anchor_noop", None)
            persisted["close_wave"] = close_wave
            try:
                _integrate_save(manifest_path, persisted)
            except OSError as exc:
                steps.append({"name": "anchor-guard",
                              "error": f"could not persist committed anchor receipt: {exc}"})
                return EXIT_BLOCK, steps
        return anchor_commit_rc, steps

