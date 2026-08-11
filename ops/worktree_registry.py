#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Worktree registry: a birth→resolution ledger + orphan sentinel for git worktrees.

Every convergence/feature worktree is *born* (register), lives while an agent works
it, and is *resolved* (cutover=merged, or dropped=abandoned). The registry is the
書面登記閉環 the P3 orchestrator drives; `sweep` is the crash-recovery sentinel that
reconciles the ledger against on-disk git reality and proposes what to reclaim —
never destroying unlanded or unsaved work.

Architecture (mirrors the retired ops/converge_board.py, ops/ui_deadcode.py — three layers):
  IO layer      read-only git fact gathering (NEVER mutates git except the explicit
                `sweep --commit` clearance actions). fetch-first. Owns the ONE piece
                of real judgement here: `landed_in_base` computed by TREE-DIFF.
  pure layer    consumed from ops/lib/worktree_state.py (P1): classify(facts)->State
                and unsafe_to_drop(facts)->reason|None. This module NEVER re-implements
                a verdict — it gathers facts and defers every judgement to P1.
  render layer  human table / --json (schema kg.worktree.registry.v1)

⚠ TREE-DIFF CONTAINMENT (the whole point). `landed_in_base` answers "is this ref's
net change already present in base?" It is computed by comparing trees, NOT by
`git cherry` / patch-id. The retired converge_board._cherry_unmerged used `git cherry`, which
went WRONG after a rebase/squash (patch-ids drift) — reporting landed work as
unlanded or vice versa. This tool deliberately uses tree containment so a
squash-merged branch (commit sha differs, content already in base) is correctly
seen as landed. See `landed_in_base`.

Registry state file (per-machine, NEVER committed):
  anchored at  <dirname(git-common-dir)>/.cache/worktree_registry.json
  so every linked worktree shares ONE ledger (like the shared DerivedData anchor).
  schema kg.worktree.registry.v1:
    {"schema": ..., "records": [{path, branch, intent, base, created_at,
                                 status(active|merged|abandoned), resolved_at,
                                 backlog[ticket ids claimed], claimed_at,
                                 handed_back_at, handed_back_sha}]}
  Timestamps are taken in the CLI adapter (--at overrides for tests); the IO/pure
  layers read no clock.

Subcommands (register/hand-back/resolve/sweep are the P3 orchestrator API, not just human):
  register   birth: record a new active worktree     (--path --branch --intent --base
             [--backlog ID...]). --backlog CLAIMS those ticket ids: refused if any is
             already held by another ACTIVE record. Omitting the flag leaves an
             existing claim alone; passing it (even empty) replaces it. A claim lives
             exactly as long as the record is active, so resolve/sweep release it and
             there is no separate release verb.
  list       ledger + live classify of each record   (table / --json)
  resolve    death: strike a worktree active record  (--branch|--path --status)
  hand-back  worker hand-back: stamp the active record with the current branch tip
             (--branch|--path; read-only git, no mutation of the worktree)
  sweep      orphan sentinel: fetch → gather every worktree/branch fact → P1
             classify + unsafe_to_drop → propose a CONSERVATIVE disposition. dry-run
             default; --commit executes clearance (remote branch → worktree remove →
             local branch), gated per-card by unsafe_to_drop.

             Absolute protection (the retired converge convention "main first, never teardown"): the base
             branch (--base, default origin/main, incl. its local branch) and the
             PRIMARY worktree (the main working tree / repo root) are NEVER CLEAR and
             never receive a `branch -D` / `worktree remove` — hard-excluded before any
             classify reasoning (see sweep_guards + _step_touches_protected).

             CLEAR is confined to three shapes; everything else is KEEP:
               (a) dangling landed branch — a branch, no worktree, landed+clean;
               (b) orphan detached worktree — detached, contained-in-base, clean;
               (c) registry-resolved subject — a record already merged/abandoned.
             A landed branch that STILL has a checked-out worktree is KEPT (reclaimable,
             awaiting resolve), never auto-cleared. On --commit, an ACTIVE record whose
             subject was cleared resolves to *merged* (not abandoned); a record whose
             worktree merely vanished is struck abandoned.

Exit codes: 0 ok | 1 partial failure (sweep --commit) | 64 usage error |
            75 claim refused (EX_TEMPFAIL — someone else holds that ticket;
            retry once they resolve). NOTE argparse answers 2 for a malformed
            command line out of this same main, which is why 75 and not 2.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Consume the P1 pure judgement layer — never re-implement a verdict here.
OPS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(OPS_DIR))
sys.path.insert(0, str(OPS_DIR / "lib"))
import worktree_state as ws  # noqa: E402  (ops/lib shared pure module)
import worktree_campaign as wc  # noqa: E402  (campaign reservation pure layer)
from lock_wait import exclusive_lock  # noqa: E402
from lib.exit_codes import EXIT_CLAIMED, EXIT_OK, EXIT_PARTIAL, EXIT_USAGE  # noqa: E402

SCHEMA = "kg.worktree.registry.v1"
# A well-formed register that loses a race for a backlog ticket. It needs a code of
# its own: not EXIT_USAGE, because the caller did nothing wrong; not EXIT_PARTIAL,
# which means a sweep got part-way; not EXIT_OK.
#
# 75 = sysexits' EX_TEMPFAIL, "temporary failure; the user is invited to retry" —
# which is exactly this situation: the same command becomes correct the moment the
# holder resolves. Deliberately NOT 2, though 2 looked free: argparse answers 2 for
# a malformed command line out of THIS SAME `main`, so `--brnach` (a typo) and "that
# ticket is taken" would be indistinguishable, and an agent would drop a ticket
# nobody holds. 2 is also spoken for by the open ruling in IMP-0042, which assigns
# it to "block". The orchestrator maps this to its own EXIT_BLOCK (which is 1, so do
# NOT assume the numbers match anywhere).
STATUS_ACTIVE = "active"
RESOLVE_STATUS = ("merged", "abandoned")  # terminal states a resolve can set
HAND_BACK_SEAL_SCHEMA = "kg.worktree.handback.v1"
HAND_BACK_OUTCOMES = (
    "changed",
    "no-op-existing-fix",
    "changed-but-not-closable",
    "blocked",
    "triage-only",
)
INTEGRABLE_HAND_BACK_OUTCOMES = {"changed", "no-op-existing-fix"}
GREEN_ACCEPTANCE_STATUSES = {
    "green", "pass", "passed", "ok", "confirmed-fixed", "confirmed_fixed",
}


# ============================================================================
# IO layer — read-only git. The ONLY writes live in `sweep --commit` clearance.
# ============================================================================
def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.stdout.strip()


def _git_ok(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out = proc.stdout.strip()
    if proc.returncode != 0 and proc.stderr.strip():
        out = (out + "\n" + proc.stderr.strip()).strip()
    return proc.returncode, out


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _normalised_acceptance_status(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


def _acceptance_is_green(value: Any) -> bool:
    return _normalised_acceptance_status(value) in GREEN_ACCEPTANCE_STATUSES


def _load_hand_back_outcomes(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("outcomes")
    if not isinstance(payload, list):
        raise ValueError("outcomes JSON must be a list or an object with an outcomes list")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("every hand-back outcome must be an object")
    return payload


def _review_receipt_problems(worktree: Path, base_sha: str, tip_sha: str) -> list[dict[str, Any]]:
    script = worktree / "ops" / "review_audit.sh"
    if not script.is_file():
        return [{"kind": "review-audit-missing", "path": str(script)}]
    if not os.access(script, os.X_OK):
        return [{"kind": "review-audit-unreadable", "path": str(script),
                 "detail": "review audit script is not executable"}]
    try:
        proc = subprocess.run(
            [str(script), "--rev-range", f"{base_sha}..{tip_sha}"],
            cwd=str(worktree), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return [{"kind": "review-audit-unreadable", "path": str(script),
                 "detail": str(exc)}]
    if proc.returncode == 0:
        return []
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return [{"kind": "review-audit-failed", "rc": proc.returncode,
             "output_tail": output[-1200:]}]


def _outcome_problems(
    outcomes: list[dict[str, Any]],
    *,
    claimed: list[str],
    base_sha: str,
    worktree: Path,
    tip_sha: str,
    run_review: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    problems: list[dict[str, Any]] = []
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in outcomes:
        ticket_id = str(item.get("ticket_id") or "").strip()
        outcome = str(item.get("outcome") or "").strip()
        status = str(item.get("acceptance_status") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not ticket_id:
            problems.append({"kind": "ticket-id-missing"})
            continue
        if ticket_id in seen:
            problems.append({"kind": "duplicate-ticket", "ticket_id": ticket_id})
            continue
        seen.add(ticket_id)
        if ticket_id not in claimed:
            problems.append({"kind": "ticket-not-claimed", "ticket_id": ticket_id})
        if outcome not in HAND_BACK_OUTCOMES:
            problems.append({"kind": "outcome-invalid", "ticket_id": ticket_id,
                             "outcome": outcome, "allowed": list(HAND_BACK_OUTCOMES)})
        if not status:
            problems.append({"kind": "acceptance-status-missing", "ticket_id": ticket_id})
        if not evidence:
            problems.append({"kind": "evidence-missing", "ticket_id": ticket_id})
        if outcome in {"changed", "no-op-existing-fix"} and not _acceptance_is_green(status):
            problems.append({"kind": "acceptance-not-green", "ticket_id": ticket_id,
                             "outcome": outcome, "acceptance_status": status})
        if outcome in {"changed-but-not-closable", "blocked", "triage-only"} \
                and _acceptance_is_green(status):
            problems.append({"kind": "nonintegrable-outcome-is-green",
                             "ticket_id": ticket_id, "outcome": outcome})

        provenance = item.get("provenance")
        canonical: dict[str, Any] = {
            "ticket_id": ticket_id,
            "outcome": outcome,
            "acceptance_status": status,
            "evidence": evidence,
        }
        if provenance is not None:
            if not isinstance(provenance, dict):
                problems.append({"kind": "provenance-invalid", "ticket_id": ticket_id})
            else:
                kind = str(provenance.get("kind") or "").strip()
                sha = str(provenance.get("sha") or "").strip()
                source = str(provenance.get("source") or "").strip()
                canonical["provenance"] = {"kind": kind, "sha": sha}
                if source:
                    canonical["provenance"]["source"] = source
                if outcome == "no-op-existing-fix":
                    if kind not in {"base-ancestor", "fixed-elsewhere"} or not sha:
                        problems.append({"kind": "no-op-provenance-missing",
                                         "ticket_id": ticket_id})
                    elif kind == "base-ancestor":
                        rc, _ = _git_ok(["merge-base", "--is-ancestor", sha, base_sha],
                                        cwd=worktree)
                        if rc != 0:
                            problems.append({"kind": "provenance-not-base-ancestor",
                                             "ticket_id": ticket_id, "sha": sha,
                                             "base_sha": base_sha})
                    elif not source:
                        problems.append({"kind": "fixed-elsewhere-source-missing",
                                         "ticket_id": ticket_id})
        elif outcome == "no-op-existing-fix":
            problems.append({"kind": "no-op-provenance-missing", "ticket_id": ticket_id})
        normalised.append(canonical)

    expected = set(claimed)
    if seen != expected:
        problems.append({"kind": "ticket-set-mismatch", "claimed": sorted(expected),
                         "outcomes": sorted(seen)})
    if run_review and any(item.get("outcome") == "changed" for item in normalised):
        problems.extend(_review_receipt_problems(worktree, base_sha, tip_sha))
    return problems, sorted(normalised, key=lambda item: item["ticket_id"])


def _seal_body(record: dict[str, Any], *, base_sha: str, tip_sha: str,
               outcomes: list[dict[str, Any]], handed_back_at: str) -> dict[str, Any]:
    return {
        "schema": HAND_BACK_SEAL_SCHEMA,
        "record": {
            "branch": record.get("branch"),
            "path": _norm(record.get("path") or ""),
            "base": record.get("base"),
            "backlog": sorted(record.get("backlog") or []),
            "claimed_at": record.get("claimed_at"),
        },
        "base_sha": base_sha,
        "tip_sha": tip_sha,
        "outcomes": outcomes,
        "handed_back_at": handed_back_at,
    }


def _seal_with_digest(body: dict[str, Any]) -> dict[str, Any]:
    seal = dict(body)
    seal["digest"] = hashlib.sha256(_canonical_json(body)).hexdigest()
    return seal


def _child_receipt_from_manifest(
    record: dict[str, Any], *, campaign_id: str, partition_id: str,
    role: str, manifest_path: Path, tip_sha: str,
    seal: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project a completed child integration manifest into an immutable receipt."""
    if role != "child" or not campaign_id or not partition_id:
        raise ValueError("child receipt requires role=child, campaign id, and partition id")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("child integration manifest must be a JSON object")
    manifest_head = payload.get("head_sha") or payload.get("integration_head")
    if manifest_head != tip_sha:
        raise ValueError(
            f"child manifest head {manifest_head!r} does not equal hand-back tip {tip_sha!r}"
        )
    branches = payload.get("branches") or payload.get("consumed_children")
    if (not isinstance(branches, list) or not branches
            or any(not isinstance(item, str) or not item for item in branches)
            or len(set(branches)) != len(branches)):
        raise ValueError("child integration manifest must list source branches")
    campaign_manifest_digest = (
        payload.get("campaign_manifest_digest")
        or payload.get("manifest_digest")
        or (payload.get("campaign") or {}).get("manifest_digest")
    )
    if not isinstance(campaign_manifest_digest, str) or not campaign_manifest_digest:
        raise ValueError("child integration manifest has no campaign_manifest_digest")
    completed_manifest_digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    outcomes = list((seal or {}).get("outcomes") or record.get("handback_outcomes") or [])
    ticket_ids = sorted(str(item) for item in (record.get("backlog") or []))
    if not outcomes or sorted(str(item.get("ticket_id")) for item in outcomes
                              if isinstance(item, dict)) != ticket_ids:
        raise ValueError("child manifest/outcome seal does not cover the claimed tickets")
    return {
        "schema": wc.CHILD_RECEIPT_SCHEMA,
        "role": role,
        "campaign_id": campaign_id,
        "partition_id": partition_id,
        "branch": record.get("branch"),
        "manifest_digest": completed_manifest_digest,
        "campaign_manifest_digest": campaign_manifest_digest,
        "manifest_head_sha": manifest_head,
        "source_branches": sorted(branches),
        "ticket_ids": ticket_ids,
        "outcomes": outcomes,
        "outcome_seal_digest": (seal or {}).get("digest"),
        "completed_manifest": str(manifest_path.resolve()),
    }


def validate_handback_seal(record: dict[str, Any], *, repo: Path | None = None,
                           require_seal: bool = True) -> list[dict[str, Any]]:
    seal = record.get("handback_seal")
    if not isinstance(seal, dict):
        return ([{"kind": "handback-seal-missing", "branch": record.get("branch")}]
                if require_seal else [])
    digest = seal.get("digest")
    body = {key: value for key, value in seal.items() if key != "digest"}
    problems: list[dict[str, Any]] = []
    if not isinstance(digest, str) or digest != hashlib.sha256(_canonical_json(body)).hexdigest():
        problems.append({"kind": "handback-seal-digest-mismatch",
                         "branch": record.get("branch")})
    if body.get("schema") != HAND_BACK_SEAL_SCHEMA:
        problems.append({"kind": "handback-seal-schema-invalid"})
    expected_tip = record.get("handed_back_sha")
    if body.get("tip_sha") != expected_tip:
        problems.append({"kind": "handback-seal-tip-mismatch",
                         "sealed": body.get("tip_sha"), "recorded": expected_tip})
    if body.get("handed_back_at") != record.get("handed_back_at"):
        problems.append({"kind": "handback-seal-time-mismatch",
                         "sealed": body.get("handed_back_at"),
                         "recorded": record.get("handed_back_at")})
    expected_base = record.get("base_sha")
    if not expected_base or body.get("base_sha") != expected_base:
        problems.append({"kind": "handback-seal-base-mismatch",
                         "sealed": body.get("base_sha"), "recorded": expected_base})
    identity = body.get("record")
    if not isinstance(identity, dict) or identity.get("branch") != record.get("branch") \
            or identity.get("path") != _norm(record.get("path") or "") \
            or identity.get("base") != record.get("base") \
            or identity.get("claimed_at") != record.get("claimed_at") \
            or identity.get("backlog") != sorted(record.get("backlog") or []):
        problems.append({"kind": "handback-seal-identity-mismatch",
                         "branch": record.get("branch")})
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list):
        problems.append({"kind": "handback-seal-outcomes-invalid"})
    else:
        outcome_ids = [str(item.get("ticket_id") or "") for item in outcomes
                       if isinstance(item, dict)]
        if len(outcome_ids) != len(set(outcome_ids)) \
                or set(outcome_ids) != set(record.get("backlog") or []):
            problems.append({"kind": "handback-seal-ticket-set-mismatch",
                             "sealed": sorted(outcome_ids),
                             "claimed": sorted(record.get("backlog") or [])})
        metadata_invalid: list[dict[str, Any]] = []
        ticket_id_invalid = False
        for index, item in enumerate(outcomes):
            if not isinstance(item, dict):
                problems.append({"kind": "handback-outcome-not-integrable",
                                 "ticket_id": None, "outcome": None})
                continue
            ticket_id = item.get("ticket_id")
            raw_outcome = item.get("outcome")
            if not isinstance(ticket_id, str):
                ticket_id_invalid = True
                metadata_invalid.append({"kind": "handback-outcome-metadata-invalid",
                                         "field": "ticket_id", "index": index,
                                         "type": type(ticket_id).__name__})
            if not isinstance(raw_outcome, str):
                metadata_invalid.append({"kind": "handback-outcome-metadata-invalid",
                                         "field": "outcome", "index": index,
                                         "type": type(raw_outcome).__name__})
            outcome_integrable = (
                isinstance(raw_outcome, str)
                and raw_outcome in INTEGRABLE_HAND_BACK_OUTCOMES
            )
            if not outcome_integrable:
                problems.append({"kind": "handback-outcome-not-integrable",
                                 "ticket_id": ticket_id,
                                 "outcome": raw_outcome})
        invalid_items = [
            {"kind": "handback-outcome-item-invalid", "index": index,
             "type": type(item).__name__}
            for index, item in enumerate(outcomes)
            if not isinstance(item, dict)
        ]
        problems.extend(invalid_items)
        problems.extend(metadata_invalid)
        if (not invalid_items and not ticket_id_invalid and repo is not None
                and expected_base and body.get("tip_sha")):
            semantic_problems, checked = _outcome_problems(
                outcomes, claimed=list(record.get("backlog") or []),
                base_sha=expected_base, worktree=repo, tip_sha=body["tip_sha"],
                run_review=False,
            )
            seal_ticket_set_problem = any(
                item.get("kind") == "handback-seal-ticket-set-mismatch"
                for item in problems
            )
            problems.extend(
                item for item in semantic_problems
                if not (seal_ticket_set_problem and item.get("kind") == "ticket-set-mismatch")
            )
            if checked != sorted(outcomes, key=lambda item: item.get("ticket_id", "")):
                problems.append({"kind": "handback-seal-outcome-normalisation-mismatch"})
    return problems


def repo_root() -> Path:
    return Path(_git(["rev-parse", "--show-toplevel"]))


def common_anchor() -> Path:
    """dirname of the git common dir — the main working tree's root, shared by every
    linked worktree. The registry lives under here so all worktrees see one ledger."""
    cd = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
    if not cd:
        cd = _git(["rev-parse", "--git-common-dir"])
    return Path(cd).resolve().parent


def default_state_path() -> Path:
    return common_anchor() / ".cache" / "worktree_registry.json"


def fetch_origin() -> None:
    """fetch-first: base (main) moves under us. Best-effort — offline tolerated."""
    subprocess.run(
        ["git", "fetch", "origin", "--prune"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---- tree-diff containment (the anti-`git cherry` core) ---------------------
def _merge_base(a: str, b: str) -> str | None:
    rc, out = _git_ok(["merge-base", a, b])
    if rc != 0 or not out:
        return None
    return out.strip()


def _diff_names(a: str, b: str) -> tuple[bool, set[str]]:
    """(ok, changed_paths) for `git diff --name-only a b`. ok=False on git error
    (without --exit-code the rc is 0 whether or not there is a diff, so a non-zero
    rc means a genuine failure → the caller must fail safe)."""
    rc, out = _git_ok(["diff", "--name-only", a, b])
    if rc != 0:
        return (False, set())
    return (True, {ln for ln in out.splitlines() if ln})


def landed_in_base(base: str, ref: str) -> bool:
    """TREE-DIFF containment: is `ref`'s net change already present in `base`?

    NOT computed via `git cherry` / patch-id — those drift after a rebase/squash and
    are the exact bug (the retired converge_board._cherry_unmerged) this tool must not repeat.

    Method (fork-relative tree comparison):
      mb      = merge-base(base, ref)                      # the fork point
      changed = paths ref changed since mb  (diff mb..ref) # ref's contribution
      differ  = paths where ref and base trees differ now  (diff ref..base)
    ref is landed ⟺ NONE of ref's changed paths differ between ref and base, i.e.
    base already holds ref's version of everything ref touched (adds/mods/deletes):
        changed.isdisjoint(differ)

    This is correct for a squash-merge (ref's commit sha absent from base, yet its
    content present): `changed` = the touched paths, `differ` = ∅ ⇒ landed. A branch
    ancestor of base: `changed` = ∅ ⇒ landed. A branch with unique work: its path is
    in both sets ⇒ not landed. Fails safe (not landed) on unrelated histories or any
    git error so a bad read never green-lights dropping work."""
    mb = _merge_base(base, ref)
    if mb is None:
        return False  # unrelated histories / error → fail safe
    ok, changed = _diff_names(mb, ref)
    if not ok:
        return False
    if not changed:
        return True  # ref net-changed nothing vs the fork point → fully in base
    ok2, differ = _diff_names(ref, base)
    if not ok2:
        return False
    return changed.isdisjoint(differ)


# ---- topology / worktree facts ---------------------------------------------
def _rev_list_count(base: str, ref: str) -> tuple[int, int]:
    """(behind, ahead) = (commits in base not ref, commits in ref not base)."""
    rc, out = _git_ok(["rev-list", "--left-right", "--count", f"{base}...{ref}"])
    if rc != 0 or not out:
        return (0, 0)
    parts = out.split()
    if len(parts) != 2:
        return (0, 0)
    return (int(parts[0]), int(parts[1]))


def _head_epoch(ref: str, cwd: Path | None = None) -> int | None:
    """Commit time (unix seconds) of `ref`'s tip, or None if unresolved."""
    rc, out = _git_ok(["log", "-1", "--format=%ct", ref], cwd=cwd)
    if rc != 0 or not out:
        return None
    try:
        return int(out.splitlines()[0])
    except (ValueError, IndexError):
        return None


def _is_dirty(worktree_path: str) -> bool:
    rc, out = _git_ok(["status", "--porcelain"], cwd=Path(worktree_path))
    return rc == 0 and bool(out.strip())


def _upstream(branch: str) -> str | None:
    up = _git(["for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch}"])
    return up or None


def _local_branches() -> list[str]:
    return [
        b for b in _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"]).splitlines()
        if b
    ]


def _remote_branch_exists(name: str, remote: str = "origin") -> bool:
    rc, out = _git_ok(["ls-remote", "--heads", remote, name])
    return rc == 0 and bool(out.strip())


def parse_worktree_porcelain(out: str) -> list[dict[str, Any]]:
    """Pure parser for `git worktree list --porcelain` — split out so the record
    shape can be asserted on a string literal instead of a real repo."""
    worktrees: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    for line in out.splitlines():
        if not line:
            if cur:
                worktrees.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line == "prunable" or line.startswith("prunable "):
            cur["prunable"] = line[len("prunable "):] or "prunable"
        elif line == "locked" or line.startswith("locked "):
            # a locked worktree is exempt from `git worktree prune` even when broken,
            # so "broken" and "reapable" are not the same question
            cur["locked"] = line[len("locked "):] or "locked"
    if cur:
        worktrees.append(cur)
    return worktrees


def _worktrees() -> list[dict[str, Any]]:
    """Parse `git worktree list --porcelain` into records with keys
    path / head / branch (short) / detached / bare / prunable.

    `prunable` carries git's own reason string (e.g. "gitdir file points to
    non-existent location") and is the signal that a worktree's administrative link
    is broken while its directory survives — an interrupted teardown. It is recorded
    because git's answer here stays truthful when `rev-parse` no longer is: repository
    discovery walks UP out of a `.git`-less directory and reports the ENCLOSING
    checkout instead (see worktree_orchestrate._worktree_entry)."""
    return parse_worktree_porcelain(_git(["worktree", "list", "--porcelain"]))


# ---- sweep guards: base branch + primary worktree are NEVER swept ----------
def sweep_guards(base: str) -> tuple[str | None, set[str]]:
    """(primary_worktree_path_normalized, protected_branch_names) — the two things a
    sweep must NEVER tear down (the retired converge convention: "main first, never teardown").

      * primary worktree = the MAIN working tree (the repo root), always the first
        entry of `git worktree list`. Removing it destroys the repository; a running
        session lives there. Never a CLEAR candidate, never `worktree remove`-d.
      * base branch = the `--base` ref (and, since --base defaults to origin/main, the
        LOCAL branch it tracks). Deleting it (`branch -D main`) is catastrophic. We
        also protect whatever branch the primary worktree currently has checked out.

    This is a hard, absolute exclusion applied BEFORE any classify/CLEAR reasoning."""
    wts = _worktrees()
    primary = _norm(wts[0]["path"]) if wts else None
    protected: set[str] = set()
    if base:
        protected.add(base)
        if "/" in base:               # origin/main -> also protect the local branch 'main'
            protected.add(base.split("/", 1)[1])
    if wts and wts[0].get("branch"):  # whatever the main working tree has checked out
        protected.add(wts[0]["branch"])
    return primary, protected


def _step_touches_protected(
    gargs: list[str], primary_path: str | None, protected_branches: set[str]
) -> bool:
    """Safety net: True if this git clearance step would delete the base branch or
    remove the primary worktree. CLEAR never contains protected subjects, so this
    should never fire — belt-and-suspenders so a bug upstream can never emit a
    repository-destroying `branch -D main` / `worktree remove <repo>`.

    The subject is located by skipping option tokens rather than by index. Reading a
    fixed `gargs[2]` made this silently blind to `worktree remove --force <primary>`
    — it inspected the string `--force` — which is precisely the argv shape the
    orchestrator's resolve emits, so the one caller most in need of the net was the
    one it did not cover."""
    def _subject(argv: list[str], start: int) -> str | None:
        for tok in argv[start:]:
            if not tok.startswith("-"):
                return tok
        return None

    if gargs[:2] == ["branch", "-D"]:
        subject = _subject(gargs, 2)
        if subject is not None and subject in protected_branches:
            return True
    if gargs[:2] == ["worktree", "remove"]:
        subject = _subject(gargs, 2)
        if subject is not None and primary_path and _norm(subject) == primary_path:
            return True
    if gargs[:1] == ["push"] and "--delete" in gargs and gargs[-1] in protected_branches:
        return True
    return False


# ============================================================================
# facts assembly — gather read-only facts, defer EVERY verdict to P1.
# ============================================================================
def build_facts(
    base: str,
    *,
    name: str | None,
    detached: bool,
    worktree_path: str | None,
    head_sha: str | None,
    now_epoch: int,
    live_window: int,
    registered_active: bool,
) -> dict[str, Any]:
    """Produce ONE P1 `facts` dict (see worktree_state.py contract). The ref to
    inspect is the branch (when on a branch) or the detached HEAD sha."""
    ref = name if (name and not detached) else (head_sha or "HEAD")
    landed = landed_in_base(base, ref)
    behind, ahead = _rev_list_count(base, ref)
    dirty = _is_dirty(worktree_path) if worktree_path else False
    head_epoch = _head_epoch(ref, cwd=Path(worktree_path) if worktree_path else None)
    head_age = (now_epoch - head_epoch) if head_epoch is not None else None
    has_origin = bool(name) and _upstream(name) is not None

    # unique_commits (P1 REQUIRED): landed → 0. Not landed → the topological ahead
    # count, but at least 1 so P1.classify never mis-files uncontained work as MERGED
    # (P1's own belt-and-suspenders would still refuse the drop, but this keeps
    # classify honest: uncontained work reads ACTIVE/DIVERGED, not MERGED).
    if landed:
        unique = 0
    else:
        unique = ahead if ahead > 0 else 1

    return {
        "name": name,
        "detached": detached,
        "dirty": dirty,
        "ahead": ahead,               # advisory
        "behind": behind,
        "unique_commits": unique,     # REQUIRED
        "landed_in_base": landed,     # REQUIRED (tree-diff)
        "head_age_s": head_age,
        "live_window_s": live_window,
        "has_worktree": worktree_path is not None,
        "has_origin": has_origin,     # advisory
        "registered_active": registered_active,
    }


def _norm(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _subject(
    facts: dict[str, Any],
    *,
    kind: str,
    worktree_path: str | None,
    head_sha: str | None,
    tracked: bool,
    registry_status: str | None,
    protected: bool,
    protected_reason: str | None,
    excluded: bool = False,
) -> dict[str, Any]:
    """Classify + safety-gate ONE subject via P1, attach a CONSERVATIVE disposition.

    Safety floors (any forces KEEP, in this precedence):
      protected            base branch / primary worktree — NEVER swept (hard rule).
      excluded             the worktree the sweep was invoked FROM (--exclude-current):
                           an orchestrator running a preflight sweep from inside a live
                           worktree must never propose clearing itself. Highest KEEP
                           floor after `protected` — applies even to an otherwise-CLEAR
                           detached orphan whose root == the caller's cwd.
      unsafe_to_drop != None  live / dirty / unlanded / uncontained — dropping loses
                           work (P1 verdict; classify alone can orphan commits, so the
                           unsafe gate is mandatory).

    Given a safe (unsafe is None), non-protected subject, CLEAR is confined to three
    shapes; EVERYTHING else is KEEP:
      (a) dangling landed branch   — a branch, no worktree, landed+clean.
      (b) orphan detached worktree — detached, contained-in-base, clean.
      (c) registry-resolved        — a record already resolved (merged/abandoned);
                                     honoured even with an open worktree.
    In particular a landed branch that STILL has a checked-out worktree is KEPT
    (reclaimable, awaiting resolve) — never auto-cleared, lest an agent's live
    worktree be removed out from under it."""
    state = ws.classify(facts)
    unsafe = ws.unsafe_to_drop(facts)
    name = facts.get("name")
    has_wt = bool(facts.get("has_worktree"))
    detached = bool(facts.get("detached"))
    landed = bool(facts.get("landed_in_base"))

    keep_reason: str | None = None
    if protected:
        disposition = "KEEP"
        keep_reason = protected_reason or "base branch / primary worktree — never teardown"
    elif excluded:
        disposition = "KEEP"
        keep_reason = "excluded: sweep invoked from this worktree (--exclude-current) — never self-clear"
    elif unsafe is not None:
        disposition = "KEEP"
        keep_reason = unsafe
    elif registry_status in RESOLVE_STATUS:
        disposition = "CLEAR"                                   # (c) operator resolved it
    elif detached and has_wt and landed:
        disposition = "CLEAR"                                   # (b) contained detached orphan
    elif (not has_wt) and landed and name is not None:
        disposition = "CLEAR"                                   # (a) dangling landed branch
    else:
        disposition = "KEEP"
        if landed and has_wt and name is not None:
            keep_reason = "landed, reclaimable — resolve to clear (open worktree)"
        else:
            keep_reason = "not eligible for clearance (kept by default)"

    label = name
    if label is None:
        label = f"(detached {(head_sha or '')[:8]})"
    return {
        "kind": kind,
        "name": name,
        "label": label,
        "path": worktree_path,
        "state": state.value,
        "landed": landed,
        "dirty": bool(facts.get("dirty")),
        "detached": detached,
        "ahead": facts.get("ahead", 0),
        "behind": facts.get("behind", 0),
        "unique": facts.get("unique_commits", 0),
        "has_origin": bool(facts.get("has_origin")),
        "tracked": tracked,
        "untracked": not tracked,
        "registry_status": registry_status,
        "protected": bool(protected),
        "excluded": bool(excluded),
        "unsafe": unsafe,
        "keep_reason": keep_reason,
        "disposition": disposition,
    }


def gather_sweep(
    base: str,
    now_epoch: int,
    live_window: int,
    records: list[dict[str, Any]],
    *,
    exclude_path: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconcile the on-disk git reality against the active ledger.

    Returns (subjects, stale_entries):
      subjects       one card per worktree (branch or detached) + per worktree-less
                     local branch, each with a CLEAR/KEEP disposition. The base branch
                     and primary worktree are always present but forced KEEP+protected.
      stale_entries  active records whose worktree path no longer exists on disk AND
                     whose branch is NOT itself being cleared (a cleared dangling-landed
                     branch resolves to merged via nit1, not abandoned).

    exclude_path   normalized path of the worktree the sweep was invoked FROM
                   (--exclude-current). Its worktree subject is force-KEPT (excluded=True)
                   so an orchestrator's preflight sweep never proposes clearing itself.
    """
    active = [r for r in records if r.get("status") == STATUS_ACTIVE]
    reg_paths = {_norm(r["path"]) for r in active if r.get("path")}
    reg_branches = {r["branch"] for r in active if r.get("branch")}

    # resolved (merged/abandoned) records → registry_status for CLEAR shape (c).
    resolved_by_branch: dict[str, str] = {}
    resolved_by_path: dict[str, str] = {}
    for r in records:
        st = r.get("status")
        if st in RESOLVE_STATUS:
            if r.get("branch"):
                resolved_by_branch[r["branch"]] = st
            if r.get("path"):
                resolved_by_path[_norm(r["path"])] = st

    def _registry_status(name: str | None, path: str | None) -> str | None:
        # an active record wins; else the branch/path's last resolved status, if any.
        if (name is not None and name in reg_branches) or (path is not None and _norm(path) in reg_paths):
            return STATUS_ACTIVE
        if name is not None and name in resolved_by_branch:
            return resolved_by_branch[name]
        if path is not None and _norm(path) in resolved_by_path:
            return resolved_by_path[_norm(path)]
        return None

    primary_path, protected_branches = sweep_guards(base)

    def _protection(is_primary: bool, branch: str | None) -> tuple[bool, str | None]:
        bits = []
        if is_primary:
            bits.append("primary worktree (main working tree)")
        if branch is not None and branch in protected_branches:
            bits.append(f"base branch {branch!r}")
        if not bits:
            return False, None
        return True, " / ".join(bits) + " — never teardown (main-first invariant)"

    subjects: list[dict[str, Any]] = []
    seen_branches: set[str] = set()
    seen_paths: set[str] = set()

    # 1. worktree-carried subjects (branch or detached)
    for wt in _worktrees():
        if wt.get("bare"):
            continue
        path = wt["path"]
        npath = _norm(path)
        seen_paths.add(npath)
        branch = wt.get("branch")
        detached = bool(wt.get("detached"))
        if branch:
            seen_branches.add(branch)
        is_primary = primary_path is not None and npath == primary_path
        protected, protected_reason = _protection(is_primary, branch)
        excluded = exclude_path is not None and npath == exclude_path
        registered = npath in reg_paths or (branch is not None and branch in reg_branches)
        facts = build_facts(
            base, name=branch, detached=detached, worktree_path=path,
            head_sha=wt.get("head"), now_epoch=now_epoch, live_window=live_window,
            registered_active=registered,
        )
        subjects.append(_subject(
            facts, kind="worktree", worktree_path=path, head_sha=wt.get("head"),
            tracked=registered, registry_status=_registry_status(branch, path),
            protected=protected, protected_reason=protected_reason, excluded=excluded,
        ))

    # 2. local branches with no worktree
    for b in _local_branches():
        if b in seen_branches:
            continue
        protected, protected_reason = _protection(False, b)
        registered = b in reg_branches
        facts = build_facts(
            base, name=b, detached=False, worktree_path=None, head_sha=None,
            now_epoch=now_epoch, live_window=live_window, registered_active=registered,
        )
        subjects.append(_subject(
            facts, kind="branch", worktree_path=None, head_sha=None, tracked=registered,
            registry_status=_registry_status(b, None),
            protected=protected, protected_reason=protected_reason,
        ))

    # 3. stale registry entries — active record whose worktree path vanished AND whose
    #    branch is NOT being cleared (nit1: a cleared dangling-landed branch is resolved
    #    to merged, so it must not be double-counted here and struck as abandoned).
    cleared_branches = {s["name"] for s in subjects if s["disposition"] == "CLEAR" and s.get("name")}
    stale: list[dict[str, Any]] = []
    for r in active:
        p = r.get("path")
        if not p or _norm(p) in seen_paths:
            continue
        if r.get("branch") in cleared_branches:
            continue
        if not Path(p).exists():
            stale.append(r)

    return subjects, stale


# ============================================================================
# registry state IO (local JSON ledger — NOT git-tracked)
# ============================================================================
def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "records": []}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError(f"malformed registry state at {path}")
    data.setdefault("schema", SCHEMA)
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    # atomic: write a sibling temp then os.replace, so a reader (or a crash mid-write)
    # never sees a half-written ledger — the swap is a single rename syscall.
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body)
        os.replace(tmp, path)
    finally:
        # a raise between write and replace would otherwise strand the temp; the
        # replace consumes it on success, so this only fires on the failure path.
        tmp.unlink(missing_ok=True)


def _campaign_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the mutable campaign reservation list without inventing a second store."""
    reservations = state.setdefault("campaign_reservations", [])
    if not isinstance(reservations, list):
        raise ValueError("malformed campaign_reservations in registry state")
    return reservations


def _restore_bytes(path: Path, original: bytes | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)


def reserve_campaign(
    state_path: Path,
    request: dict[str, Any],
    *,
    current_base: str,
    backlog_entries: list[dict[str, Any]] | dict[str, dict[str, Any]] | None = None,
    backlog_reader: Callable[[], list[dict[str, Any]] | dict[str, dict[str, Any]]] | None = None,
    base_reader: Callable[[], str] | None = None,
    commit: bool = False,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Validate and optionally atomically persist one campaign reservation.

    The registry lock covers the second read of active claims/reservations, the
    validator, the manifest write, and the ledger write.  A failed transaction
    restores both files byte-for-byte, which is stronger than merely returning
    ``ok=false`` after a partial reservation.
    """
    state_path = Path(state_path).resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = now_iso or datetime.now(timezone.utc).isoformat()
    with _ledger_lock(state_path):
        state = load_state(state_path)
        locked_base = (base_reader() if base_reader is not None else current_base).strip()
        if not locked_base:
            raise ValueError("base ref could not be resolved inside registry lock")
        # The selector is part of the reservation transaction.  A caller may
        # provide a loader so a backlog groom/status change that happened while
        # this process waited for the registry lock is observed before commit.
        fresh_backlog_entries = (
            backlog_reader() if backlog_reader is not None else backlog_entries
        )
        if fresh_backlog_entries is None:
            raise ValueError("backlog entries or a backlog reader is required")
        reservations = _campaign_state(state)
        campaign_id = request.get("campaign_id") if isinstance(request, dict) else None
        existing = next((r for r in reservations if r.get("campaign_id") == campaign_id), None)
        manifest_path = wc.campaign_manifest_path(state_path, campaign_id) if isinstance(campaign_id, str) else None
        canonical = wc.canonical_manifest(request) if isinstance(request, dict) else request

        if existing is not None:
            if existing.get("coordinator") != request.get("coordinator"):
                problems = [{"kind": "campaign-already-owned", "message": "campaign has another coordinator",
                             "campaign": campaign_id, "owner": existing.get("coordinator")}]
            else:
                existing_manifest = None
                try:
                    existing_manifest = json.loads(manifest_path.read_text()) if manifest_path else None
                except (OSError, ValueError):
                    pass
                if existing_manifest != canonical:
                    problems = [{"kind": "campaign-request-drift", "message": "existing campaign manifest differs",
                                 "campaign": campaign_id}]
                else:
                    problems = wc.validate_manifest(
                        request,
                        current_base=locked_base,
                        backlog_entries=fresh_backlog_entries,
                        existing_reservations=reservations,
                    )
                    if not problems:
                        return {"ok": True, "mode": "idempotent", "existing": True,
                                **wc.reservation_summary(existing)}
        else:
            problems = []

        if not existing:
            active_reservations = list(reservations)
            for record in state.get("records") or []:
                if record.get("status") == STATUS_ACTIVE and record.get("backlog"):
                    active_reservations.append({
                        "campaign_id": f"active:{record.get('branch')}",
                        "ticket_ids": list(record.get("backlog") or []),
                    })
            problems = wc.validate_manifest(
                request,
                current_base=locked_base,
                backlog_entries=fresh_backlog_entries,
                existing_reservations=active_reservations,
            )
        if problems:
            return {"ok": False, "mode": "committed" if commit else "dry-run",
                    "campaign_id": campaign_id, "coordinator": request.get("coordinator") if isinstance(request, dict) else None,
                    "conflicts": problems}
        if manifest_path is None:
            return {"ok": False, "mode": "dry-run", "conflicts":[{
                "kind": "invalid-campaign-id", "message": "campaign_id is required"}]}

        reservation = wc.reservation_record(canonical, str(manifest_path), timestamp)
        summary = wc.reservation_summary(reservation)
        result = {"ok": True, "mode": "committed" if commit else "dry-run",
                  **summary, "reservation": reservation}
        if not commit:
            return result

        state_before = state_path.read_bytes() if state_path.exists() else None
        manifest_before = manifest_path.read_bytes() if manifest_path.exists() else None
        manifest_dir = manifest_path.parent
        dir_existed = manifest_dir.exists()
        try:
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path.write_bytes(wc.json_bytes(canonical))
            reservations.append(reservation)
            save_state(state_path, state)
        except Exception:
            reservations[:] = [r for r in reservations if r is not reservation]
            _restore_bytes(state_path, state_before)
            _restore_bytes(manifest_path, manifest_before)
            if not dir_existed:
                try:
                    manifest_dir.rmdir()
                except OSError:
                    pass
            raise
        return result


def claim_campaign_ticket(
    state_path: Path,
    *,
    campaign_id: str,
    partition_id: str,
    branch: str,
    path: str,
    intent: str,
    base: str,
    base_sha: str | None = None,
    base_reader: Callable[[], str] | None = None,
    repo_root_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Atomically transfer one campaign reservation into an active record."""
    state_path = Path(state_path).resolve()
    timestamp = now_iso or datetime.now(timezone.utc).isoformat()
    path = os.path.abspath(path)
    with _ledger_lock(state_path):
        state = load_state(state_path)
        reservation = next(
            (item for item in state.get("campaign_reservations") or []
             if item.get("campaign_id") == campaign_id), None,
        )
        if reservation is None:
            return {"ok": False, "reason": "campaign reservation not found",
                    "campaign_id": campaign_id}
        actual_base = (
            base_reader() if base_reader is not None
            else base_sha if base_sha is not None
            else _git_base_for_claim(base, repo_root_path=repo_root_path)
        ).strip()
        if not actual_base:
            return {"ok": False, "reason": "campaign base is unreadable",
                    "campaign_id": campaign_id}
        if reservation.get("base") != actual_base:
            return {"ok": False, "reason": "campaign base is stale",
                    "expected": reservation.get("base"), "actual": actual_base}
        partition = (reservation.get("partitions") or {}).get(partition_id)
        if not isinstance(partition, dict):
            return {"ok": False, "reason": "campaign partition not found",
                    "campaign_id": campaign_id, "partition": partition_id}
        ticket_ids = list(partition.get("ticket_ids") or [])
        claimed = partition.setdefault("claimed", {})
        ticket = next((item for item in ticket_ids if item not in claimed), None)
        if ticket is None:
            return {"ok": False, "reason": "campaign partition has no remaining reservation",
                    "campaign_id": campaign_id, "partition": partition_id}
        matches = [
            record for record in state.get("records") or []
            if record.get("status") == STATUS_ACTIVE
            and (record.get("branch") == branch
                 or _norm(record.get("path") or "") == _norm(path)
                 or ticket in (record.get("backlog") or []))
        ]
        if matches:
            return {"ok": False, "reason": "worktree identity or ticket already active",
                    "conflicts": [{"branch": r.get("branch"), "path": r.get("path"),
                                   "backlog": list(r.get("backlog") or [])}
                                  for r in matches]}
        record = {
            "path": path, "branch": branch, "intent": intent, "base": base,
            "created_at": timestamp, "base_sha": actual_base,
            "status": STATUS_ACTIVE, "resolved_at": None,
            "backlog": [ticket], "claimed_at": timestamp,
            # Campaign metadata is the bridge from a child worktree to the
            # parent integration contract.  Ordinary opens leave these absent;
            # campaign opens stamp them atomically with the ticket claim.
            "campaign_id": campaign_id,
            "partition_id": partition_id,
            "role": "child",
        }
        claimed[ticket] = {"branch": branch, "path": path, "claimed_at": timestamp}
        state.setdefault("records", []).append(record)
        save_state(state_path, state)
        return {"ok": True, "record": record, "ticket": ticket,
                "reservation": wc.reservation_summary(reservation)}


def _git_base_for_claim(
    base: str, *, repo_root_path: Path | str | None = None,
) -> str:
    """Resolve a base ref from an explicit repo root, never a ledger path guess."""
    root = Path(repo_root_path).resolve() if repo_root_path else repo_root()
    rc, output = _git_ok(["rev-parse", base], cwd=root)
    return output if rc == EXIT_OK else ""


def release_campaign_claim(
    state_path: Path,
    *,
    campaign_id: str,
    partition_id: str,
    ticket_id: str,
    branch: str,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Undo an opening child claim and its active record in one locked RMW."""
    state_path = Path(state_path).resolve()
    timestamp = now_iso or datetime.now(timezone.utc).isoformat()
    with _ledger_lock(state_path):
        state = load_state(state_path)
        for reservation in state.get("campaign_reservations") or []:
            if reservation.get("campaign_id") != campaign_id:
                continue
            partition = (reservation.get("partitions") or {}).get(partition_id)
            claimed = (partition or {}).get("claimed") or {}
            claim = claimed.get(ticket_id)
            if claim is None or claim.get("branch") != branch:
                return {"ok": False, "reason": "campaign claim not owned by branch"}
            claimed.pop(ticket_id, None)
            for record in state.get("records") or []:
                if record.get("status") == STATUS_ACTIVE and record.get("branch") == branch:
                    record["status"] = "abandoned"
                    record["resolved_at"] = timestamp
                    break
            save_state(state_path, state)
            return {"ok": True, "campaign_id": campaign_id, "partition": partition_id,
                    "ticket": ticket_id, "released": True}
        return {"ok": False, "reason": "campaign not found"}


@contextmanager
def _ledger_lock(state_path: Path):
    """Exclusive lock over one ledger's whole read-modify-write, so concurrent
    register / resolve / sweep from parallel hands-off sessions cannot lose each
    other's updates (the ledger is a shared JSON file; unlocked RMW is last-writer-
    wins). An advisory flock on a sidecar `<ledger>.lock` — the kernel drops it when
    the fd closes, so a crashed holder never leaves a stale lock (unlike an O_EXCL
    marker file). Blocking acquire with no timeout is safe: every writer's critical
    section terminates (register/resolve are a small-JSON load+mutate+save; sweep also
    runs git under the lock, so it can hold for seconds — still bounded), and a dead
    holder auto-releases, so no deadlock can form. Advisory only — every WRITER must
    take it; load_state stays lock-free for read-only callers, which the atomic
    save_state protects from torn reads."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    with exclusive_lock(lock_path, label=f"worktree-ledger:{state_path.name}"):
        yield


def _try_acquire_ledger_lock_nb(state_path: Path) -> bool:
    """True if the ledger lock is currently free (non-blocking acquire+release),
    False if another open file description holds it. Inspection/tests only — never a
    substitute for holding `_ledger_lock` across a real read-modify-write."""
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def claim_integration_sources(
    state_path: Path,
    *,
    source_refs: dict[str, str],
    integration_branch: str,
    integration_slug: str,
    claimed_at: str,
) -> dict[str, Any]:
    """Reserve handed-back source branches for exactly one integration owner.

    Ticket claims prevent two workers from doing the same ticket; this is the
    corresponding boundary one level up. Without it, two round coordinators can
    legally consume the same immutable hand-back SHA into two integration trees.
    The reservation is all-or-nothing and shares the canonical ledger lock.
    """
    state_path = Path(state_path).resolve()
    with _ledger_lock(state_path):
        state = load_state(state_path)
        records = state["records"]
        active: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if record.get("status") == STATUS_ACTIVE and record.get("branch"):
                active.setdefault(str(record["branch"]), []).append(record)

        conflicts: list[dict[str, Any]] = []
        selected: list[dict[str, Any]] = []
        owners = active.get(integration_branch, [])
        if len(owners) != 1:
            conflicts.append({
                "branch": integration_branch,
                "reason": "integration branch has no unique active registry record",
                "active_records": len(owners),
            })
        elif owners[0].get("teardown_started_at"):
            conflicts.append({
                "branch": integration_branch,
                "reason": "integration branch teardown already started",
                "teardown_started_at": owners[0].get("teardown_started_at"),
            })
        for branch, expected_sha in source_refs.items():
            matches = active.get(branch, [])
            if len(matches) != 1:
                conflicts.append({
                    "branch": branch,
                    "reason": "source branch has no unique active registry record",
                    "active_records": len(matches),
                })
                continue
            record = matches[0]
            if record.get("teardown_started_at"):
                conflicts.append({
                    "branch": branch,
                    "reason": "source branch teardown already started",
                    "teardown_started_at": record.get("teardown_started_at"),
                })
                continue
            handed_back = record.get("handed_back_sha")
            if handed_back != expected_sha:
                conflicts.append({
                    "branch": branch, "reason": "hand-back SHA changed",
                    "expected_sha": expected_sha, "handed_back_sha": handed_back,
                })
                continue
            owner = record.get("integration_owner")
            if owner and owner.get("branch") != integration_branch:
                conflicts.append({
                    "branch": branch,
                    "reason": "source branch already reserved by another integration",
                    "owner": owner,
                })
                continue
            selected.append(record)

        if conflicts:
            return {"ok": False, "integration_branch": integration_branch,
                    "claimed": [], "conflicts": conflicts}

        claim = {"branch": integration_branch, "slug": integration_slug,
                 "claimed_at": claimed_at}
        for record in selected:
            record["integration_owner"] = {**claim,
                                           "source_sha": record["handed_back_sha"]}
        save_state(state_path, state)
        return {"ok": True, "integration_branch": integration_branch,
                "claimed": sorted(source_refs), "conflicts": []}


def claim_parent_integration(
    state_path: Path,
    *,
    campaign_id: str,
    parent_branch: str,
    parent_slug: str,
    base_sha: str,
    request_id: str,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Atomically reserve one complete campaign child set for a parent.

    The snapshot is deliberately computed while holding the canonical registry
    lock.  A refusal never appends a parent record or mutates any child receipt;
    a same-request retry returns the existing immutable snapshot.
    """
    state_path = Path(state_path).resolve()
    timestamp = now_iso or datetime.now(timezone.utc).isoformat()
    with _ledger_lock(state_path):
        state = load_state(state_path)
        reservations = state.get("campaign_reservations") or []
        reservation = next(
            (item for item in reservations if item.get("campaign_id") == campaign_id),
            None,
        )
        if not isinstance(reservation, dict):
            return {"ok": False, "mode": "refused", "campaign_id": campaign_id,
                    "problems": [{"kind": "campaign-reservation-missing",
                                  "message": "campaign reservation does not exist"}]}

        parent_reservations = state.setdefault("parent_reservations", [])
        if not isinstance(parent_reservations, list):
            return {"ok": False, "mode": "refused", "campaign_id": campaign_id,
                    "problems": [{"kind": "parent-reservations-malformed",
                                  "message": "registry parent_reservations is not a list"}]}
        active = [item for item in parent_reservations
                  if isinstance(item, dict)
                  and item.get("campaign_id") == campaign_id
                  and item.get("status") == STATUS_ACTIVE]
        owner = {"branch": parent_branch, "slug": parent_slug,
                 "request_id": request_id}
        for existing in active:
            existing_owner = existing.get("owner") or {}
            if existing.get("base_sha") != base_sha:
                return {"ok": False, "mode": "refused", "campaign_id": campaign_id,
                        "problems": [{"kind": "stale-base",
                                      "message": "existing parent reservation is based on another primary",
                                      "expected": existing.get("base_sha"), "actual": base_sha}]}
            same_request = existing_owner.get("request_id") == request_id
            same_owner = (existing_owner.get("branch") == parent_branch
                          and existing_owner.get("slug") == parent_slug)
            if same_request or same_owner:
                snapshot = existing.get("snapshot")
                if isinstance(snapshot, dict):
                    return {"ok": True, "mode": "idempotent", "campaign_id": campaign_id,
                            "parent": existing, **snapshot}
            return {"ok": False, "mode": "refused", "campaign_id": campaign_id,
                    "problems": [{"kind": "parent-already-owned",
                                  "message": "campaign already has another parent owner",
                                  "owner": existing_owner}]}

        snapshot = wc.parent_child_snapshot(
            reservation, state.get("records") or [],
            campaign_id=campaign_id, base_sha=base_sha,
        )
        if not snapshot.get("ok"):
            return {"ok": False, "mode": "refused", "campaign_id": campaign_id,
                    "snapshot": snapshot, "problems": snapshot.get("problems") or []}
        parent = {
            "schema": wc.PARENT_RESERVATION_SCHEMA,
            "campaign_id": campaign_id,
            "base_sha": base_sha,
            "owner": owner,
            "status": STATUS_ACTIVE,
            "created_at": timestamp,
            "snapshot": snapshot,
        }
        parent_reservations.append(parent)
        # Keep a single owner projection on the campaign reservation.  The full
        # child snapshot remains immutable under parent_reservations.
        reservation["parent_owner"] = owner
        save_state(state_path, state)
        return {"ok": True, "mode": "committed", "campaign_id": campaign_id,
                "parent": parent, **snapshot}


def release_parent_integration(
    state_path: Path,
    *,
    campaign_id: str,
    parent_branch: str,
    parent_slug: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Release only this parent owner; child records and receipts remain intact."""
    state_path = Path(state_path).resolve()
    timestamp = now_iso or datetime.now(timezone.utc).isoformat()
    with _ledger_lock(state_path):
        state = load_state(state_path)
        released = []
        for parent in state.get("parent_reservations") or []:
            if not isinstance(parent, dict) or parent.get("status") != STATUS_ACTIVE:
                continue
            owner = parent.get("owner") or {}
            if parent.get("campaign_id") != campaign_id or owner.get("branch") != parent_branch:
                continue
            if parent_slug is not None and owner.get("slug") != parent_slug:
                continue
            parent["status"] = "aborted"
            parent["aborted_at"] = timestamp
            released.append(parent)
        if released:
            for reservation in state.get("campaign_reservations") or []:
                if reservation.get("campaign_id") == campaign_id:
                    reservation.pop("parent_owner", None)
            save_state(state_path, state)
        return {"ok": True, "released": released, "campaign_id": campaign_id}


def release_integration_sources(state_path: Path, *, integration_branch: str) -> list[str]:
    """Release active source reservations owned by an aborted integration."""
    state_path = Path(state_path).resolve()
    with _ledger_lock(state_path):
        state = load_state(state_path)
        released: list[str] = []
        for record in state["records"]:
            owner = record.get("integration_owner") or {}
            if record.get("status") == STATUS_ACTIVE \
                    and owner.get("branch") == integration_branch:
                released.append(str(record.get("branch")))
                record.pop("integration_owner", None)
        if released:
            save_state(state_path, state)
        return sorted(released)


def integration_sources_owned_by(state_path: Path, integration_branch: str) -> list[str]:
    """Read active source branches still assigned to an integration branch."""
    state = load_state(Path(state_path).resolve())
    return sorted(
        str(record.get("branch"))
        for record in state.get("records") or []
        if record.get("status") == STATUS_ACTIVE
        and (record.get("integration_owner") or {}).get("branch") == integration_branch
    )


# ============================================================================
# CLI adapter — the ONLY place a clock is read (or --at overrides it).
# ============================================================================
def _parse_at(at: str) -> datetime:
    at = at.strip()
    if at.isdigit():
        return datetime.fromtimestamp(int(at), tz=timezone.utc)
    dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_now(at: str | None) -> tuple[int, str]:
    """(epoch_seconds, iso8601) for 'now'. --at overrides the clock for tests."""
    if at:
        dt = _parse_at(at)
        return int(dt.timestamp()), dt.isoformat()
    now = datetime.now(timezone.utc)
    return int(now.timestamp()), now.isoformat()


def _state_path(args: argparse.Namespace) -> Path:
    return Path(args.state).resolve() if args.state else default_state_path()


# ============================================================================
# render layer
# ============================================================================
def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    sep = "  "
    out = [sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append(sep.join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        out.append(sep.join(cell.ljust(widths[i]) for i, cell in enumerate(r)))
    return "\n".join(out)


def _short_path(p: str | None) -> str:
    if not p:
        return "-"
    parts = Path(p).parts
    return "…/" + "/".join(parts[-2:]) if len(parts) >= 2 else p


# ============================================================================
# subcommands
# ============================================================================
def _normalise_tickets(raw: list[str] | None) -> tuple[list[str], list[str]]:
    """Strip surrounding whitespace; refuse anything that is not shaped like an id.

    The conflict check is exact string comparison, which it has to be — backlog ids
    carry a lowercase sha suffix (`IMP-20260807-b9526c`), so case-folding them would
    invent ids that do not exist. That leaves near-misses claiming nothing at all,
    silently: measured, `IMP-0001`, ` IMP-0001` and `imp-0001` were three separate
    tickets and all three registers succeeded. Whitespace is trimmed because it is
    unambiguously a typo; a wrong-case stream is REFUSED rather than guessed at,
    because guessing means rewriting the id an agent asked for.

    Deliberately not "does this id exist in the backlog store": the registry does not
    depend on `backlog.py`, and a shape check is the strongest thing available here
    that does not invent that dependency.
    """
    if raw is None:
        return [], []
    cleaned = [tok.strip() for tok in raw]
    ok = [tok for tok in cleaned if re.fullmatch(r"[A-Z]{2,6}-\S+", tok)]
    bad = [tok for tok in cleaned if tok not in ok]
    return ok, bad


def cmd_register(args: argparse.Namespace) -> int:
    _, now_iso = resolve_now(args.at)
    path = os.path.abspath(args.path)
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]
    base_path = Path(path)
    if base_path.is_dir():
        base_rc, recorded_base_sha = _git_ok(
            ["rev-parse", "--verify", f"{args.base}^{{commit}}"], cwd=base_path,
        )
        recorded_base_sha = recorded_base_sha if base_rc == 0 else None
    else:
        # `open` registers before `git worktree add`, so the target path is not
        # born yet. `main` resolves this before taking the ledger lock; keeping
        # the result on the parsed args preserves immutable base provenance while
        # preventing every contended claim from spawning git in the critical
        # section. A direct caller that bypasses `main` gets no guessed base.
        recorded_base_sha = getattr(args, "_recorded_base_sha", None)

    # upsert-by-branch/path among ACTIVE records (idempotent for the orchestrator):
    # a re-register of a live worktree refreshes its intent/base/path in place.
    #
    # A branch-match and a DISTINCT path-match can BOTH be active (branch B_old lives
    # at this path; branch B was checked out elsewhere). Updating only the first would
    # leave two active records sharing one path. So collapse ALL matches: keep the
    # first as the survivor, and terminally close the rest (displaced by a re-checkout
    # — not merged, hence "abandoned"). This holds the invariant INDUCTIVELY: register
    # is the sole creator of active records, so if it never lets the incoming branch
    # OR path collide with a surviving active peer, then "at most one active record
    # per branch AND per path" holds across the whole ledger. It only reconciles
    # matches to THIS branch/path — an unrelated pre-existing collision is cleared when
    # register next touches it, or by sweep.
    matches = [
        r for r in records
        if r.get("status") == STATUS_ACTIVE
        and (r.get("branch") == args.branch
             or (r.get("path") and _norm(r["path"]) == _norm(path)))
    ]
    if args.exclusive and matches:
        conflicts = [
            {"branch": r.get("branch"), "path": r.get("path"),
             "backlog": list(r.get("backlog") or []),
             "claimed_at": r.get("claimed_at")}
            for r in matches
        ]
        payload = {
            "schema": SCHEMA, "action": "refused",
            "reason": "worktree identity already active",
            "branch": args.branch, "path": path, "conflicts": conflicts,
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"✗ [{args.branch}] or {path} is already active; exclusive "
                  "registration is only for a new worktree birth", file=sys.stderr)
        return EXIT_CLAIMED
    # ---- claim: at most one ACTIVE record may hold a given backlog ticket ----
    #
    # This check lives here, and not in a wrapper around register.
    #
    # The hard constraint, verified: `_ledger_lock` is a blocking flock taken on a
    # fresh fd per entry, and flock belongs to the open file description rather than
    # the process — a second acquire from the same process blocks forever with no
    # subprocess to kill. Since the orchestrator's `_registry` runs `wr.main` IN
    # PROCESS, a wrapper that took the lock and then called `main` would deadlock.
    #
    # What that does NOT rule out (an earlier version of this comment claimed it
    # did): an outer caller CAN take `_ledger_lock` itself and then call
    # `cmd_register` directly, and `_registry_mutation` in the orchestrator shows a
    # real subprocess boundary is available too. Both were measured to work. The
    # reason to put it here anyway is smaller and truer — the claim and the record
    # it belongs to are one fact, so they should be written by one function inside
    # the one critical section `main` already takes, rather than by two that have to
    # agree about a lock.
    #
    # Checked against every OTHER active record — `matches` are excluded because
    # they are precisely the records this call is about to become or abandon.
    #
    # Stated honestly, because "taking over" is doing some work there: `matches`
    # includes a record displaced by PATH, which may be a different, live branch.
    # Measured — feat-a@/p1 holding IMP-0001 and feat-b@/p2 holding IMP-0002, then
    # `register feat-a /p2 --backlog IMP-0002` succeeds: feat-b is abandoned and its
    # ticket changes hands with no refusal. That is the pre-existing collapse rule
    # (one active record per path) doing its job, and it is only reachable by calling
    # `register` directly with a path that is already occupied — `open` refuses an
    # existing path and `adopt` reads the branch from git. It is not a hole the claim
    # opened, but it IS a way a claim moves without anyone being told.
    wanted, malformed = _normalise_tickets(args.backlog)
    if malformed:
        print(f"✗ not backlog ids: {', '.join(malformed)} — expected <STREAM>-<rest> "
              f"with an UPPERCASE stream (IMP / APP). Ids are compared exactly, so "
              f"`imp-0001` would silently be a different ticket from `IMP-0001` and "
              f"claim nothing.", file=sys.stderr)
        return EXIT_USAGE
    if wanted:
        conflicts = [
            {"branch": r.get("branch"), "path": r.get("path"),
             "backlog": sorted(set(r.get("backlog") or []) & set(wanted)),
             "claimed_at": r.get("claimed_at")}
            for r in records
            # identity, not `r not in matches`: `in` compares dicts by value, so
            # two distinct records that happen to be equal would exclude each other
            if r.get("status") == STATUS_ACTIVE and not any(r is m for m in matches)
            and set(r.get("backlog") or []) & set(wanted)
        ]
        if conflicts:
            # Return before any mutation. A refusal that had already half-written
            # would be worse than not checking: the loser would both be told no
            # and be recorded as holding something.
            payload = {"schema": SCHEMA, "action": "refused",
                       "reason": "backlog ticket already claimed",
                       "branch": args.branch, "wanted": wanted, "conflicts": conflicts}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                for c in conflicts:
                    print(f"✗ {', '.join(c['backlog'])} already claimed by "
                          f"[{c['branch']}] at {c['path']}", file=sys.stderr)
            return EXIT_CLAIMED

    if matches:
        # the branch is the ledger's identity key, so the branch-match record is the
        # survivor (this branch moved worktrees); whatever else held the target path
        # is the displaced one. Falls back to the sole path-match when no branch-match.
        rec = next((r for r in matches if r.get("branch") == args.branch), matches[0])
        displaced = [r for r in matches if r is not rec]
        rec.update({
            "path": path, "branch": args.branch,
            "intent": args.intent, "base": args.base,
        })
        if base_path.is_dir():
            branch_rc, branch_tip = _git_ok(
                ["rev-parse", "--verify", f"{args.branch}^{{commit}}"], cwd=base_path,
            )
            if branch_rc == 0 and branch_tip and recorded_base_sha:
                merge_rc, inferred_base_sha = _git_ok(
                    ["merge-base", branch_tip, recorded_base_sha], cwd=base_path,
                )
                if merge_rc == 0 and inferred_base_sha:
                    stored_base_sha = rec.get("base_sha")
                    stored_rc, _ = _git_ok(
                        ["merge-base", "--is-ancestor", stored_base_sha or "", branch_tip],
                        cwd=base_path,
                    ) if stored_base_sha else (1, "")
                    if not stored_base_sha or stored_rc != 0:
                        rec["base_sha"] = inferred_base_sha
        if not rec.get("base_sha") and recorded_base_sha:
            rec["base_sha"] = recorded_base_sha
        # Only when the flag was given. `rec.update` above preserves keys it does
        # not name, so an omitted --backlog leaves the claim standing — which is
        # the behaviour register's idempotence needs (the orchestrator re-registers
        # live records) and the one a reader is least likely to guess. Passing the
        # flag REPLACES the claim, including with an empty list to give it up.
        if args.backlog is not None:
            rec["backlog"] = wanted
            rec["claimed_at"] = now_iso if wanted else None
        for d in displaced:
            d["status"] = "abandoned"
            d["resolved_at"] = now_iso
            d["note"] = f"superseded by re-register of {args.branch} at {path}"
        verb = "updated"
    else:
        rec = {
            "path": path, "branch": args.branch, "intent": args.intent,
            "base": args.base, "created_at": now_iso,
            "base_sha": recorded_base_sha,
            "status": STATUS_ACTIVE, "resolved_at": None,
            "backlog": wanted, "claimed_at": now_iso if wanted else None,
        }
        records.append(rec)
        verb = "registered"

    save_state(state_path, state)
    if args.json:
        print(json.dumps({"schema": SCHEMA, "action": verb, "record": rec},
                         indent=2, ensure_ascii=False))
    else:
        print(f"✓ {verb} [{args.branch}] intent={args.intent!r} base={args.base}")
        print(f"  path: {path}")
        print(f"  ledger: {state_path}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]

    enriched: list[dict[str, Any]] = []
    for r in records:
        view = dict(r)
        if r.get("status") == STATUS_ACTIVE and r.get("branch"):
            now_epoch, _ = resolve_now(args.at)
            facts = build_facts(
                r.get("base") or "main", name=r["branch"], detached=False,
                worktree_path=(r["path"] if r.get("path") and Path(r["path"]).exists() else None),
                head_sha=None, now_epoch=now_epoch, live_window=args.live_window,
                registered_active=True,
            )
            view["live_state"] = ws.classify(facts).value
            view["landed"] = bool(facts["landed_in_base"])
            view["worktree_present"] = bool(r.get("path") and Path(r["path"]).exists())
        enriched.append(view)

    if args.json:
        print(json.dumps({"schema": SCHEMA, "ledger": str(state_path), "records": enriched,
                          "campaign_reservations": [wc.reservation_summary(r)
                                                     for r in state.get("campaign_reservations") or []]},
                         indent=2, ensure_ascii=False))
        return EXIT_OK

    if not records:
        print(f"(empty ledger: {state_path})")
        return EXIT_OK
    headers = ["branch", "backlog", "claimed", "intent", "base", "status", "live",
               "wt", "created", "resolved"]
    rows = []
    for v in enriched:
        rows.append([
            str(v.get("branch") or "-"),
            # who holds which ticket is the question this ledger is now asked most
            # often ("is anyone on IMP-xxxx?"), so it is a column and not a --json-only
            # field. Resolved records keep theirs as history; the `status` column is
            # what says whether it is still held.
            ",".join(v.get("backlog") or []) or "-",
            # `claimed_at` needs a reader HERE, not once the board exists. Nothing
            # reclaims a claim automatically (preflight's sweep is dry-run by
            # default), so "how long has this been held" is the only signal that
            # separates a live worktree from one whose agent died — and a field with
            # no reader is a field that drifts.
            str(v.get("claimed_at") or "-")[:19],
            str(v.get("intent") or "-"),
            str(v.get("base") or "-"),
            str(v.get("status") or "-"),
            str(v.get("live_state") or "-"),
            ("yes" if v.get("worktree_present") else "-") if v.get("status") == STATUS_ACTIVE else "-",
            str(v.get("created_at") or "-")[:19],
            str(v.get("resolved_at") or "-")[:19],
        ])
    print(f"# ledger: {state_path}\n")
    print(_table(headers, rows))
    return EXIT_OK


def cmd_hand_back(args: argparse.Namespace) -> int:
    """Record the exact commit a worker handed back to the integrator.

    This is deliberately a registry mutation, not a git mutation: the worker has
    already committed its work, and this command only proves which checked-out tip
    it is returning.  Integration later compares this stamp with the source branch
    tip in the primary checkout, so a worker that kept editing after hand-back cannot
    be silently integrated under an old receipt.
    """
    _, now_iso = resolve_now(args.at)
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]

    if args.path is not None:
        target_path = _norm(args.path)
    elif args.branch is None:
        target_path = _norm(str(repo_root()))
    else:
        target_path = None
    candidates = [
        r for r in records
        if r.get("status") == STATUS_ACTIVE
        and ((args.branch is None or r.get("branch") == args.branch)
             and (target_path is None
                  or (r.get("path") and _norm(r["path"]) == target_path)))
    ]
    if not candidates:
        selector = f"branch={args.branch}" if args.branch else f"path={target_path}"
        msg = f"no active registry record matches {selector}"
        payload = {"schema": SCHEMA, "action": "refused", "reason": msg}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"✗ hand-back refused: {msg}", file=sys.stderr)
        return EXIT_USAGE
    if len(candidates) != 1:
        msg = "hand-back selector matches multiple active registry records"
        payload = {"schema": SCHEMA, "action": "refused", "reason": msg,
                   "records": candidates}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"✗ hand-back refused: {msg}", file=sys.stderr)
        return EXIT_USAGE

    rec = candidates[0]
    worktree = Path(rec["path"])
    if not worktree.is_dir():
        msg = f"registered worktree is missing: {worktree}"
        payload = {"schema": SCHEMA, "action": "refused", "reason": msg,
                   "record": rec}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"✗ hand-back refused: {msg}", file=sys.stderr)
        return EXIT_PARTIAL

    rc, actual_branch = _git_ok(["branch", "--show-current"], cwd=worktree)
    if rc != 0 or actual_branch != rec.get("branch"):
        msg = (f"registered worktree is not on its recorded branch: expected "
               f"{rec.get('branch')!r}, found {actual_branch or '(detached)'}")
        payload = {"schema": SCHEMA, "action": "refused", "reason": msg,
                   "record": rec, "actual_branch": actual_branch}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"✗ hand-back refused: {msg}", file=sys.stderr)
        return EXIT_PARTIAL

    rc, tip_sha = _git_ok(["rev-parse", "--verify", "HEAD^{commit}"], cwd=worktree)
    if rc != 0 or not tip_sha or "\n" in tip_sha:
        msg = f"cannot read a single commit tip from {worktree}: {tip_sha or '(empty)'}"
        payload = {"schema": SCHEMA, "action": "refused", "reason": msg,
                   "record": rec}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"✗ hand-back refused: {msg}", file=sys.stderr)
        return EXIT_PARTIAL

    seal = None
    if args.outcomes:
        base_sha = rec.get("base_sha")
        refusal: list[dict[str, Any]] = []
        if not base_sha:
            refusal.append({"kind": "recorded-base-sha-missing"})
        dirty_rc, dirty = _git_ok(["status", "--porcelain=v1"], cwd=worktree)
        if dirty_rc != 0 or dirty:
            refusal.append({"kind": "worktree-dirty", "files": dirty.splitlines()})
        try:
            raw_outcomes = _load_hand_back_outcomes(Path(args.outcomes))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raw_outcomes = []
            refusal.append({"kind": "outcomes-unreadable", "detail": str(exc)})
        if base_sha:
            outcome_problems, normalised = _outcome_problems(
                raw_outcomes, claimed=list(rec.get("backlog") or []),
                base_sha=base_sha, worktree=worktree, tip_sha=tip_sha,
                run_review=True,
            )
            refusal.extend(outcome_problems)
            if any(item.get("outcome") == "changed" for item in normalised):
                diff_rc, diff_output = _git_ok(
                    ["diff", "--quiet", f"{base_sha}..{tip_sha}"], cwd=worktree,
                )
                if diff_rc == 0:
                    refusal.append({"kind": "changed-outcome-has-no-diff",
                                    "base_sha": base_sha, "tip_sha": tip_sha})
                elif diff_rc > 1:
                    refusal.append({"kind": "changed-diff-unreadable",
                                    "detail": diff_output})
            if not refusal:
                body = _seal_body(rec, base_sha=base_sha, tip_sha=tip_sha,
                                  outcomes=normalised, handed_back_at=now_iso)
                seal = _seal_with_digest(body)
        if refusal:
            payload = {"schema": SCHEMA, "action": "refused",
                       "reason": "hand-back outcome validation failed",
                       "problems": refusal, "record": rec}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print("✗ hand-back refused: outcome validation failed", file=sys.stderr)
            return EXIT_PARTIAL

    child_metadata = any(getattr(args, key, None) is not None
                         for key in ("campaign", "partition", "role", "manifest"))
    if child_metadata:
        campaign_id = getattr(args, "campaign", None)
        partition_id = getattr(args, "partition", None)
        role = getattr(args, "role", None)
        manifest_arg = getattr(args, "manifest", None)
        if not (campaign_id and partition_id and role == "child" and manifest_arg):
            msg = "child receipt needs --campaign, --partition, --role child, and --manifest"
            payload = {"schema": SCHEMA, "action": "refused", "reason": msg,
                       "record": rec}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"✗ hand-back refused: {msg}", file=sys.stderr)
            return EXIT_USAGE
        try:
            rec["child_receipt"] = _child_receipt_from_manifest(
                rec, campaign_id=str(campaign_id), partition_id=str(partition_id),
                role=str(role), manifest_path=Path(manifest_arg), tip_sha=tip_sha,
                seal=seal,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            msg = f"child integration manifest is not a valid receipt source: {exc}"
            payload = {"schema": SCHEMA, "action": "refused", "reason": msg,
                       "record": rec}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"✗ hand-back refused: {msg}", file=sys.stderr)
            return EXIT_PARTIAL

    rec["handed_back_at"] = now_iso
    rec["handed_back_sha"] = tip_sha
    if seal is not None:
        rec["handback_seal"] = seal
        rec["handback_outcomes"] = seal["outcomes"]
    save_state(state_path, state)
    payload = {"schema": SCHEMA, "action": "hand-back", "record": rec,
               "handed_back_at": now_iso, "handed_back_sha": tip_sha}
    if seal is not None:
        payload["handback_seal"] = seal
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"✓ handed back [{rec.get('branch')}] @ {tip_sha[:12]} ({now_iso})")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    _, now_iso = resolve_now(args.at)
    if args.status not in RESOLVE_STATUS:
        print(f"✗ --status must be one of {RESOLVE_STATUS}", file=sys.stderr)
        return EXIT_USAGE
    if not args.branch and not args.path:
        print("✗ resolve needs --branch or --path", file=sys.stderr)
        return EXIT_USAGE

    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]
    target_path = _norm(args.path) if args.path else None

    matches = [
        r for r in records
        if r.get("status") == STATUS_ACTIVE
        and (
            (args.branch and r.get("branch") == args.branch)
            or (target_path and r.get("path") and _norm(r["path"]) == target_path)
        )
    ]
    if not matches:
        sel = f"branch={args.branch}" if args.branch else f"path={args.path}"
        print(f"✗ no active registry record for {sel}", file=sys.stderr)
        return EXIT_USAGE

    for r in matches:
        r["status"] = args.status
        r["resolved_at"] = now_iso
    save_state(state_path, state)

    if args.json:
        print(json.dumps({"schema": SCHEMA, "action": "resolve", "status": args.status,
                          "records": matches}, indent=2, ensure_ascii=False))
    else:
        for r in matches:
            print(f"✓ resolved [{r.get('branch') or r.get('path')}] -> {args.status} @ {now_iso}")
    return EXIT_OK


def _clear_steps(subject: dict[str, Any], root: Path) -> list[tuple[str, list[str], Path]]:
    """Ordered clearance steps for a CLEAR subject: remote branch → worktree remove
    → local branch. (worktree remove BEFORE branch delete: a branch checked out in a
    worktree cannot be deleted.) Only emits steps that apply to this subject shape."""
    steps: list[tuple[str, list[str], Path]] = []
    name = subject.get("name")
    path = subject.get("path")
    if name and _remote_branch_exists(name):
        steps.append(("delete remote branch", ["push", "origin", "--delete", name], root))
    if path:
        steps.append(("remove worktree", ["worktree", "remove", path], root))
    if name:
        steps.append(("delete local branch", ["branch", "-D", name], root))
    return steps


def _exec_step(label: str, gargs: list[str], cwd: Path, commit: bool, quiet: bool = False) -> bool:
    """Preview (dry-run) or run (commit) one clearance git step. `quiet` suppresses
    stdout (JSON mode) while still executing under --commit. Returns True on success."""
    shown = "git " + " ".join(gargs)
    if not commit:
        if not quiet:
            print(f"     {shown}   # {label}")
        return True
    rc, out = _git_ok(gargs, cwd=cwd)
    if not quiet:
        print(f"     {'✓' if rc == 0 else '✗'} {shown}   # {label}")
        if rc != 0 and out:
            print(f"        {out}")
    return rc == 0


def cmd_sweep(args: argparse.Namespace) -> int:
    if not args.no_fetch:
        fetch_origin()
    now_epoch, now_iso = resolve_now(args.at)
    root = repo_root()
    state_path = _state_path(args)
    state = load_state(state_path)
    records: list[dict[str, Any]] = state["records"]

    # --exclude-current: never propose clearing the worktree the sweep runs FROM.
    # The invoking worktree's root is `git rev-parse --show-toplevel` at cwd (= root
    # here, since cmd_sweep uses cwd's git context throughout).
    exclude_path = _norm(str(root)) if args.exclude_current else None

    subjects, stale = gather_sweep(
        args.base, now_epoch, args.live_window, records, exclude_path=exclude_path
    )
    clears = [s for s in subjects if s["disposition"] == "CLEAR"]
    keeps = [s for s in subjects if s["disposition"] == "KEEP"]
    mode = "committed" if args.commit else "dry-run"

    # Build the clearance plan up front. clears already excludes base/primary; this
    # filter is a hard safety net so a repository-destroying step can never be emitted.
    primary_path, protected_branches = sweep_guards(args.base)
    plans: list[tuple[dict[str, Any], list[tuple[str, list[str], Path]]]] = []
    for s in clears:
        safe_steps = [
            step for step in _clear_steps(s, root)
            if not _step_touches_protected(step[1], primary_path, protected_branches)
        ]
        plans.append((s, safe_steps))

    # ---- human tables first (printed before execution, non-json) ----------
    if not args.json:
        print(f"# worktree sweep ({mode}, base={args.base}) — orphan sentinel\n")
        if keeps:
            print("── KEEP (protected / live / dirty / unlanded / open-worktree) ──")
            headers = ["subject", "state", "landed", "prot", "untracked", "reason"]
            rows = [[
                s["label"], s["state"], "yes" if s["landed"] else "-",
                "PROT" if s.get("protected") else "-",
                "UNTRACKED" if s["untracked"] else "-",
                s.get("keep_reason") or s.get("unsafe") or "-",
            ] for s in keeps]
            print(_table(headers, rows))
            print()
        if clears:
            print("── CLEAR (dangling-landed / detached-orphan / resolved) ──")
            headers = ["subject", "state", "untracked", "worktree"]
            rows = [[
                s["label"], s["state"],
                "UNTRACKED" if s["untracked"] else "-",
                _short_path(s["path"]),
            ] for s in clears]
            print(_table(headers, rows))
            print()
        if stale:
            print("── STALE-ENTRY (registered but worktree gone → strike ledger) ──")
            for r in stale:
                print(f"  {r.get('branch') or '-'}   {r.get('path')}")
            print()
        if not (keeps or clears or stale):
            print("(nothing to sweep)")

    # ---- execute / preview clearance -------------------------------------
    failures = 0
    executed: list[dict[str, Any]] = []
    for s, safe_steps in plans:
        if not args.json:
            print(f"## clear {s['label']}  [{s['state']}]"
                  + ("  (UNTRACKED)" if s["untracked"] else ""))
        step_results = []
        for label, gargs, cwd in safe_steps:
            ok = _exec_step(label, gargs, cwd, args.commit, quiet=args.json)
            step_results.append({"label": label, "cmd": "git " + " ".join(gargs), "ok": ok})
            if not ok:
                failures += 1
        executed.append({"label": s["label"], "name": s.get("name"), "steps": step_results})

    # ---- ledger reconciliation (only on --commit) -------------------------
    # nit1: an ACTIVE record whose subject was CLEARed resolves to *merged* — a
    # successful landing/clearance. It must NOT later be struck as abandoned by the
    # stale path just because its worktree is now gone.
    cleared_branches = {s["name"] for s in clears if s.get("name")}
    cleared_paths = {_norm(s["path"]) for s in clears if s.get("path")}
    resolved_merged = 0
    struck = 0
    if args.commit:
        for r in records:
            if r.get("status") != STATUS_ACTIVE:
                continue
            if r.get("branch") in cleared_branches or (r.get("path") and _norm(r["path"]) in cleared_paths):
                r["status"] = "merged"
                r["resolved_at"] = now_iso
                resolved_merged += 1
        for r in stale:
            if r.get("status") != STATUS_ACTIVE:   # skip any just flipped to merged
                continue
            r["status"] = "abandoned"
            r["resolved_at"] = now_iso
            struck += 1
        if resolved_merged or struck:
            save_state(state_path, state)

    if not args.json:
        if struck:
            print(f"\n✓ struck {struck} stale ledger entry(ies) -> abandoned")
        elif stale:
            print(f"\n# {len(stale)} stale ledger entry(ies) would be struck (--commit to write)")
        if resolved_merged:
            print(f"✓ resolved {resolved_merged} cleared record(s) -> merged")
        if not args.commit:
            print("\n# dry-run only — re-run with --commit to execute clearance.")

    # ---- json (printed AFTER execution so committed mode reflects results) -
    if args.json:
        payload: dict[str, Any] = {
            "schema": SCHEMA, "mode": mode, "base": args.base,
            "clear": clears, "keep": keeps,
            "stale_entries": [
                {"branch": r.get("branch"), "path": r.get("path"), "intent": r.get("intent")}
                for r in stale
            ],
            "plan": [
                {"label": s["label"], "name": s.get("name"), "path": s.get("path"),
                 "cmds": ["git " + " ".join(gargs) for (_lbl, gargs, _cwd) in safe_steps]}
                for (s, safe_steps) in plans
            ],
        }
        if args.commit:
            payload["executed"] = executed
            payload["failures"] = failures
            payload["resolved_merged"] = resolved_merged
            payload["struck_stale"] = struck
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return EXIT_OK if failures == 0 else EXIT_PARTIAL


# ============================================================================
# argparse
# ============================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="worktree_registry.py",
        description=(
            "Worktree registry — birth→resolution ledger + orphan sentinel. "
            "Judgement (classify / unsafe_to_drop) is deferred to the P1 pure layer "
            "ops/lib/worktree_state.py; containment uses TREE-DIFF, never git cherry. "
            "See module docstring for the state file schema and layer contract."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def add_state(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--state", default=None,
                        help="registry state file (default: <git-common-dir dirname>/.cache/worktree_registry.json)")
        sp.add_argument("--at", default=None,
                        help="override 'now' (ISO8601 or epoch seconds) — for tests/determinism")

    def add_base(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--base", default="origin/main",
            help="baseline ref for containment (default: origin/main — the LOCAL base "
                 "may lag origin, which would hide already-landed work; compare against "
                 "the remote so a merged branch reads as landed)",
        )
        sp.add_argument("--live-window", type=int, default=ws.LIVE_WINDOW_DEFAULT_S,
                        help=f"seconds; HEAD younger than this = live agent (default {ws.LIVE_WINDOW_DEFAULT_S})")

    reg = sub.add_parser("register", help="birth: record a new active worktree")
    add_state(reg)
    reg.add_argument("--path", required=True, help="worktree path")
    reg.add_argument("--branch", required=True, help="branch name checked out in it")
    reg.add_argument("--intent", required=True, help="why this worktree exists (short)")
    reg.add_argument("--base", default="main", help="baseline ref it forks from (default: main)")
    reg.add_argument(
        "--repo-root", default=None,
        help="actual repository root used to resolve --base before a not-yet-born path exists",
    )
    reg.add_argument(
        "--backlog", nargs="*", default=None, metavar="ID",
        help="backlog ticket ids this worktree CLAIMS. Refused with exit "
             f"{EXIT_CLAIMED} if any of them is already held by another active "
             "record. Omit to leave an existing claim untouched; pass with no ids "
             "to give it up. A claim lives exactly as long as the record is active, "
             "so `resolve` and `sweep` release it with no extra step.",
    )
    reg.add_argument(
        "--exclusive", action="store_true",
        help="new-birth mode: refuse when branch OR path already has an active "
             "record instead of idempotently upserting it. `open` uses this so two "
             "concurrent callers with the same slug cannot share one record and "
             "let the loser's cleanup resolve the winner's claim; `adopt` omits it.",
    )
    reg.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    reg.set_defaults(func=cmd_register)

    ls = sub.add_parser("list", help="ledger + live classify of each record")
    add_state(ls)
    ls.add_argument("--live-window", type=int, default=ws.LIVE_WINDOW_DEFAULT_S,
                    help="seconds; live-agent window for the live classify column")
    ls.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    ls.set_defaults(func=cmd_list)

    hb = sub.add_parser(
        "hand-back",
        help="worker hand-back: stamp the active record with the current checked-out tip",
    )
    add_state(hb)
    hb.add_argument("--branch", default=None, help="branch of the active record")
    hb.add_argument("--path", default=None,
                    help="worktree path (default: current worktree)")
    hb.add_argument("--outcomes", default=None, metavar="JSON",
                    help="typed hand-back outcomes JSON; required for closed-loop integration")
    hb.add_argument("--campaign", default=None, metavar="ID",
                    help="campaign id when handing back a child integration receipt")
    hb.add_argument("--partition", default=None, metavar="ID",
                    help="campaign partition id for a child integration receipt")
    hb.add_argument("--role", default=None, choices=("child",),
                    help="receipt role (currently only child is integrable by a parent)")
    hb.add_argument("--manifest", default=None, metavar="JSON",
                    help="completed child integration manifest used to build the receipt")
    hb.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    hb.set_defaults(func=cmd_hand_back)

    rs = sub.add_parser("resolve", help="death: strike a worktree's active record")
    add_state(rs)
    rs.add_argument("--branch", default=None, help="branch of the record to resolve")
    rs.add_argument("--path", default=None, help="path of the record to resolve")
    rs.add_argument("--status", required=True, choices=list(RESOLVE_STATUS),
                    help="merged (cutover) | abandoned (dropped)")
    rs.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    rs.set_defaults(func=cmd_resolve)

    sw = sub.add_parser(
        "sweep",
        help="orphan sentinel: fetch → classify every worktree/branch → propose "
             "clearance (dry-run default; --commit executes; unsafe work refused)",
    )
    add_state(sw)
    add_base(sw)
    sw.add_argument("--no-fetch", action="store_true", help="skip git fetch (offline / tests)")
    sw.add_argument("--exclude-current", action="store_true",
                    help="never propose clearing the worktree the sweep is invoked FROM "
                         "(self-exclusion; lets the P3 orchestrator preflight from any worktree)")
    sw.add_argument("--commit", action="store_true", help="execute clearance (default: dry-run)")
    sw.add_argument("--json", action="store_true", help=f"emit {SCHEMA} JSON")
    sw.set_defaults(func=cmd_sweep)

    return p


# Named, so membership can be ASSERTED. It used to be an inline tuple inside `main`,
# and the only thing guarding `cmd_register`'s place in it was a 24-process race test
# — which was measured to notice its removal about 1 run in 10, because the children
# were spawned in a loop and the interpreter start-up spread (median 1.26 ms between
# arrivals) serialized them before the lock ever mattered. A structural assertion
# catches the same mutation every time, and costs nothing.
LEDGER_WRITERS = (cmd_register, cmd_hand_back, cmd_resolve, cmd_sweep)


def _prepare_register_base(args: argparse.Namespace) -> None:
    """Resolve a missing worktree's base before the ledger lock is acquired."""
    if args.func is not cmd_register or Path(os.path.abspath(args.path)).is_dir():
        return
    repo_root_arg = getattr(args, "repo_root", None)
    # A not-yet-born path has no repository context of its own. Only the
    # orchestrator's explicit --repo-root is authoritative; falling back to the
    # module process cwd would silently stamp an unrelated repository (or none).
    args._recorded_base_sha = (
        _git_base_for_claim(args.base, repo_root_path=repo_root_arg)
        if repo_root_arg else None
    )


def main(argv: list[str] | None = None) -> int:
    tokens = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        args = parser.parse_args(tokens)
    except SystemExit as exc:
        # Keep argparse's diagnostics, but expose the shared CLI contract to
        # callers: only --help is a successful exit; malformed invocations are
        # usage errors, not the generic argparse code 2.
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    _prepare_register_base(args)
    # Serialize the WRITERS over the shared ledger so parallel hands-off sessions
    # cannot lose each other's updates (each mutator is a load→mutate→save RMW on one
    # JSON file). Read-only commands (list) run lock-free — the atomic save_state
    # keeps their reads from tearing. The lock spans the whole mutator, so its
    # internal load_state/save_state are one indivisible critical section.
    if args.func in LEDGER_WRITERS:
        with _ledger_lock(_state_path(args)):
            return args.func(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
