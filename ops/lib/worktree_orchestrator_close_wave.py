"""Close-wave finalization and explicit backup synchronization."""

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


def _delivery_sync_close_wave(
    args: argparse.Namespace,
    primary: Path,
    manifest_path: Path | None,
    steps: list[dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    """Complete the delivery-loop's explicit backup leg.

    The local cutover is develop; this is the separately named backup action.
    Persisting sync_status makes a push failure resumable without repeating Gate,
    cutover, resolve, or anchor.
    """
    if not getattr(args, "sync", False):
        return EXIT_OK, None
    if manifest_path is None:
        steps.append({"name": "sync", "error": "no integration manifest to mark sync"})
        return EXIT_BLOCK, None
    current = _delivery_load_json(manifest_path)
    if current is None:
        steps.append({"name": "sync", "error": "integration manifest disappeared before sync"})
        return EXIT_BLOCK, None
    marker = dict(current.get("close_wave") or {})
    if marker.get("sync_status") == "completed":
        steps.append({"name": "sync", "mode": "already-synced",
                      "sync": marker.get("sync")})
        return EXIT_OK, marker.get("sync")

    head_rc, sync_head = _git(["rev-parse", "HEAD"], cwd=primary)
    if head_rc != EXIT_OK or not sync_head:
        steps.append({"name": "sync", "error": "could not capture primary HEAD before sync"})
        return EXIT_BLOCK, None
    marker = _delivery_update_phase_marker(
        marker, "sync", status="started",
        operation_base=marker.get("operation_base") or marker.get("anchor_base_sha"),
        landed_sha=sync_head,
        expected_ticket_ids=marker.get("expected_ticket_ids", []),
        applied_ticket_ids=marker.get("anchor_ids", []),
        queue_state="consumed",
    )
    current["close_wave"] = marker
    try:
        _integrate_save(manifest_path, current)
    except OSError as exc:
        steps.append({"name": "sync", "error": f"could not persist sync start: {exc}"})
        return EXIT_BLOCK, None

    # Sync runs after cutover, so the stable primary copy is now the coordinator
    # version that produced the fresh Gate.  The caller's source worktree may have
    # been resolved and removed by this point; resolving `__file__` here would make
    # a successful local landing crash before its backup receipt is written.
    orchestrator = primary / "ops" / "worktree_orchestrate.py"
    sync_rc, sync_payload = _delivery_json_tool(
        orchestrator,
        primary,
        ["sync", "--commit", *_state_arg(args.state)],
        label=f"sync:{args.slug}",
        expected_schema=SCHEMA,
        required_keys=("verdict",),
    )
    steps.append({"name": "sync", "rc": sync_rc, "payload": sync_payload})
    if sync_rc != EXIT_OK or sync_payload.get("verdict") not in ("pushed", "noop"):
        return sync_rc or EXIT_BLOCK, sync_payload

    current = _delivery_load_json(manifest_path)
    if current is None:
        steps.append({"name": "sync", "error": "integration manifest disappeared after sync"})
        return EXIT_BLOCK, sync_payload
    current["close_wave"] = {
        **_delivery_update_phase_marker(
            current.get("close_wave"), "sync", status="completed",
            operation_base=(current.get("close_wave") or {}).get("operation_base")
            or (current.get("close_wave") or {}).get("anchor_base_sha"),
            landed_sha=sync_payload.get("to"),
            expected_ticket_ids=(current.get("close_wave") or {}).get(
                "expected_ticket_ids", []),
            applied_ticket_ids=(current.get("close_wave") or {}).get("anchor_ids", []),
            acceptance_receipt=sync_payload, queue_state="consumed",
        ),
        "sync_status": "completed",
        "sync": sync_payload,
    }
    try:
        _integrate_save(manifest_path, current)
    except OSError as exc:
        steps.append({"name": "sync",
                      "error": f"sync succeeded but receipt could not be saved: {exc}"})
        return EXIT_BLOCK, sync_payload
    return EXIT_OK, sync_payload


def cmd_close_wave(args: argparse.Namespace) -> int:
    """Run one end-to-end Delivery Team closure under the shared finalization lock."""
    if not getattr(args, "commit", False):
        return _cmd_close_wave_impl(args)
    with _delivery_loop_lock(primary_root()):
        return _cmd_close_wave_impl(args)


def _cmd_close_wave_impl(args: argparse.Namespace) -> int:
    """Run the Delivery Team's complete, resumable batch closure.

    Workers still stop at commit + hand-back. This verb belongs to the Delivery
    Team master/integrator and continues through primary cutover. With --sync it
    also mirrors the landed primary tip to origin/main. Other teams' worktrees
    are allowed to remain active: every teardown target is still an explicit
    source branch or this round's integration branch, and the finalization lock
    serializes the shared primary/remote side effects.
    """
    if not SLUG_RE.match(args.slug or ""):
        _emit({
            "schema": DELIVERY_SCHEMA,
            "step": "close-wave",
            "error": "slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$",
            "slug": args.slug,
        }, args.json, "✗ close-wave refused: invalid slug")
        return EXIT_USAGE
    if args.state:
        # All child verbs must receive the same absolute path even though they run
        # from primary, the integration tree, and source worktrees respectively.
        args.state = str(Path(args.state).expanduser().resolve())
    blocked = _freeze_guard(args.state, "close-wave", args.json)
    if blocked is not None:
        return blocked
    primary = primary_root()
    coordinator_orchestrator = Path(__file__).resolve()
    runner_revision = _delivery_revision(coordinator_orchestrator)
    if getattr(args, "commit", False) and runner_revision is None:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug,
            "runner_revision": None,
            "integration_revision": None,
            "error": "runner_revision is missing",
        }, args.json, "✗ close-wave refused: runner_revision is missing")
        return EXIT_BLOCK
    dirty = _delivery_primary_dirty(primary)
    _, early_manifests = _delivery_state_paths(args)
    early_manifest = early_manifests[0] if early_manifests else None
    if dirty and not _delivery_anchor_recovery_dirty_allowed(primary, early_manifest):
        _emit({
            "schema": DELIVERY_SCHEMA,
            "step": "close-wave",
            "error": "primary is not clean; refusing before touching the wave",
            "dirty_files": dirty,
        }, args.json, "✗ close-wave refused: primary is dirty\n" + "\n".join(
            f"  {path}" for path in dirty
        ))
        return EXIT_BLOCK

    state_path, manifests = _delivery_state_paths(args)
    manifest_path = manifests[0] if manifests else None
    state_exists = state_path.exists()
    manifest_exists = manifest_path is not None and manifest_path.exists()
    integration_state = _delivery_load_json(state_path) if state_exists else None
    manifest = (_delivery_load_json(manifest_path)
                if manifest_exists and manifest_path else None)
    if state_exists and integration_state is None:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error="integration state exists but is unreadable or malformed",
        )
    if manifest_exists and manifest is None:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error="completed integration manifest exists but is unreadable or malformed",
        )

    branches = list(args.branches or [])
    persisted = integration_state or manifest
    requested_independent = bool(getattr(args, "independent", False))
    persisted_independent = (
        isinstance(persisted, dict) and persisted.get("independent") is True
    )
    if persisted is not None and persisted_independent != requested_independent:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug,
            "error": "independent opt-in must match the persisted integration state",
            "persisted_independent": persisted_independent,
            "requested_independent": requested_independent,
        }, args.json,
            "✗ close-wave refused: repeat the original "
            "--independent opt-in exactly")
        return EXIT_USAGE
    if persisted is not None:
        state_branches = persisted.get("branches")
        if not isinstance(state_branches, list) or any(
            not isinstance(branch, str) for branch in state_branches
        ):
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="persisted integration identity has malformed branches",
            )
        state_branches = list(state_branches)
        if branches and branches != state_branches:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "error": "--branches differs from persisted integration state",
                "expected_branches": state_branches, "received_branches": branches,
                "state_file": str(state_path),
                "manifest": str(manifest_path) if manifest_path else None,
            }, args.json,
                "✗ close-wave refused: resume with the original branch list")
            return EXIT_USAGE
        branches = state_branches
    if not branches:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "error": "fresh close-wave needs --branches; an in-flight slug may omit it",
            "slug": args.slug,
        }, args.json, "✗ close-wave: --branches <source-branch ...> is required")
        return EXIT_USAGE

    operation_base = _delivery_operation_base(args.base, manifest=manifest)
    state_identity_error = (_delivery_integration_error(
        integration_state, label="integration state", slug=args.slug,
        base=operation_base, branches=branches, require_gated=False,
        require_live_worktree=True,
    ) if integration_state is not None else None)
    if state_identity_error:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error=state_identity_error,
        )
    manifest_marker = manifest.get("close_wave") if isinstance(manifest, dict) else None
    manifest_delivery_status = (
        manifest_marker.get("status") if isinstance(manifest_marker, dict) else None
    )
    manifest_identity_error = (_delivery_integration_error(
        manifest, label="completed integration manifest", slug=args.slug,
        base=operation_base, branches=branches, require_gated=True,
        require_live_worktree=manifest_delivery_status not in ("validated", "completed"),
    ) if manifest is not None else None)
    if manifest_identity_error:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error=manifest_identity_error,
        )
    if integration_state is not None and manifest is not None:
        for key in ("worktree", "branch"):
            if integration_state.get(key) != manifest.get(key):
                return _delivery_state_error(
                    args=args, state_path=state_path, manifest_path=manifest_path,
                    error=f"integration state and manifest disagree on {key}",
                )
        # integrate writes the manifest before unlinking state.  In that crash
        # window the gated manifest is authoritative; never run Gate twice from
        # the older receipt.
        integration_state = None

    allowed = set(branches)
    if integration_state and integration_state.get("branch"):
        allowed.add(str(integration_state["branch"]))
    if manifest and manifest.get("branch"):
        allowed.add(str(manifest["branch"]))
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "error": "could not read the worktree registry; no closure was attempted",
        }, args.json, "✗ close-wave refused: registry-list failed")
        return EXIT_BLOCK
    if args.commit and manifest is not None and manifest_delivery_status == "completed":
        steps: list[dict[str, Any]] = []
        integration_revision = manifest.get("integration_revision")
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps, "manifest": str(manifest_path),
                "error": revision_error,
            }, args.json, f"✗ close-wave stopped: {revision_error}")
            return EXIT_BLOCK
        saved_expected = _delivery_saved_expected_ticket_ids(manifest)
        expected_ticket_ids = _delivery_expected_ticket_set(
            primary, records, branches, saved_expected=saved_expected,
        )
        reservation_errors = _delivery_expected_ticket_reservation_errors(
            records, branches, statuses={wr.STATUS_ACTIVE, "merged"}
        )
        independent_completed = (
            manifest.get("independent") is True
            and saved_expected == []
            and isinstance((manifest.get("close_wave") or {}).get(
                "independent_provenance"
            ), dict)
            and (manifest.get("close_wave") or {}).get(
                "independent_provenance", {}
            ).get("ok") is True
        )
        closure = (
            {
                "ok": False,
                "expected_ticket_ids": expected_ticket_ids,
                "failures": reservation_errors,
            }
            if reservation_errors else
            {
                "ok": True,
                "expected_ticket_ids": [],
                "failures": [],
                "mode": "independent-no-ticket",
                "provenance": (manifest.get("close_wave") or {}).get(
                    "independent_provenance"
                ),
            }
            if independent_completed else
            _delivery_expected_ticket_closure(primary, expected_ticket_ids)
        )
        steps.append({"name": "expected-ticket-closure", **closure})
        if not closure["ok"]:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "steps": steps, "manifest": str(manifest_path) if manifest_path else None,
                "error": "completed close-wave has tickets that are not fixed",
            }, args.json,
                "✗ close-wave stopped: completed manifest does not prove every "
                "expected ticket is fixed")
            return EXIT_BLOCK
        sync_rc, sync_payload = _delivery_sync_close_wave(
            args, primary, manifest_path, steps,
        )
        if sync_rc != EXIT_OK:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps, "manifest": str(manifest_path) if manifest_path else None,
            }, args.json, "✗ close-wave stopped during remote sync")
            return sync_rc
        marker = (_delivery_load_json(manifest_path) or {}).get("close_wave", {})
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "already-closed", "slug": args.slug, "branches": branches,
            "integration_branch": manifest.get("branch"),
            "manifest": str(manifest_path) if manifest_path else None,
            "runner_revision": runner_revision,
            "integration_revision": integration_revision,
            "steps": steps, "expected_ticket_ids": expected_ticket_ids,
            "sync_status": marker.get("sync_status", "not-requested"),
        }, args.json,
            f"close-wave {args.slug}: already closed"
            + (" and synced" if marker.get("sync_status") == "completed"
               else "; remote sync not requested"))
        return EXIT_OK

    if (args.commit and manifest is not None
            and manifest_delivery_status == "validated"
            and not Path(str(manifest.get("worktree"))).is_dir()):
        rrc, recovery_records = _delivery_registry_records(args, primary=primary)
        if rrc != EXIT_OK:
            return EXIT_BLOCK
        active_allowed = [
            record for record in recovery_records
            if record.get("status") == wr.STATUS_ACTIVE
            and record.get("branch") in set(branches) | {manifest.get("branch")}
        ]
        if active_allowed:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="validated close-wave lost its integration worktree while an allowed active record remains",
            )
        recovered = _delivery_load_json(manifest_path) if manifest_path else None
        if recovered is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="validated close-wave manifest disappeared during recovery",
            )
        integration_revision = recovered.get("integration_revision")
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": [], "manifest": str(manifest_path),
                "error": revision_error,
            }, args.json, f"✗ close-wave recovery stopped: {revision_error}")
            return EXIT_BLOCK
        saved_expected = _delivery_saved_expected_ticket_ids(recovered)
        expected_ticket_ids = _delivery_expected_ticket_set(
            primary, recovery_records, branches, saved_expected=saved_expected,
        )
        reservation_errors = _delivery_expected_ticket_reservation_errors(
            recovery_records, branches, statuses={wr.STATUS_ACTIVE, "merged"}
        )
        independent_recovered = (
            recovered.get("independent") is True
            and saved_expected == []
            and isinstance((recovered.get("close_wave") or {}).get(
                "independent_provenance"
            ), dict)
            and (recovered.get("close_wave") or {}).get(
                "independent_provenance", {}
            ).get("ok") is True
        )
        closure = (
            {
                "ok": False,
                "expected_ticket_ids": expected_ticket_ids,
                "failures": reservation_errors,
            }
            if reservation_errors else
            {
                "ok": True,
                "expected_ticket_ids": [],
                "failures": [],
                "mode": "independent-no-ticket",
                "provenance": (recovered.get("close_wave") or {}).get(
                    "independent_provenance"
                ),
            }
            if independent_recovered else
            _delivery_expected_ticket_closure(primary, expected_ticket_ids)
        )
        recovery_steps: list[dict[str, Any]] = [
            {"name": "expected-ticket-closure", **closure}
        ]
        if not closure["ok"]:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "steps": recovery_steps, "manifest": str(manifest_path),
                "error": "validated close-wave recovery has tickets that are not fixed",
            }, args.json,
                "✗ close-wave recovery stopped: expected ticket set is not fully fixed")
            return EXIT_BLOCK
        recovered["close_wave"] = {
            **(recovered.get("close_wave") or {}),
            "status": "completed",
            "expected_ticket_ids": expected_ticket_ids,
        }
        try:
            _integrate_save(manifest_path, recovered)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist recovered close-wave completion: {exc}",
            )
        sync_rc, _sync_payload = _delivery_sync_close_wave(
            args, primary, manifest_path, recovery_steps,
        )
        if sync_rc != EXIT_OK:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": recovery_steps, "manifest": str(manifest_path),
            }, args.json, "close-wave recovered locally but remote sync stopped")
            return sync_rc
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "recovered", "slug": args.slug, "branches": branches,
            "integration_branch": manifest.get("branch"),
            "manifest": str(manifest_path) if manifest_path else None,
            "runner_revision": runner_revision,
            "integration_revision": integration_revision,
            "steps": recovery_steps, "expected_ticket_ids": expected_ticket_ids,
        }, args.json,
            f"close-wave {args.slug}: recovered after teardown"
            + (" and synced" if getattr(args, "sync", False)
               else "; remote sync not requested"))
        return EXIT_OK

    if not args.commit:
        independent_suffix = " --independent" if requested_independent else ""
        plan = [
            "integrate --commit --no-gate"
            f"{independent_suffix} (fresh) or --continue --commit"
            f"{independent_suffix} (resume)",
            "integrated-tree fresh Gate",
            "cutover --commit",
            "resolve every source with --via-integration main",
            "backlog.py anchor --commit",
            "commit only docs/runbook/backlog closure metadata",
            "backlog.py validate --baseline-check",
            "resolve the integration tree",
        ]
        if getattr(args, "sync", False):
            plan.append("sync --commit -> origin/main (backup leg)")
        if integration_state:
            next_step = f"integrate --continue --commit{independent_suffix}"
        elif manifest:
            next_step = "cutover --commit"
        else:
            next_step = f"integrate --commit --no-gate{independent_suffix}"
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave", "mode": "dry-run",
            "slug": args.slug, "branches": branches, "allowed_branches": sorted(allowed),
            "state_file": str(state_path) if integration_state else None,
            "manifest": str(manifest_path) if manifest else None,
            "plan": plan, "next_step": next_step,
        }, args.json,
            f"# close-wave {args.slug} (dry-run)\n  " + "\n  ".join(plan)
            + f"\n  next: {next_step}\n  (--commit to execute)")
        return EXIT_OK

    steps: list[dict[str, Any]] = []

    def record_phase(phase: str, status: str, **fields: Any) -> bool:
        """Write a durable phase receipt, turning ledger failures into a stop."""
        if manifest_path is None:
            return True
        try:
            _delivery_record_phase(
                manifest_path, phase, status=status, **fields,
            )
        except (OSError, ValueError) as exc:
            steps.append({
                "name": f"{phase}-phase",
                "status": status,
                "error": f"could not persist {phase} phase receipt: {exc}",
            })
            return False
        return True

    # Before cutover the source coordinator is required for the new protocol;
    # after cutover, all remaining steps use this stable primary copy.  A delivery
    # wave may resolve its own source worktree before anchor/sync, so any later
    # lookup through `__file__` is unsafe.
    primary_orchestrator = primary / "ops" / "worktree_orchestrate.py"
    target_base = operation_base
    integration_worktree: Path | None = None
    integration_branch: str | None = None

    if integration_state is None and manifest is None:
        integrate_rc, integrate_payload = _delivery_json_tool(
            coordinator_orchestrator,
            primary,
            [
                "integrate", "--slug", args.slug, "--branches", *branches,
                "--no-gate", "--commit", "--base", operation_base,
                *(["--independent"] if requested_independent else []),
                *_state_arg(args.state),
            ],
            label=f"integrate:{args.slug}",
            expected_schema=INTEGRATE_SCHEMA,
            required_keys=("worktree", "branch"),
            receipt_validator=_delivery_require_integrate_picked,
        )
        steps.append({"name": "integrate-pick", "rc": integrate_rc,
                      "payload": integrate_payload})
        if integrate_rc != EXIT_OK:
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "state_file": str(state_path) if state_path.exists() else None,
                   "next": "resolve the named conflict, then rerun close-wave with the same slug"},
                  args.json,
                  f"✗ close-wave stopped during integrate; state kept at {state_path}")
            return integrate_rc
        integration_state = _delivery_load_json(state_path)
        if integration_state is None:
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "error": "integrate returned success but left no resumable state",
                   "steps": steps}, args.json,
                  "✗ close-wave refused: integrate did not leave state")
            return EXIT_BLOCK
        integration_error = _delivery_integration_error(
            integration_state, label="integration state", slug=args.slug,
            base=operation_base, branches=branches, require_gated=False,
            require_live_worktree=True,
        )
        if integration_error:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=integration_error,
            )
        allowed.add(str(integration_state["branch"]))

    if integration_state is not None:
        integration_state["runner_revision"] = runner_revision
        try:
            _integrate_save(state_path, integration_state)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist runner_revision: {exc}",
            )

    if integration_state is not None:
        integration_worktree = Path(str(integration_state["worktree"]))
        integration_branch = str(integration_state.get("branch") or "")
        continue_script = integration_worktree / "ops" / "worktree_orchestrate.py"
        continue_rc, continue_payload = _delivery_json_tool(
            continue_script,
            integration_worktree,
            [
                "integrate", "--slug", args.slug, "--continue", "--commit",
                "--base", operation_base, *_state_arg(args.state),
                *(["--independent"] if requested_independent else []),
            ],
            label=f"integrate-gate:{args.slug}",
            expected_schema=INTEGRATE_SCHEMA,
            required_keys=("worktree", "branch", "manifest", "integration_revision"),
            receipt_validator=_delivery_require_integrate_gated,
        )
        steps.append({"name": "integrate-gate", "rc": continue_rc,
                      "payload": continue_payload})
        if continue_rc != EXIT_OK or continue_payload.get("verdict") not in ("pass", "warn"):
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug,
                   "runner_revision": runner_revision,
                   "integration_revision": continue_payload.get(
                       "integration_revision"
                   ),
                   "steps": steps,
                   "next": "fix/resume the named integrated-tree issue, then rerun close-wave"},
                  args.json, "✗ close-wave stopped: integrated-tree Gate is not non-block")
            return continue_rc or EXIT_BLOCK
        manifest_value = continue_payload.get("manifest")
        manifest_path = Path(str(manifest_value)) if manifest_value else None
        manifest = (_delivery_load_json(manifest_path)
                    if manifest_path and manifest_path.exists() else None)
        if manifest_path is None or manifest is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integrate reported success but left no readable manifest",
            )
        manifest_error = _delivery_integration_error(
            manifest, label="completed integration manifest", slug=args.slug,
            base=operation_base, branches=branches, require_gated=True,
            require_live_worktree=True,
        )
        if manifest_error:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=manifest_error,
            )
        integration_revision = manifest.get("integration_revision")
        if continue_payload.get("integration_revision") != integration_revision:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integrate gate receipt and manifest disagree on integration_revision",
            )
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            steps.append({
                "name": "revision-provenance", "ok": False,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "error": revision_error,
            })
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps, "manifest": str(manifest_path),
                "error": revision_error,
            }, args.json, f"✗ close-wave stopped: {revision_error}")
            return EXIT_BLOCK
        manifest["runner_revision"] = runner_revision
        try:
            _integrate_save(manifest_path, manifest)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist runner_revision in manifest: {exc}",
            )
        integration_state = None
        allowed.add(str(manifest.get("branch")))

    if getattr(args, "commit", False) and manifest is not None:
        integration_revision = manifest.get("integration_revision")
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps,
                "manifest": str(manifest_path) if manifest_path else None,
                "error": revision_error,
            }, args.json, f"✗ close-wave stopped: {revision_error}")
            return EXIT_BLOCK
        if manifest.get("runner_revision") != runner_revision:
            manifest["runner_revision"] = runner_revision
            try:
                _integrate_save(manifest_path, manifest)
            except OSError as exc:
                return _delivery_state_error(
                    args=args, state_path=state_path, manifest_path=manifest_path,
                    error=f"could not persist runner_revision in manifest: {exc}",
                )

    # The opening registry snapshot is not enough: a peer may start while the
    # integrated Gate is running.  Recheck before the irreversible develop step.
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        return EXIT_BLOCK
    # Other teams may have active worktrees. The shared Delivery Team lock keeps
    # their close-wave primary/sync sequence out of this critical section; their
    # source branches are not targets of this wave's resolve calls.
    saved_expected = _delivery_saved_expected_ticket_ids(manifest)
    expected_ticket_ids = _delivery_expected_ticket_set(
        primary, records, branches, saved_expected=saved_expected,
    )
    reservation_errors = _delivery_expected_ticket_reservation_errors(
        records, branches, statuses={wr.STATUS_ACTIVE, "merged"}
    )
    if manifest is not None:
        integration_worktree = integration_worktree or Path(str(manifest.get("worktree") or ""))
        integration_branch = integration_branch or str(manifest.get("branch") or "")
    elif integration_state is not None:
        integration_worktree = integration_worktree or Path(str(
            integration_state.get("worktree") or ""
        ))
        integration_branch = integration_branch or str(integration_state.get("branch") or "")
    integration_record = next(
        (record for record in records
         if record.get("status") == wr.STATUS_ACTIVE
         and record.get("branch") == integration_branch),
        None,
    )
    independent_provenance: dict[str, Any] | None = None
    if requested_independent:
        integration_head = ""
        if integration_worktree is not None and integration_worktree.is_dir():
            head_rc, integration_head = _git(
                ["rev-parse", "HEAD"], cwd=integration_worktree,
            )
            if head_rc != EXIT_OK:
                integration_head = ""
        independent_provenance = _delivery_independent_no_ticket_provenance(
            state=integration_state,
            manifest=manifest,
            integration_record=integration_record,
            current_head=integration_head,
            primary_dirty=_delivery_primary_dirty(primary),
            queue=list((integration_state or manifest or {}).get("queue") or []),
        )
    if reservation_errors or not expected_ticket_ids or (
            requested_independent
            and independent_provenance is not None
            and not independent_provenance["ok"]
    ):
        no_ticket_ok = (
            requested_independent
            and not reservation_errors
            and not expected_ticket_ids
            and independent_provenance is not None
            and independent_provenance["ok"]
        )
        expected_set_error = (
            "named source reservation has malformed backlog"
            if reservation_errors else
            "named source branches have no claimed backlog tickets"
            if not expected_ticket_ids and not no_ticket_ok else
            "independent no-ticket provenance is incomplete"
            if requested_independent else None
        )
        steps.append({
            "name": "expected-ticket-set",
            "ok": no_ticket_ok,
            "expected_ticket_ids": expected_ticket_ids,
            "errors": reservation_errors,
            "provenance": independent_provenance,
            **({"error": expected_set_error} if expected_set_error else {}),
        })
        if not no_ticket_ok:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "steps": steps,
                "error": (
                    "close-wave requires valid source ticket reservations"
                    if reservation_errors else
                    "close-wave requires complete independent no-ticket provenance"
                    if requested_independent else
                    "close-wave requires a non-empty expected ticket set"
                ),
            }, args.json,
                "✗ close-wave stopped: source ticket reservation is invalid"
                if reservation_errors else
                "✗ close-wave stopped: independent no-ticket provenance is incomplete"
                if requested_independent else
                "✗ close-wave stopped: expected ticket set is empty")
            return EXIT_BLOCK
    if manifest_path is not None and saved_expected is None:
        persisted = _delivery_load_json(manifest_path)
        if persisted is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integration manifest disappeared before expected ticket set was saved",
            )
        persisted["close_wave"] = {
            **(persisted.get("close_wave") or {}),
            "expected_ticket_ids": expected_ticket_ids,
            **(
                {"independent_provenance": independent_provenance}
                if independent_provenance is not None
                else {}
            ),
        }
        try:
            _integrate_save(manifest_path, persisted)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist expected ticket set: {exc}",
            )

    if manifest is not None:
        integration_worktree = integration_worktree or Path(str(manifest["worktree"]))
        integration_branch = integration_branch or str(manifest.get("branch") or "")
    if integration_worktree is None or integration_branch is None:
        _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
               "error": "no integration worktree/branch was available after assembly",
               "steps": steps}, args.json,
              "✗ close-wave refused: integration identity is missing")
        return EXIT_BLOCK

    head_rc, phase_head = _git(["rev-parse", "HEAD"], cwd=primary)
    if head_rc != EXIT_OK or not phase_head:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error="could not capture primary HEAD before close-wave phases",
        )
    phase_expected = list(expected_ticket_ids)
    if not record_phase(
        "cutover", "started", operation_base=operation_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=[], queue_state="pending",
    ):
        return EXIT_BLOCK
    ancestor_rc, _ = _git(
        ["merge-base", "--is-ancestor", integration_branch, target_base], cwd=primary
    )
    if ancestor_rc == 0:
        landed_rc, landed_sha = _git(["rev-parse", "HEAD"], cwd=primary)
        cutover_receipt = {
            "mode": "already-landed", "branch": integration_branch,
            "landed": landed_rc == EXIT_OK, "sha": landed_sha,
        }
        steps.append({"name": "cutover", **cutover_receipt})
        if not record_phase(
            "cutover", "completed", operation_base=operation_base,
            landed_sha=landed_sha if landed_rc == EXIT_OK else phase_head,
            expected_ticket_ids=phase_expected, applied_ticket_ids=[],
            acceptance_receipt=cutover_receipt, queue_state="pending",
        ):
            return EXIT_BLOCK
    else:
        cutover_script = integration_worktree / "ops" / "worktree_orchestrate.py"
        cutover_rc, cutover_payload = _delivery_json_tool(
            cutover_script,
            integration_worktree,
            [
                "cutover", "--worktree", str(integration_worktree), "--commit",
                "--base", operation_base, *_state_arg(args.state),
            ],
                label=f"cutover:{args.slug}",
                expected_schema=SCHEMA,
                required_keys=("landed",),
                receipt_validator=_delivery_require_cutover_landed,
        )
        steps.append({"name": "cutover", "rc": cutover_rc,
                      "payload": cutover_payload})
        if cutover_rc != EXIT_OK or not cutover_payload.get("landed"):
            record_phase(
                "cutover", "blocked", operation_base=operation_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=[], acceptance_receipt=cutover_payload,
                queue_state="pending",
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "next": "follow cutover refusal, then rerun close-wave"}, args.json,
                  "✗ close-wave stopped: cutover did not land")
            return cutover_rc or EXIT_BLOCK
        if not record_phase(
            "cutover", "completed", operation_base=operation_base,
            landed_sha=cutover_payload.get("sha") or cutover_payload.get("landed_sha"),
            expected_ticket_ids=phase_expected, applied_ticket_ids=[],
            acceptance_receipt=cutover_payload, queue_state="pending",
        ):
            return EXIT_BLOCK

    phase_head_rc, landed_phase_head = _git(["rev-parse", "HEAD"], cwd=primary)
    if phase_head_rc == EXIT_OK and landed_phase_head:
        phase_head = landed_phase_head

    # Capture source paths after cutover too: a resumed invocation may have already
    # resolved some of them.  Resolved sources are idempotently skipped; active
    # sources are audited before removal.
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        return EXIT_BLOCK
    active_by_branch = {
        str(record.get("branch")): record for record in records
        if record.get("status") == wr.STATUS_ACTIVE
    }
    if not record_phase(
        "resolve-source", "started", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=[], queue_state="pending",
        source_branches=list(branches),
    ):
        return EXIT_BLOCK
    resolved_branches: list[str] = []
    for branch in branches:
        record = active_by_branch.get(branch)
        if record is None:
            steps.append({"name": "resolve-source", "branch": branch, "mode": "already-resolved"})
            resolved_branches.append(branch)
            continue
        source_path = Path(str(record.get("path") or ""))
        if not source_path.is_dir():
            record_phase(
                "resolve-source", "blocked", operation_base=target_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=[], queue_state="pending",
                resolved_branches=resolved_branches,
                error="active source worktree is missing",
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "error": "active source worktree is missing; refusing to guess its identity",
                   "branch": branch, "path": str(source_path), "steps": steps}, args.json,
                  f"✗ close-wave stopped: source worktree missing for {branch}")
            return EXIT_BLOCK
        resolve_rc, resolve_payload = _delivery_json_tool(
            primary_orchestrator,
            primary,
            [
                "resolve", "--worktree", str(source_path),
                "--base", target_base, "--via-integration", integration_branch,
                "--commit", *_state_arg(args.state),
            ],
            label=f"resolve-source:{branch}",
            expected_schema=SCHEMA,
            required_keys=("step",),
            receipt_validator=_delivery_require_resolved,
        )
        steps.append({"name": "resolve-source", "branch": branch, "rc": resolve_rc,
                      "payload": resolve_payload})
        if resolve_rc != EXIT_OK:
            record_phase(
                "resolve-source", "blocked", operation_base=target_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=[], acceptance_receipt=resolve_payload,
                queue_state="pending", resolved_branches=resolved_branches,
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "next": "fix the named resolve audit and rerun close-wave"}, args.json,
                  f"✗ close-wave stopped resolving source {branch}")
            return resolve_rc
        resolved_branches.append(branch)
    if not record_phase(
        "resolve-source", "completed", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=[], queue_state="pending",
        resolved_branches=resolved_branches,
    ):
        return EXIT_BLOCK

    anchor_rc, anchor_steps = _delivery_anchor_and_commit(
        args, primary, allowed, args.slug, manifest_path
    )
    steps.extend(anchor_steps)
    anchor_commit_rc = anchor_rc
    if anchor_commit_rc != EXIT_OK:
        record_phase(
            "anchor", "blocked", operation_base=phase_head,
            landed_sha=phase_head, expected_ticket_ids=phase_expected,
            applied_ticket_ids=[], queue_state="pending",
            acceptance_receipt=(anchor_steps[-1] if anchor_steps else None),
        )
        _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
               "mode": "stopped", "slug": args.slug, "steps": steps}, args.json,
              "✗ close-wave stopped: anchor metadata was not committed")
        return EXIT_BLOCK
    closure = (
        {
            "ok": True,
            "expected_ticket_ids": [],
            "failures": [],
            "mode": "independent-no-ticket",
            "provenance": independent_provenance,
        }
        if requested_independent and not expected_ticket_ids
        else _delivery_expected_ticket_closure(primary, expected_ticket_ids)
    )
    steps.append({"name": "expected-ticket-closure", **closure})
    if not closure["ok"]:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug, "branches": branches,
            "steps": steps,
            "error": "anchor succeeded but expected ticket set is not fully fixed",
        }, args.json,
            "✗ close-wave stopped: anchor did not close every expected ticket")
        return EXIT_BLOCK

    if not record_phase(
        "validate", "started", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids, queue_state="consumed",
    ):
        return EXIT_BLOCK
    validate_rc, validate_payload = _delivery_json_tool(
        primary / "ops" / "backlog.py",
        primary,
        ["validate", "--baseline-check"],
        label=f"validate:{args.slug}",
        expected_schema="kg.backlog.validate.v1",
        required_keys=("problems", "ok"),
        receipt_validator=_delivery_require_validate_receipt,
    )
    steps.append({"name": "validate", "rc": validate_rc,
                  "payload": validate_payload})
    if validate_rc != EXIT_OK:
        record_phase(
            "validate", "blocked", operation_base=target_base,
            landed_sha=phase_head, expected_ticket_ids=phase_expected,
            applied_ticket_ids=expected_ticket_ids,
            acceptance_receipt=validate_payload, queue_state="consumed",
        )
        _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
               "mode": "stopped", "slug": args.slug, "steps": steps}, args.json,
              "✗ close-wave stopped: backlog validation is not green")
        return validate_rc
    if not record_phase(
        "validate", "completed", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids,
        acceptance_receipt=validate_payload, queue_state="consumed",
    ):
        return EXIT_BLOCK

    if manifest_path is not None:
        validated_manifest = _delivery_load_json(manifest_path)
        if validated_manifest is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integration manifest disappeared after validation",
            )
        validated_manifest["close_wave"] = {
            **(validated_manifest.get("close_wave") or {}),
            "status": "validated",
        }
        try:
            _integrate_save(manifest_path, validated_manifest)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist validated close-wave state: {exc}",
            )

    # Keep teardown last.  If anchor or validation stops, the integration worktree
    # and manifest remain available for the same slug to resume; deleting them first
    # would leave a successful landing with no way to finish the lifecycle.
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        return EXIT_BLOCK
    integration_record = next(
        (record for record in records
         if record.get("status") == wr.STATUS_ACTIVE
         and record.get("branch") == integration_branch),
        None,
    )
    if not record_phase(
        "resolve-integration", "started", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids, queue_state="consumed",
        integration_branch=integration_branch,
    ):
        return EXIT_BLOCK
    if integration_record is None:
        steps.append({"name": "resolve-integration", "mode": "already-resolved",
                      "branch": integration_branch})
        resolve_integration_receipt = {
            "mode": "already-resolved", "branch": integration_branch,
            "resolved": "merged", "failures": 0,
        }
    else:
        resolve_rc, resolve_payload = _delivery_json_tool(
            primary_orchestrator,
            primary,
            [
                "resolve", "--worktree", str(integration_worktree),
                "--base", target_base, "--via-integration", integration_branch,
                "--commit", *_state_arg(args.state),
            ],
            label=f"resolve-integration:{args.slug}",
            expected_schema=SCHEMA,
            required_keys=("step",),
            receipt_validator=_delivery_require_resolved,
        )
        steps.append({"name": "resolve-integration", "rc": resolve_rc,
                      "payload": resolve_payload})
        if resolve_rc != EXIT_OK:
            record_phase(
                "resolve-integration", "blocked", operation_base=target_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=expected_ticket_ids,
                acceptance_receipt=resolve_payload, queue_state="consumed",
                integration_branch=integration_branch,
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "next": "fix the named integration resolve issue and rerun close-wave"}, args.json,
                  "✗ close-wave stopped resolving the integration tree")
            return resolve_rc
        resolve_integration_receipt = resolve_payload
    if not record_phase(
        "resolve-integration", "completed", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids,
        acceptance_receipt=resolve_integration_receipt, queue_state="consumed",
        integration_branch=integration_branch,
    ):
        return EXIT_BLOCK

    if manifest_path is not None:
        completed_manifest = _delivery_load_json(manifest_path)
        if completed_manifest is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integration manifest disappeared after resolve",
            )
        completed_manifest["close_wave"] = {
            **(completed_manifest.get("close_wave") or {}),
            "status": "completed",
            "sync_status": (
                "pending" if getattr(args, "sync", False) else "not-requested"
            ),
        }
        try:
            _integrate_save(manifest_path, completed_manifest)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist completed close-wave state: {exc}",
            )

    sync_rc, _sync_payload = _delivery_sync_close_wave(
        args, primary, manifest_path, steps,
    )
    if sync_rc != EXIT_OK:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug, "steps": steps,
            "runner_revision": runner_revision,
            "integration_revision": (
                (manifest or {}).get("integration_revision")
                if isinstance(manifest, dict) else None
            ),
            "manifest": str(manifest_path) if manifest_path else None,
        }, args.json, "close-wave landed locally but remote sync stopped")
        return sync_rc

    final_manifest = _delivery_load_json(manifest_path) if manifest_path else None
    final_marker = ((final_manifest or {}).get("close_wave")
                    if isinstance(final_manifest, dict) else {}) or {}
    final_integration_revision = None
    for candidate in (final_manifest, manifest):
        if isinstance(candidate, dict) and candidate.get("integration_revision"):
            final_integration_revision = candidate["integration_revision"]
            break
    _emit({
        "schema": DELIVERY_SCHEMA, "step": "close-wave", "mode": "committed",
        "slug": args.slug, "branches": branches, "integration_branch": integration_branch,
        "runner_revision": runner_revision,
        "integration_revision": final_integration_revision,
        "steps": steps, "primary_dirty": _delivery_primary_dirty(primary),
        "expected_ticket_ids": expected_ticket_ids,
        "sync_status": final_marker.get("sync_status", "not-requested"),
    }, args.json,
        f"✓ close-wave {args.slug}: integrated, gated, cut over, sources resolved, "
        "anchored, validated, integration tree resolved"
        + (" and synced to origin/main" if final_marker.get("sync_status") == "completed"
           else " (remote sync not requested)"))
    return EXIT_OK
