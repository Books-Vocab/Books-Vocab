"""Close-wave child receipt, registry, and ticket-set contracts."""

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


# ---------------------------------------------------------------------------
# close-wave — the Delivery Team's bounded batch-closure coordinator
# ---------------------------------------------------------------------------

def _delivery_json_tool(
    script: Path,
    cwd: Path,
    argv: list[str],
    *,
    label: str,
    expected_schema: str | None = None,
    required_keys: tuple[str, ...] = (),
    receipt_validator: Callable[[dict[str, Any]], str | None] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run one existing orchestrator/registry verb and decode its JSON receipt.

    ``close-wave`` coordinates existing primitives; it does not reproduce their
    gate, containment, or registry judgement.  Keeping each child as a separate
    process also means its stderr heartbeat remains visible while stdout stays a
    single machine-readable payload for the coordinator.
    """
    command = [sys.executable, str(script), *argv]
    if "--json" not in command:
        command.append("--json")
    try:
        completed = run_streamed_command(
            command,
            cwd=cwd,
            label_key="delivery",
            label=label,
            progress_prefix="[delivery]",
            heartbeat_interval=20.0,
            # Registry ledgers are machine JSON, not human log tails.  The old
            # 256 KiB ceiling truncated a measured ~276 KiB receipt and made a
            # valid close-wave look like a malformed child.  Keep a finite bound
            # for runaway tools while leaving enough room for the complete ledger.
            capture_limit=8 * 1024 * 1024,
        )
    except OSError as exc:
        return 127, {"error": f"could not start {label}: {exc}"}
    except KeyboardInterrupt:
        return EXIT_BLOCK, {
            "error": f"{label} was interrupted; resumable state was left in place",
            "interrupted": True,
        }
    diagnostic = (completed.stderr or "").strip()
    if diagnostic:
        # The streaming runner keeps child stderr separate so the coordinator's
        # stdout remains one JSON document.  Relay it after completion as well:
        # otherwise a child can fail with useful evidence that is invisible to the
        # operator who is watching the parent process.
        print(diagnostic, file=sys.stderr, flush=True)
    raw = (completed.stdout or "").strip()
    child_rc = completed.returncode if completed.returncode is not None else EXIT_BLOCK
    if not raw:
        return child_rc or EXIT_BLOCK, {
            "error": f"{label} returned no JSON payload",
            "stderr": diagnostic[-4000:],
        }
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return child_rc or EXIT_BLOCK, {
            "error": f"{label} returned invalid JSON: {exc}",
            "stdout_tail": raw[-4000:],
            "stderr": diagnostic[-4000:],
        }
    if not isinstance(payload, dict):
        return child_rc or EXIT_BLOCK, {
            "error": f"{label} returned JSON {type(payload).__name__}, expected object",
            "payload": payload,
        }
    if child_rc == EXIT_OK:
        contract_errors: list[str] = []
        if expected_schema and payload.get("schema") != expected_schema:
            contract_errors.append(
                f"schema {payload.get('schema')!r} != {expected_schema!r}"
            )
        missing = [key for key in required_keys if key not in payload]
        if missing:
            contract_errors.append("missing keys: " + ", ".join(missing))
        if receipt_validator is not None:
            semantic_error = receipt_validator(payload)
            if semantic_error:
                contract_errors.append(semantic_error)
        if contract_errors:
            return EXIT_BLOCK, {
                "error": f"{label} returned an invalid success receipt",
                "contract_errors": contract_errors,
                "receipt": payload,
            }
    return child_rc, payload


def _delivery_require_mode(payload: dict[str, Any], expected: str) -> str | None:
    actual = payload.get("mode")
    if actual != expected:
        return f"mode {actual!r} != {expected!r}"
    return None


def _delivery_require_integrate_picked(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "picked")
    if error:
        return error
    if payload.get("gate_pending") is not True:
        return "picked integration receipt does not set gate_pending=true"
    if payload.get("landed") is not False:
        return "picked integration receipt must set landed=false"
    if not isinstance(payload.get("head_sha"), str) or not payload["head_sha"]:
        return "picked integration receipt has no head_sha"
    return None


def _delivery_require_integrate_gated(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "committed")
    if error:
        return error
    if payload.get("landed") is not False:
        return "gated integration receipt must set landed=false"
    if payload.get("verdict") not in ("pass", "warn"):
        return (f"gated integration receipt has non-landable verdict "
                f"{payload.get('verdict')!r}")
    if not isinstance(payload.get("manifest"), str) or not payload["manifest"]:
        return "gated integration receipt has no manifest"
    if not isinstance(payload.get("runner_revision"), str) \
            or not payload["runner_revision"]:
        return "gated integration receipt has no runner_revision"
    if not isinstance(payload.get("integration_revision"), str) \
            or not payload["integration_revision"]:
        return "gated integration receipt has no integration_revision"
    return None


def _delivery_require_cutover_landed(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "committed")
    if error:
        return error
    if payload.get("landed") is not True:
        return "cutover success receipt must set landed=true"
    if not isinstance(payload.get("sha"), str) or not payload["sha"]:
        return "cutover success receipt has no landed sha"
    return None


def _delivery_require_resolved(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "committed")
    if error:
        return error
    if payload.get("resolved") != "merged":
        return (f"resolve success receipt has resolved={payload.get('resolved')!r}, "
                "expected 'merged'")
    if payload.get("failures") != 0:
        return f"resolve success receipt has failures={payload.get('failures')!r}"
    return None


def _delivery_require_anchor_receipt(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "commit")
    if error:
        return error
    problems = payload.get("problems")
    if not isinstance(problems, list):
        return "anchor receipt has non-list problems"
    if problems:
        return f"anchor receipt has {len(problems)} problem(s)"
    unstamped = payload.get("unstamped")
    if not isinstance(unstamped, list):
        return "anchor receipt has non-list unstamped"
    if unstamped:
        return (f"anchor receipt still has {len(unstamped)} selected closure(s) "
                "without a landed sha")
    applied = payload.get("applied")
    if not isinstance(applied, list) or any(
        not isinstance(ticket_id, str) for ticket_id in applied
    ):
        return "anchor receipt has malformed applied ids"
    return None


def _delivery_require_validate_receipt(payload: dict[str, Any]) -> str | None:
    problems = payload.get("problems")
    if not isinstance(problems, list):
        return "validate receipt has non-list problems"
    if problems:
        return f"validate receipt has {len(problems)} problem(s)"
    if payload.get("ok") is not True:
        return f"validate receipt has ok={payload.get('ok')!r}"
    return None


def _delivery_require_registry_receipt(payload: dict[str, Any]) -> str | None:
    records = payload.get("records")
    if not isinstance(records, list):
        return "registry receipt has non-list records"
    allowed_statuses = {wr.STATUS_ACTIVE, "merged", "abandoned"}
    required = ("path", "branch", "base", "status")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return f"registry record {index} is not an object"
        missing = [key for key in required if key not in record]
        if missing:
            return f"registry record {index} missing keys: {', '.join(missing)}"
        if any(not isinstance(record[key], str) or not record[key]
               for key in ("path", "branch", "base")):
            return f"registry record {index} has malformed path/branch/base"
        if not Path(record["path"]).is_absolute():
            return f"registry record {index} has a non-absolute path"
        if record["status"] not in allowed_statuses:
            return (f"registry record {index} has unknown status "
                    f"{record['status']!r}")
    return None


def _delivery_state_paths(args: argparse.Namespace) -> tuple[Path, list[Path]]:
    state_path = _integrate_state_path(args.state, args.slug)
    completed_dir = state_path.parent / "completed"
    manifests = sorted(
        completed_dir.glob(f"{args.slug}-*.json"),
        key=lambda path: path.stat().st_mtime_ns if path.exists() else 0,
        reverse=True,
    )
    return state_path, manifests


def _delivery_load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _delivery_revision(path: Path) -> str | None:
    """Return the content revision of one orchestrator copy, fail-closed."""
    try:
        return sha256_file(path)
    except OSError:
        return None


def _delivery_revision_guard(
    runner_revision: str | None,
    integration_revision: str | None,
) -> str | None:
    """Require the runner and gated integration tree to use one tool revision."""
    if not isinstance(runner_revision, str) or not runner_revision:
        return "runner_revision is missing"
    if not isinstance(integration_revision, str) or not integration_revision:
        return "integration_revision is missing"
    if runner_revision != integration_revision:
        return "runner_revision does not match integration_revision"
    return None


def _delivery_common_dir(worktree: Path) -> str | None:
    rc, common = _git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=worktree,
    )
    return _norm(common) if rc == EXIT_OK and common else None


def _delivery_integration_error(
    payload: Any,
    *,
    label: str,
    slug: str,
    base: str,
    branches: list[str],
    require_gated: bool,
    require_live_worktree: bool,
) -> str | None:
    """Validate a persisted integration receipt before using its identity.

    A resumable coordinator must not let a stale slug borrow another run's state,
    branch, base, or worktree.  This is deliberately a schema/identity check rather
    than a best-effort ``dict.get`` chain: malformed local state is a blocked receipt,
    never an invitation to start a fresh integration with the same name.
    """
    if not isinstance(payload, dict):
        return f"{label} is not a JSON object"
    if payload.get("schema") != INTEGRATE_SCHEMA:
        return (f"{label} has schema {payload.get('schema')!r}, expected "
                f"{INTEGRATE_SCHEMA!r}")
    if payload.get("slug") != slug:
        return f"{label} belongs to slug {payload.get('slug')!r}, not {slug!r}"
    stored_base = payload.get("base")
    stored_base_is_identity = (
        isinstance(stored_base, str)
        and re.fullmatch(r"[0-9a-fA-F]{7,64}", stored_base) is not None
    )
    if (stored_base != base
            and _local_trunk(str(stored_base or "")) != _local_trunk(base)
            and not stored_base_is_identity):
        return (f"{label} was created with base {payload.get('base')!r}, not "
                f"{base!r}")
    stored_branches = payload.get("branches")
    if not isinstance(stored_branches, list) or any(
        not isinstance(branch, str) for branch in stored_branches
    ):
        return f"{label} has malformed branches"
    if stored_branches != branches:
        return (f"{label} branch list {stored_branches!r} does not match "
                f"{branches!r}")
    if not isinstance(payload.get("worktree"), str) or not payload["worktree"]:
        return f"{label} has no worktree identity"
    if not isinstance(payload.get("branch"), str) or not payload["branch"]:
        return f"{label} has no integration branch identity"
    if require_gated and payload.get("status") != "gated":
        return (f"{label} status is {payload.get('status')!r}, expected 'gated' "
                "before close-wave cutover")
    worktree = Path(payload["worktree"])
    if not worktree.is_absolute():
        return f"{label} worktree path is not absolute: {worktree}"
    if worktree.exists():
        # A path can be a perfectly valid foreign checkout (or merely a directory
        # inside this repository). `_current_branch` alone is unsafe because git
        # discovery walks upward after a linked worktree's `.git` file disappears.
        # Require both the repository's worktree registry identity and the shared
        # git-common-dir before executing any persisted child command.
        entry = _worktree_entry(str(worktree))
        if entry is None:
            return (f"{label} worktree is not a linked worktree of this repository: "
                    f"{worktree}")
        if _norm(str(entry.get("path") or "")) != _norm(str(worktree)):
            return f"{label} worktree registry path disagrees: {worktree}"
        if entry.get("branch") != payload["branch"]:
            return (f"{label} worktree registry branch is {entry.get('branch')!r}, "
                    f"expected {payload['branch']!r}")
        actual_branch = _current_branch(str(worktree))
        if actual_branch != payload["branch"]:
            return (f"{label} worktree is on {actual_branch!r}, expected "
                    f"{payload['branch']!r}")
        primary_common = _delivery_common_dir(primary_root())
        worktree_common = _delivery_common_dir(worktree)
        if primary_common is None or worktree_common is None:
            return (f"{label} cannot verify git-common-dir containment for "
                    f"{worktree}")
        if worktree_common != primary_common:
            return (f"{label} worktree belongs to a different repository "
                    f"(common-dir {worktree_common!r}, expected {primary_common!r})")
    elif require_live_worktree:
        return f"{label} worktree is missing: {worktree}"
    return None


def _delivery_state_error(
    *,
    args: argparse.Namespace,
    state_path: Path,
    manifest_path: Path | None,
    error: str,
    mode: str = "stopped",
) -> int:
    _emit({
        "schema": DELIVERY_SCHEMA,
        "step": "close-wave",
        "mode": mode,
        "slug": args.slug,
        "state_file": str(state_path) if state_path.exists() else None,
        "manifest": str(manifest_path) if manifest_path and manifest_path.exists() else None,
        "error": error,
        "next": "inspect the named state/manifest; do not delete it blindly",
    }, args.json, f"✗ close-wave refused: {error}")
    return EXIT_BLOCK


def _delivery_registry_records(
    args: argparse.Namespace, *, primary: Path | None = None
) -> tuple[int, list[dict[str, Any]]]:
    # Run the registry implementation that belongs to this coordinator.  During
    # the first delivery-loop round the coordinator can still be in an isolated
    # worktree while primary is on the previous tool version; using primary's
    # copy here would make the new close-wave protocol self-incompatible.
    repo = primary or primary_root()
    registry_script = (
        repo / "ops" / "worktree_registry.py"
        if primary is not None
        else Path(__file__).resolve().parent / "worktree_registry.py"
    )
    # `list` defaults to a human table.  The coordinator consumes the typed JSON
    # receipt; make that contract explicit instead of relying on a downstream
    # helper to append a flag after an already-built argv snapshot.
    argv = ["list", "--json"]
    if args.state:
        argv += ["--state", args.state]
    rc, payload = _delivery_json_tool(
        registry_script, repo, argv, label="registry-list",
        expected_schema="kg.worktree.registry.v1", required_keys=("records",),
        receipt_validator=_delivery_require_registry_receipt,
    )
    records = payload.get("records")
    if rc != EXIT_OK or not isinstance(records, list):
        return rc or EXIT_BLOCK, []
    semantic_error = _delivery_require_registry_receipt(payload)
    if semantic_error:
        return EXIT_BLOCK, []
    return EXIT_OK, records


def _delivery_expected_ticket_ids(
    records: list[dict[str, Any]], branches: list[str],
    *, statuses: set[str] | None = None,
    staged_ids: Iterable[str] | None = None,
) -> list[str]:
    """Derive the ticket set a named wave owes from its source reservations.

    The registry is the ownership SoT.  Reading only the explicitly named source
    branches prevents a foreign Team's active work from entering this closure, while
    the optional ``statuses`` argument lets a completed-wave recovery read the same
    reservations after ``resolve`` has marked them merged.
    """
    allowed_branches = set(branches)
    allowed_statuses = statuses or {wr.STATUS_ACTIVE}
    ticket_ids: set[str] = set()
    for record in records:
        if (record.get("status") not in allowed_statuses
                or record.get("branch") not in allowed_branches):
            continue
        backlog = record.get("backlog")
        if not isinstance(backlog, list):
            continue
        ticket_ids.update(
            ticket_id for ticket_id in backlog
            if isinstance(ticket_id, str) and ticket_id
        )
    ticket_ids.update(
        ticket_id for ticket_id in (staged_ids or ())
        if isinstance(ticket_id, str) and ticket_id
    )
    return sorted(ticket_ids)


def _delivery_staged_ticket_ids(
    primary: Path, branches: Iterable[str],
) -> list[str]:
    """Return staged closure ids owned by the explicitly named source branches.

    A stacked hand-back can be resolved before the wave resumes, so registry
    ``backlog`` lists are no longer a complete closure ledger.  The gitignored
    anchor queue is the durable per-machine evidence for those staged rows; it is
    merged only for named branches, preserving the foreign-team boundary.
    """
    allowed = {branch for branch in branches if isinstance(branch, str)}
    return sorted({
        row.get("id") for row in _read_anchor_queue(primary)
        if isinstance(row, dict)
        and row.get("branch") in allowed
        and isinstance(row.get("id"), str)
        and row.get("id")
    })


def _delivery_expected_ticket_set(
    primary: Path,
    records: list[dict[str, Any]],
    branches: list[str],
    *,
    saved_expected: Iterable[str] | None = None,
) -> list[str]:
    """Union persisted, registry, and staged ids without widening the wave."""
    ids = _delivery_expected_ticket_ids(
        records,
        branches,
        statuses={wr.STATUS_ACTIVE, "merged"},
        staged_ids=_delivery_staged_ticket_ids(primary, branches),
    )
    ids.extend(
        ticket_id for ticket_id in (saved_expected or ())
        if isinstance(ticket_id, str) and ticket_id
    )
    return sorted(set(ids))


def _delivery_expected_ticket_reservation_errors(
    records: list[dict[str, Any]], branches: list[str],
    *, statuses: set[str] | None = None,
) -> list[dict[str, str]]:
    """Fail closed when a named source reservation cannot expose its tickets."""
    allowed_branches = set(branches)
    allowed_statuses = statuses or {wr.STATUS_ACTIVE}
    errors: list[dict[str, str]] = []
    for record in records:
        if (record.get("status") not in allowed_statuses
                or record.get("branch") not in allowed_branches):
            continue
        backlog = record.get("backlog")
        if (not isinstance(backlog, list)
                or any(not isinstance(ticket_id, str) or not ticket_id
                       for ticket_id in backlog)):
            errors.append({
                "branch": str(record.get("branch")),
                "reason": "backlog must be a list of non-empty ticket ids",
            })
    return errors


def _delivery_expected_ticket_closure(
    primary: Path, expected_ticket_ids: list[str],
) -> dict[str, Any]:
    """Machine-check the exact ticket set before close-wave can report success."""
    expected = sorted(set(expected_ticket_ids))
    if not expected:
        return {
            "ok": False,
            "expected_ticket_ids": [],
            "failures": [{"reason": "expected ticket set is empty"}],
        }

    failures: list[dict[str, str]] = []
    for ticket_id in expected:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id):
            failures.append({"id": ticket_id, "reason": "ticket id is malformed"})
            continue
        path = primary / "docs" / "runbook" / "backlog" / f"{ticket_id}.json"
        payload = _delivery_load_json(path)
        if payload is None:
            failures.append({"id": ticket_id, "reason": "entry is missing or unreadable"})
            continue
        if payload.get("status") != "fixed":
            failures.append({
                "id": ticket_id,
                "reason": f"status is {payload.get('status')!r}",
            })
            continue
        if payload.get("verdict") != "CONFIRMED-FIXED":
            failures.append({
                "id": ticket_id,
                "reason": f"verdict is {payload.get('verdict')!r}",
            })
            continue
        fixed_by = payload.get("fixed_by")
        if not isinstance(fixed_by, list) or not fixed_by:
            failures.append({"id": ticket_id, "reason": "fixed_by is empty"})
        elif any(
            not isinstance(sha, str) or not sha.strip() for sha in fixed_by
        ):
            failures.append({
                "id": ticket_id,
                "reason": "fixed_by contains an empty sha",
            })

    return {
        "ok": not failures,
        "expected_ticket_ids": expected,
        "failures": failures,
    }


def _delivery_independent_no_ticket_provenance(
    *,
    state: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    integration_record: dict[str, Any] | None,
    current_head: str,
    primary_dirty: list[str],
    queue: list[Any],
) -> dict[str, Any]:
    """Prove an explicit no-ticket close-wave opt-in without weakening defaults.

    The opt-in is deliberately recorded in three planes: integration state and
    completed manifest carry ``independent=true`` while the registry's existing
    intent field carries the typed ``independent-no-ticket:`` marker.  The Gate
    receipt must name the exact integrated HEAD and be non-blocking; primary and
    the integration queue must be clean.  This keeps an empty expected-ticket set
    auditable without adding a second registry schema or allowing a stale manifest
    to masquerade as an independent wave.
    """
    failures: list[dict[str, Any]] = []
    state_independent = (
        state.get("independent") is True if isinstance(state, dict) else
        manifest.get("independent") is True if isinstance(manifest, dict) else False
    )
    if not state_independent:
        failures.append({"reason": "integration state is not explicitly independent"})
    if not isinstance(manifest, dict) or manifest.get("independent") is not True:
        failures.append({"reason": "completed manifest is not explicitly independent"})
    if not isinstance(integration_record, dict):
        failures.append({"reason": "integration registry record is missing"})
    else:
        intent = integration_record.get("intent")
        if not isinstance(intent, str) or not intent.startswith(
                _INDEPENDENT_NO_TICKET_INTENT
        ):
            failures.append({
                "reason": "integration registry intent lacks independent-no-ticket marker",
            })
    gate = ((manifest or {}).get("gate") if isinstance(manifest, dict) else None)
    if not isinstance(gate, dict) and isinstance(state, dict):
        gate = state.get("gate")
    if not isinstance(gate, dict):
        failures.append({"reason": "independent wave has no Gate receipt"})
    else:
        if gate.get("verdict") not in {"pass", "warn"}:
            failures.append({
                "reason": "independent wave Gate is not non-block",
                "verdict": gate.get("verdict"),
            })
        if gate.get("head_sha") != current_head:
            failures.append({
                "reason": "independent wave Gate HEAD differs from current integration HEAD",
                "gate_head": gate.get("head_sha"), "current_head": current_head,
            })
    if isinstance(manifest, dict) and manifest.get("head_sha") != current_head:
        failures.append({
            "reason": "independent manifest HEAD differs from current integration HEAD",
            "manifest_head": manifest.get("head_sha"), "current_head": current_head,
        })
    if primary_dirty:
        failures.append({"reason": "primary is dirty", "dirty_files": primary_dirty})
    if queue:
        failures.append({"reason": "integration queue is not empty", "queue": queue})
    return {
        "ok": not failures,
        "mode": "independent-no-ticket",
        "failures": failures,
        "registry_marker": _INDEPENDENT_NO_TICKET_INTENT,
        "gate_head": gate.get("head_sha") if isinstance(gate, dict) else None,
        "current_head": current_head,
    }


def _delivery_saved_expected_ticket_ids(
    manifest: dict[str, Any] | None,
) -> list[str] | None:
    """Read a persisted expected set, distinguishing absent from malformed."""
    if not isinstance(manifest, dict):
        return None
    marker = manifest.get("close_wave")
    if not isinstance(marker, dict) or "expected_ticket_ids" not in marker:
        return None
    raw = marker.get("expected_ticket_ids")
    if not isinstance(raw, list) or any(
        not isinstance(ticket_id, str) or not ticket_id for ticket_id in raw
    ):
        return []
    return sorted(set(raw))


def _delivery_foreign_active(
    records: list[dict[str, Any]], allowed_branches: set[str]
) -> list[dict[str, Any]]:
    """Return active records outside the explicitly named wave boundary."""
    return [
        {
            "branch": record.get("branch"),
            "path": record.get("path"),
            "intent": record.get("intent"),
            "handed_back_sha": record.get("handed_back_sha"),
        }
        for record in records
        if record.get("status") == wr.STATUS_ACTIVE
        and record.get("branch") not in allowed_branches
    ]


def _delivery_primary_dirty(primary: Path) -> list[str]:
    rc, output = _git(["status", "--porcelain", "--untracked-files=all"], cwd=primary)
    if rc != 0:
        return [f"git status failed: {output}"]
    return [line for line in output.splitlines() if line.strip()]


_DELIVERY_ANCHOR_SUBJECT = "ops: anchor delivered backlog wave"


def _delivery_anchor_identity(
    primary: Path,
    expected_paths: set[str],
    *,
    base_sha: str | None,
    expected_sha: str | None = None,
) -> str | None:
    """Return the exact already-landed anchor commit, or None.

    The close-wave manifest is written before the anchor commit. If the process dies
    after ``git commit`` and before the manifest flips ``anchor_committed``, a retry
    must identify that one commit by parent, subject and changed paths. A
    bare "primary is clean" check is not enough: it could silently bless an unrelated
    clean commit made by another actor.
    """
    tip_rc, tip = _git(["rev-parse", "HEAD"], cwd=primary)
    if tip_rc != EXIT_OK or not tip:
        return None
    if expected_sha and tip != expected_sha:
        return None
    parents_rc, parents = _git(["rev-list", "--parents", "-n", "1", "HEAD"], cwd=primary)
    parent_tokens = parents.split()
    if parents_rc != EXIT_OK or len(parent_tokens) != 2:
        return None
    if base_sha and parent_tokens[1] != base_sha:
        return None
    subject_rc, subject = _git(["show", "-s", "--format=%s", "HEAD"], cwd=primary)
    if subject_rc != EXIT_OK or subject != _DELIVERY_ANCHOR_SUBJECT:
        return None
    paths_rc, changed = _git(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"], cwd=primary
    )
    if paths_rc != EXIT_OK:
        return None
    if {line for line in changed.splitlines() if line} != expected_paths:
        return None
    return tip


def _delivery_anchor_history_identity(
    primary: Path,
    expected_paths: set[str],
    *,
    base_sha: str | None,
    expected_sha: str | None = None,
) -> str | None:
    """Find a machine-repair anchor commit already contained in ``HEAD``.

    ``_delivery_anchor_identity`` intentionally requires the anchor to be the
    current tip.  Recovery is slightly wider: an unrelated primary advance may
    follow a committed anchor before the manifest receipt is flushed.  The
    commit is still accepted only when its parent, subject, and exact
    changed paths prove it is this wave's anchor.
    """
    if expected_sha:
        candidates = [expected_sha]
    else:
        rc, output = _git(["rev-list", "HEAD"], cwd=primary)
        if rc != EXIT_OK:
            return None
        candidates = [sha for sha in output.splitlines() if sha]
    for candidate in candidates:
        ancestor_rc, _ = _git(
            ["merge-base", "--is-ancestor", candidate, "HEAD"], cwd=primary
        )
        if ancestor_rc != 0:
            continue
        parents_rc, parents = _git(
            ["rev-list", "--parents", "-n", "1", candidate], cwd=primary
        )
        parent_tokens = parents.split()
        if parents_rc != EXIT_OK or len(parent_tokens) != 2:
            continue
        if base_sha and parent_tokens[1] != base_sha:
            continue
        subject_rc, subject = _git(
            ["show", "-s", "--format=%s", candidate], cwd=primary
        )
        if subject_rc != EXIT_OK or subject != _DELIVERY_ANCHOR_SUBJECT:
            continue
        paths_rc, changed = _git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", candidate],
            cwd=primary,
        )
        if paths_rc == EXIT_OK and {
            line for line in changed.splitlines() if line
        } == expected_paths:
            return candidate
    return None


def _delivery_anchor_recovery_is_safe(
    primary: Path, marker: dict[str, Any],
) -> bool:
    """Whether an interrupted anchor can be rebased onto the current primary.

    This path is deliberately narrow: the persisted phase must say that anchor
    started, no ticket may have been applied, and every expected ticket must
    still be present in the staged queue.  Anything less remains a typed guard
    refusal rather than an optimistic retry that could overwrite another wave.
    """
    phases = marker.get("phases")
    anchor_phase = phases.get("anchor") if isinstance(phases, dict) else None
    if not isinstance(anchor_phase, dict):
        return False
    if anchor_phase.get("status") not in {"started", "blocked"}:
        return False
    applied = anchor_phase.get("applied_ticket_ids", marker.get("anchor_ids", []))
    if not isinstance(applied, list) or applied:
        return False
    expected = anchor_phase.get(
        "expected_ticket_ids", marker.get("expected_ticket_ids", [])
    )
    if (not isinstance(expected, list) or not expected
            or any(not isinstance(ticket_id, str) or not ticket_id
                   for ticket_id in expected)):
        return False
    queued = {
        row.get("id") for row in _read_anchor_queue(primary)
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    return set(expected).issubset(queued)


def _delivery_anchor_noop_recovery_is_safe(
    primary: Path,
    marker: dict[str, Any],
    *,
    stored_base: str,
    current_head: str,
) -> bool:
    """Prove that a completed noop can survive a metadata-only primary advance.

    A noop has no anchor commit to rediscover.  Recovery is therefore allowed
    only when its durable receipt proves that the queue was consumed without
    applying tickets, the current tip descends from the recorded base, and the
    intervening commits touched backlog metadata documents only.  This keeps
    the exact-commit and foreign-path refusals for real anchors intact while
    avoiding a fabricated ``anchor_commit_sha`` for a legitimate noop.
    """
    if marker.get("anchor_noop") is not True:
        return False
    if marker.get("anchor_committed") is not False:
        return False
    if marker.get("anchor_commit_sha") is not None:
        return False
    phases = marker.get("phases")
    anchor_phase = phases.get("anchor") if isinstance(phases, dict) else None
    if not isinstance(anchor_phase, dict) or anchor_phase.get("status") != "completed":
        return False
    applied = anchor_phase.get("applied_ticket_ids", marker.get("anchor_ids", []))
    if not isinstance(applied, list) or applied:
        return False
    if anchor_phase.get("queue_state") != "consumed":
        return False
    receipt = anchor_phase.get("acceptance_receipt")
    if not isinstance(receipt, dict) or receipt.get("schema") != "kg.backlog.anchor.v1":
        return False
    if receipt.get("applied") != [] or receipt.get("problems") != []:
        return False
    expected = marker.get("expected_ticket_ids", [])
    if not isinstance(expected, list) or any(
        not isinstance(ticket_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
        for ticket_id in expected
    ):
        return False
    if _read_anchor_queue(primary):
        return False
    ancestor_rc, _ = _git(
        ["merge-base", "--is-ancestor", stored_base, current_head], cwd=primary,
    )
    if ancestor_rc != EXIT_OK:
        return False
    changed_rc, changed = _git(
        ["diff", "--name-only", "--no-renames", stored_base, current_head],
        cwd=primary,
    )
    if changed_rc != EXIT_OK:
        return False
    changed_paths = {path for path in changed.splitlines() if path}
    if not changed_paths:
        return False
    def is_legal_metadata_path(path: str) -> bool:
        if path == "ops/backlog_closed_unverified_baseline.txt":
            return True
        if not (path.startswith("docs/runbook/backlog/")
                and path.endswith(".json")):
            return False
        return "/" not in path[len("docs/runbook/backlog/"):]

    return all(is_legal_metadata_path(path) for path in changed_paths)


def _delivery_anchor_recovery_dirty_allowed(
    primary: Path, manifest_path: Path | None,
) -> bool:
    """Allow only expected backlog documents to survive a partial anchor crash."""
    if manifest_path is None:
        return False
    marker_payload = _delivery_load_json(manifest_path)
    marker = (marker_payload or {}).get("close_wave") if marker_payload else None
    if not isinstance(marker, dict) or not _delivery_anchor_recovery_is_safe(
            primary, marker
    ):
        # A partial anchor may have written the documents before consuming the
        # queue, so the queue proof is intentionally not required here.  The
        # phase/applied proof still must say that nothing was durably consumed.
        phases = marker.get("phases") if isinstance(marker, dict) else None
        anchor_phase = phases.get("anchor") if isinstance(phases, dict) else None
        if not isinstance(anchor_phase, dict) or anchor_phase.get("status") not in {
                "started", "blocked"}:
            return False
        applied = anchor_phase.get("applied_ticket_ids", marker.get("anchor_ids", []))
        if not isinstance(applied, list) or applied:
            return False
    expected = marker.get("expected_ticket_ids", [])
    if not isinstance(expected, list) or any(
        not isinstance(ticket_id, str) or not ticket_id for ticket_id in expected
    ):
        return False
    expected_paths = {
        f"docs/runbook/backlog/{ticket_id}.json" for ticket_id in expected
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
    }
    if len(expected_paths) != len(expected):
        return False
    dirty = _delivery_primary_dirty(primary)
    paths = set(_porcelain_paths("\n".join(dirty)))
    return bool(paths) and paths.issubset(expected_paths)

