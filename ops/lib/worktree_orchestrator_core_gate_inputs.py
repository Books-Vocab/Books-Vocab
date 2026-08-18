"""Gate input inventory, record persistence, and reuse decisions."""

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

_OPS_DIR = Path(__file__).resolve().parent.parent
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))

import worktree_registry as wr  # noqa: E402
import backlog as backlog_tool  # noqa: E402
import backlog_store as backlog_store_config  # noqa: E402
import worktree_campaign as campaign  # noqa: E402
import worktree_gate as gate_logic  # noqa: E402
from lib.provenance import logical_tool_path, sha256_file  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402
from lib import dispatch_preflight  # noqa: E402
from lib.exit_codes import EXIT_BLOCK, EXIT_OK, EXIT_TOOL_ERROR, EXIT_USAGE, EXIT_WARN  # noqa: E402
from lib import worktree_integration_status as integrate_status  # noqa: E402
from lib import worktree_orchestrator_planning as planning  # noqa: E402

SCHEMA = "kg.worktree.orchestrate.v1"
GATE_SCHEMA = "kg.worktree.gate.v1"
GATE_INPUT_SCHEMA = "kg.worktree.gate-input.v1"
GATE_PROGRESS_SCHEMA = "kg.worktree.gate-progress.v1"
FREEZE_SCHEMA = "kg.worktree.freeze.v1"
DELIVERY_SCHEMA = "kg.worktree.delivery.v1"
BASE_DEFAULT = "main"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKTREE_SCRATCH_REL = Path(".cache") / "agent-scratch"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _backlog_store_for_worktree(worktree: str) -> tuple[Path, bool]:
    """Resolve the gate's backlog input without confusing a worktree with primary.

    With the legacy store, a worktree has its own tracked
    ``docs/runbook/backlog`` tree. With an external store, the gate must not list
    the primary checkout's legacy files as if they were the active data plane.
    External state is intentionally marked non-reusable until its own content
    fingerprint is part of the gate contract.
    """
    configured = Path(backlog_tool.DEFAULT_STORE).expanduser().resolve()
    primary = Path(backlog_tool.ROOT).expanduser().resolve()
    if backlog_store_config.is_external_store(configured, primary):
        return configured, True
    return Path(worktree).expanduser().resolve() / BACKLOG_STORE_DIR, False


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind late-defined façade symbols into extracted function globals.

    Extracted helpers retain their original private-name contracts, while the
    executable façade remains the compatibility owner for provenance and patching.
    """
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]


def _gate_record_path(state: str | None, worktree: str) -> Path:
    """Where a gate verdict is recorded so cutover can read it — a per-machine cache
    beside the registry ledger, keyed by the worktree's normalized path."""
    if state:
        base_dir = Path(state).resolve().parent
    else:
        base_dir = wr.default_state_path().parent
    key = hashlib.sha256(_norm(worktree).encode()).hexdigest()[:16]
    return base_dir / "worktree_gates" / f"{key}.json"


def _gate_progress_path(state: str | None, worktree: str) -> Path:
    """Where the live progress sidecar is recorded, separate from the verdict."""
    record_path = _gate_record_path(state, worktree)
    return record_path.with_name(f"{record_path.stem}.progress.json")


def _gate_progress_lock(state: str | None):
    """Serialize progress ownership without adding a second lock-file family."""
    state_path = Path(state).resolve() if state else wr.default_state_path()
    return wr._ledger_lock(state_path)


def _read_gate_progress(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _tracked_paths(worktree: str) -> list[str] | None:
    """Return tracked paths from the tree being gated, or None when it cannot be read.

    Reuse is an optimisation, so an unreadable path inventory is not a reason to make
    a claim about unchanged inputs.  The caller treats None as an unknown scope and
    runs the gate.
    """
    rc, out = _git(["ls-files", "-z"], cwd=worktree)
    if rc != 0:
        return None
    return sorted(p for p in out.split("\0") if p)


def _input_file_digest(worktree: str, paths: list[str]) -> str | None:
    """Hash the exact worktree bytes and modes for a bounded input file set."""
    h = hashlib.sha256()
    try:
        for rel in paths:
            fp = Path(worktree) / rel
            h.update(rel.encode("utf-8", "surrogateescape"))
            h.update(b"\0")
            if fp.is_symlink():
                h.update(b"symlink\0")
                h.update(os.readlink(fp).encode("utf-8", "surrogateescape"))
            elif fp.is_file():
                h.update(b"file\0")
                h.update(fp.read_bytes())
            else:
                h.update(b"missing\0")
            try:
                h.update(str(fp.stat().st_mode & 0o7777).encode("ascii"))
            except OSError:
                h.update(b"stat-missing")
            h.update(b"\0")
    except (OSError, UnicodeError):
        return None
    return h.hexdigest()


_IOS_OPS_COMMON_INPUTS = frozenset({
    "ops/ios_ops.sh",
    # ios_ops.sh sources every ios_ops_* module before dispatch.  The catalog
    # module also sources these three transitively, so a parse/load failure in
    # any of them affects both build and test commands.
    "ops/lib/ios_cache_evict.sh",
    "ops/lib/fixture_dataset_env.sh",
    "ops/lib/userland_compat.sh",
})
_IOS_BUILD_INPUTS = frozenset({
    "ops/ios_build.sh",
    "ops/ios_diagnostics.py",
    "ops/lib/ios_build_progress.sh",
    "ops/lib/ios_install_provenance.sh",
    "ops/lib/ios_lock_wait.sh",
    "ops/lib/ios_run_metrics.sh",
    "ops/lib/ios_run_verdict.sh",
})
_IOS_TEST_INPUTS = frozenset({
    "ops/ios_test.sh",
    "ops/ios_coverage.py",
    "ops/ios_diagnostics.py",
    "ops/ios_device_files.sh",
    "ops/p9_review_calendar_evidence.py",
    "ops/ui_world_manifest.py",
    "ops/uitest_contact_sheet.py",
    "ops/lib/ios_test_discovery.sh",
    "ops/lib/ios_test_failure_verdict.sh",
    "ops/lib/ios_test_cache_root.sh",
    "ops/lib/ios_test_failure_verdict.sh",
    "ops/lib/ios_xctestrun_cache.sh",
    "ops/lib/ios_build_progress.sh",
    "ops/lib/ios_lock_wait.sh",
    "ops/lib/ios_test_video_archive.sh",
    "ops/lib/ios_run_metrics.sh",
    "ops/lib/ios_run_verdict.sh",
    "ops/lib/signal_traps.sh",
})


def _ios_executable_input_files(name: str, tracked: list[str]) -> tuple[str, list[str]] | None:
    """Return a conservative command-specific iOS input surface.

    All iOS commands read the project tree and the common ios_ops dispatcher.  Build
    and test then delegate to different top-level scripts.  Keeping those delegates
    separate is what lets a retry reuse an already-green build after repairing only
    the test runner; shared wrapper/libs still invalidate both, and an unknown iOS
    gate deliberately falls back to the broader category scope below.
    """
    if name in {"ios-build", "ios-build-catalyst"}:
        kind = "tracked-ios-build-surface"
        explicit = _IOS_OPS_COMMON_INPUTS | _IOS_BUILD_INPUTS
    elif name == "ios-test-unit" or name.startswith("ios-test-ui:") or \
            name == "ios-live-demo-uitest-compile":
        kind = "tracked-ios-test-surface"
        explicit = _IOS_OPS_COMMON_INPUTS | _IOS_TEST_INPUTS
    else:
        return None
    files = [p for p in tracked if p.startswith("ios/") or p in explicit or
             p.startswith("ops/lib/ios_ops_") or
             (kind == "tracked-ios-test-surface" and (
                 p.startswith("ops/fixtures/ui_worlds/") or
                 p.startswith("ops/uitest_review_") or
                 p.startswith("ops/catalog_")
             ))]
    return kind, files


def _gate_input_scope(spec: dict[str, Any], worktree: str,
                      changed_files: list[str], tracked: list[str] | None) -> dict[str, Any]:
    """Resolve a conservative, auditable input scope for one gate.

    This is intentionally narrower than the whole repository for expensive gates, but
    broader than the changed paths: the tool being reused may scan a whole subsystem.
    A gate without a defensible scope is explicitly non-reusable rather than silently
    guessed.  The returned descriptor is persisted with the verdict.
    """
    name = str(spec.get("name", ""))
    kind = "unknown"
    files: list[str] = []
    external_backlog = False
    if name == "backlog-validate":
        _store, external_backlog = _backlog_store_for_worktree(worktree)
    if external_backlog:
        kind = "external-store"
    elif tracked is not None:
        if name == "coverage":
            kind = "changed-files"
            files = sorted(changed_files)
        elif name == "backlog-validate":
            kind = "tracked-subsystem"
            files = [p for p in tracked if p == "ops/backlog.py" or
                     (p.startswith(BACKLOG_STORE_DIR) and
                      "/" not in p[len(BACKLOG_STORE_DIR):] and p.endswith(".json"))]
        elif name == "data-plane:ops/docs_lint.sh":
            kind = "tracked-control-plane"
            files = [p for p in tracked if p == "docs/registry.yml" or
                     p.startswith("ops/docs") and p.endswith((".py", ".sh"))]
        elif name in {"docs-lint", "docs-conflict-markers"}:
            kind = "tracked-docs"
            files = [p for p in tracked if p.startswith("docs/") and
                     (p.endswith(".md") or p == "docs/registry.yml")]
            files.extend(p for p in tracked if p.startswith("ops/docs") and
                         p.endswith((".py", ".sh")))
        elif name == "docs-verified-against":
            # Reachability is a property of the repository's commit graph, not only
            # the bytes of the named documents.  Keep this cheap gate honest until a
            # graph fingerprint exists.
            kind = "unknown"
        elif name == "ops-pytest":
            kind = "tracked-subsystem"
            files = [p for p in tracked if p.startswith("ops/") or
                     p.startswith(".github/workflows/")]
        elif name == "ops-python-scan":
            # The scanner reads every tracked Python source, so make that exact
            # repository-wide surface reusable when unrelated files change.
            kind = "tracked-python-source"
            files = [p for p in tracked if p.endswith(".py")]
        elif name.startswith("ops-shell"):
            kind = "tracked-shell-tree"
            files = [p for p in tracked if p.endswith(".sh")]
        elif spec.get("category") == "ios":
            executable = _ios_executable_input_files(name, tracked)
            if executable is not None:
                kind, files = executable
            else:
                # Quality/advisory/unknown iOS gates keep the broad fail-safe scope.
                # A new gate must earn a narrower dependency declaration explicitly.
                kind = "tracked-ios-surface"
                files = [p for p in tracked if p.startswith("ios/") or
                         p.startswith("ops/ios") or p.startswith("ops/lib/ios") or
                         p.startswith("ops/tests/test_ios") or p.startswith("ops/test_ios") or
                         p.startswith("ops/ui_quality") or
                         p.startswith("ops/tests/test_ui_quality")]
        elif spec.get("category") == "backend":
            kind = "tracked-backend-surface"
            files = [p for p in tracked if p.startswith("backend/") or
                     p in {"pyproject.toml", "uv.lock"}]
        elif spec.get("category") == "design-system":
            kind = "tracked-design-system"
            files = [p for p in tracked if p.startswith("design-system/") or
                     p.startswith("ops/verify_design_system") or p.startswith("ops/token") or
                     p.startswith("ops/gen_") or p.startswith("ios/BooksAndVocab/Models/") or
                     p.startswith("ios/BooksAndVocab/UIComponents/") or
                     p in {"backend/static/kg-tokens.css", "backend/static/kg-components.css",
                           "package.json", "package-lock.json"}]

    clean = not bool(_git(["status", "--porcelain", "--untracked-files=all"],
                          cwd=worktree)[1])
    definition = {
        "name": spec.get("name"), "category": spec.get("category"),
        "kind": spec.get("kind"), "level": spec.get("level"),
        "cmd": spec.get("cmd"), "cwd": spec.get("cwd"),
        "files": spec.get("files"),
    }
    descriptor: dict[str, Any] = {
        "schema": GATE_INPUT_SCHEMA, "kind": kind, "files": sorted(files),
        "worktree_clean": clean,
        "definition_fingerprint": hashlib.sha256(
            json.dumps(definition, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")).hexdigest(),
    }
    descriptor["fingerprint"] = (
        _input_file_digest(worktree, descriptor["files"])
        if kind not in {"unknown", "history"} else None
    )
    descriptor["reusable"] = bool(
        kind not in {"unknown", "history", "changed-files", "external-store"}
        and descriptor["fingerprint"] is not None and clean
    )
    return descriptor


def _read_gate_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read the previous live-worktree record without making reuse fail open."""
    if not path.exists():
        return None, "no_prior_record"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "prior_record_unreadable"
    return (payload, None) if isinstance(payload, dict) else (None, "prior_record_invalid")


def _reuse_gate(spec: dict[str, Any], current_input: dict[str, Any],
                previous: dict[str, Any] | None, previous_error: str | None,
                orchestrator: dict[str, Any], base: str = BASE_DEFAULT
                ) -> tuple[dict[str, Any] | None, str]:
    """Return a copied prior result only when every reuse proof is present."""
    if previous is None:
        return None, previous_error or "no_prior_record"
    if not current_input.get("reusable"):
        return None, "input_scope_not_reusable"
    if current_input.get("schema") != GATE_INPUT_SCHEMA:
        return None, "current_input_schema_unknown"
    if previous.get("schema") != GATE_SCHEMA:
        return None, "source_record_schema_unknown"
    if previous.get("base") != base:
        return None, "base_changed"
    old_orchestrator = previous.get("orchestrator")
    if not isinstance(old_orchestrator, dict):
        return None, "source_record_orchestrator_invalid"
    old_orch = old_orchestrator.get("sha256")
    if old_orch != orchestrator.get("sha256"):
        return None, "orchestrator_changed"
    previous_gates = previous.get("gates")
    if not isinstance(previous_gates, list) or any(
            not isinstance(gate, dict) for gate in previous_gates):
        return None, "source_record_gates_invalid"
    prior = next((gate for gate in previous_gates
                  if gate.get("name") == spec.get("name")), None)
    if not isinstance(prior, dict):
        return None, "no_prior_gate"
    if prior.get("status") not in {"pass", "warn"}:
        return None, f"source_status_{prior.get('status', 'missing')}"
    prior_deferral = prior.get("deferral")
    if (prior.get("original_status") == "block"
            or (isinstance(prior_deferral, dict)
                and prior_deferral.get("disposition") == "deferred")):
        # A warning created by an explicit S2 deferral is not a durable green
        # result.  Reusing it without a fresh --defer-gate would silently carry
        # an old red past a later cutover, even if its ticket is now closed or
        # escalated.  The next run must either re-run raw block or explicitly
        # re-admit the current ticket through _validate_gate_deferrals.
        return None, "deferred_failure_requires_explicit_deferral"
    old_input = prior.get("input")
    if not isinstance(old_input, dict):
        return None, "source_record_has_no_input_fingerprint"
    if old_input.get("schema") != GATE_INPUT_SCHEMA:
        return None, "source_input_schema_unknown"
    if old_input.get("kind") != current_input.get("kind"):
        return None, "input_scope_changed"
    if old_input.get("files") != current_input.get("files"):
        return None, "input_file_set_changed"
    if old_input.get("definition_fingerprint") != current_input.get("definition_fingerprint"):
        return None, "gate_definition_changed"
    if old_input.get("fingerprint") != current_input.get("fingerprint"):
        return None, "input_content_changed"
    if old_input.get("worktree_clean") is not True or current_input.get("worktree_clean") is not True:
        return None, "worktree_not_clean"
    copied = dict(prior)
    reuse_metadata = prior.get("reuse")
    if reuse_metadata is not None and not isinstance(reuse_metadata, dict):
        return None, "source_gate_reuse_metadata_invalid"
    source_head = (reuse_metadata or {}).get("source_head") or previous.get("head_sha")
    copied["reused"] = True
    copied["reused_from_head"] = source_head
    copied["reuse"] = {"decision": "reused", "source_head": source_head,
                       "reason": "input_unchanged"}
    copied["input"] = current_input
    copied["summary"] = f"reused from {str(source_head)[:8]}: {prior.get('summary', '')}"
    return copied, "input_unchanged"


def _reuse_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Small, human-readable audit projection for gate and cutover payloads."""
    reused = [{"name": r.get("name"),
               "source_head": r.get("reused_from_head") or r.get("reuse", {}).get("source_head"),
               "reason": r.get("reuse", {}).get("reason")} for r in results
              if r.get("reuse", {}).get("decision") == "reused"]
    rerun = [{"name": r.get("name"), "reason": r.get("reuse", {}).get("reason")}
             for r in results if r.get("reuse", {}).get("decision") != "reused"]
    return {"reused": reused, "rerun": rerun}


def _executed_gate_count(results: list[dict[str, Any]]) -> int:
    """Count gates run by this invocation, excluding reuse and spawn failures."""
    return sum(
        1 for result in results
        if result.get("reuse", {}).get("decision") != "reused"
        and result.get("executed", True) is not False
    )


# Lines worth lifting out of a failed gate's output. Deliberately broad: these gates
# are a zoo — shell harnesses printing `✗`, pytest, TAP producers, bash's own
# `error:` — and a marker set narrow enough to look tidy is one that goes silent for
# whichever tool nobody had in mind. A false positive costs one line of noise; a miss
# costs the re-run this whole mechanism exists to remove.
# Two of these were added on 2026-08-09 after the set went silent on the two gates
# whose silence cost the most (IMP-20260808-8b4690):
#   `✘` U+2718 — Swift Testing's marker, one codepoint away from the `✗` U+2717
#     already here and visually near-identical, so no by-eye review of this tuple
#     was ever going to catch it. Measured on a real ios-test-unit log: 4 lines
#     carried U+2718, 1 carried U+2717.
# The zero-match branch in `_failed_gate_summary` changes how the tail is labelled,
# so a gate whose output uses an unfamiliar failure vocabulary cannot masquerade as a
# named failure.
