#!/usr/bin/env -S uv run --script
"""Bound the review loop for one scope and one commit.

This is a coordination state machine, not a reviewer-quality oracle.  It records
the evidence supplied by the independent reviewer and prevents the driving agent
from automatically asking for a third full review after two blocker-bearing
passes.  The state lives under .cache and is deliberately not part of the commit.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = "kg.review_cycle.v1"
MAX_ATTEMPTS = 2
SHA_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
SCOPE_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")
DECISIONS = {"accept", "fix", "defer"}
STATUSES = {
    "ready", "reviewing", "review_again", "passed", "pass_with_followups",
    "adjudication_required", "adjudicated",
}


class CycleError(Exception):
    """An expected state-machine refusal."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fail(message: str) -> None:
    raise CycleError(message)


def validate_identity(scope: str, commit_sha: str) -> tuple[str, str]:
    if not scope or not SCOPE_RE.fullmatch(scope):
        fail("scope must be a non-empty safe token (letters, digits, .:/-)")
    if not SHA_RE.fullmatch(commit_sha):
        fail("commit-sha must be a full 40- or 64-character hexadecimal object id")
    return scope, commit_sha.lower()


def validate_state_shape(payload: Any) -> None:
    if not isinstance(payload, dict):
        fail("review cycle state must be a JSON object")
    if payload.get("schema") != SCHEMA or not isinstance(payload.get("cycles"), list):
        fail("invalid review cycle state schema")
    for index, cycle in enumerate(payload["cycles"]):
        if not isinstance(cycle, dict):
            fail(f"invalid review cycle at index {index}: expected object")
        if not isinstance(cycle.get("scope"), str) or not isinstance(cycle.get("commit_sha"), str):
            fail(f"invalid review cycle at index {index}: missing identity")
        _, canonical_sha = validate_identity(cycle["scope"], cycle["commit_sha"])
        if cycle["commit_sha"] != canonical_sha:
            fail(f"invalid review cycle at index {index}: commit_sha must be lowercase canonical")
        if not isinstance(cycle.get("attempts"), list):
            fail(f"invalid review cycle at index {index}: attempts must be a list")
        status = cycle.get("status", "ready")
        if status not in STATUSES:
            fail(f"invalid review cycle at index {index}: unknown status")
        if len(cycle["attempts"]) > MAX_ATTEMPTS:
            fail(f"invalid review cycle at index {index}: too many attempts")
        active = cycle.get("active_attempt")
        if active is not None and (
            not isinstance(active, dict)
            or not isinstance(active.get("number"), int)
            or isinstance(active.get("number"), bool)
            or active["number"] < 1
        ):
            fail(f"invalid review cycle at index {index}: active attempt")
        for attempt_index, attempt in enumerate(cycle["attempts"]):
            if (
                not isinstance(attempt, dict)
                or not isinstance(attempt.get("number"), int)
                or isinstance(attempt.get("number"), bool)
                or attempt["number"] != attempt_index + 1
                or attempt.get("outcome") not in {"pass", "findings"}
                or not isinstance(attempt.get("findings"), dict)
            ):
                fail(f"invalid review cycle at index {index}: attempt {attempt_index} shape")
            findings = attempt["findings"]
            for key in ("block", "nit", "tooling_debt"):
                value = findings.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    fail(f"invalid review cycle at index {index}: attempt {attempt_index} counts")
        if active is not None:
            if status != "reviewing" or active["number"] != len(cycle["attempts"]) + 1:
                fail(f"invalid review cycle at index {index}: active attempt number/status")
            if active["number"] > MAX_ATTEMPTS:
                fail(f"invalid review cycle at index {index}: active attempt exceeds limit")
        elif status == "reviewing":
            fail(f"invalid review cycle at index {index}: reviewing without active attempt")
        if status == "review_again" and (
            len(cycle["attempts"]) != 1 or cycle["attempts"][0]["findings"].get("block", 0) < 1
        ):
            fail(f"invalid review cycle at index {index}: review_again transition")
        if status == "adjudication_required" and (
            len(cycle["attempts"]) != MAX_ATTEMPTS
            or cycle["attempts"][-1]["findings"].get("block", 0) < 1
        ):
            fail(f"invalid review cycle at index {index}: adjudication transition")
        if status == "adjudicated" and (
            len(cycle["attempts"]) != MAX_ATTEMPTS
            or not isinstance(cycle.get("adjudication"), dict)
        ):
            fail(f"invalid review cycle at index {index}: adjudication record")
        cancellations = cycle.get("cancellations", [])
        if not isinstance(cancellations, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("reason"), str)
            for item in cancellations
        ):
            fail(f"invalid review cycle at index {index}: cancellations")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "cycles": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read review cycle state {path}: {exc}")
    validate_state_shape(payload)
    return payload


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


@contextmanager
def state_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def cycle_for(payload: dict[str, Any], scope: str, commit_sha: str) -> dict[str, Any] | None:
    for cycle in reversed(payload["cycles"]):
        if cycle.get("scope") == scope and cycle.get("commit_sha") == commit_sha:
            return cycle
    return None


def public_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    attempts = cycle.get("attempts", [])
    totals = {"block": 0, "nit": 0, "tooling_debt": 0}
    attempt_summaries = []
    for attempt in attempts:
        findings = attempt.get("findings", {})
        for key in totals:
            totals[key] += int(findings.get(key, 0))
        attempt_summaries.append({
            "number": attempt.get("number"),
            "reviewer": attempt.get("reviewer"),
            "outcome": attempt.get("outcome"),
            "findings": {key: int(findings.get(key, 0)) for key in totals},
        })
    return {
        "scope": cycle["scope"],
        "commit_sha": cycle["commit_sha"],
        "attempts": len(attempts),
        "max_attempts": MAX_ATTEMPTS,
        "status": cycle.get("status", "new"),
        "active_attempt": cycle.get("active_attempt"),
        "cancellations": cycle.get("cancellations", []),
        "finding_totals": totals,
        "attempt_summaries": attempt_summaries,
        "adjudication": cycle.get("adjudication"),
    }


def start_cycle(payload: dict[str, Any], scope: str, commit_sha: str) -> dict[str, Any]:
    cycle = cycle_for(payload, scope, commit_sha)
    if cycle is None:
        cycle = {
            "scope": scope,
            "commit_sha": commit_sha,
            "created_at": now(),
            "updated_at": now(),
            "attempts": [],
            "status": "ready",
        }
        payload["cycles"].append(cycle)

    attempts = len(cycle["attempts"])
    status = cycle.get("status", "ready")
    if status == "adjudication_required":
        return {
            **public_cycle(cycle),
            "action": "adjudication_required",
            "allowed": False,
            "message": "two blocker-bearing review passes are complete; adjudicate before any new full review",
        }
    if status in {"passed", "pass_with_followups", "adjudicated"}:
        return {
            **public_cycle(cycle),
            "action": "no_review_needed",
            "allowed": False,
            "message": "this commit and scope already have a terminal review decision",
        }
    if cycle.get("active_attempt") is not None:
        return {
            **public_cycle(cycle),
            "action": "review_in_progress",
            "allowed": False,
            "attempt": cycle["active_attempt"]["number"],
            "message": "a review attempt is already reserved; record its result before starting another",
        }
    if attempts >= MAX_ATTEMPTS:
        cycle["status"] = "adjudication_required"
        return {
            **public_cycle(cycle),
            "action": "adjudication_required",
            "allowed": False,
            "message": "review attempt limit reached; adjudication is required",
        }
    cycle["active_attempt"] = {
        "number": attempts + 1,
        "started_at": now(),
        "previous_status": status,
    }
    cycle["status"] = "reviewing"
    return {
        **public_cycle(cycle),
        "action": "review",
        "allowed": True,
        "attempt": attempts + 1,
        "message": "run one independent review for this commit delta",
    }


def record_review(
    payload: dict[str, Any],
    scope: str,
    commit_sha: str,
    outcome: str,
    reviewer: str,
    evidence: str,
    block_count: int,
    nit_count: int,
    tooling_debt_count: int,
) -> dict[str, Any]:
    cycle = cycle_for(payload, scope, commit_sha)
    if cycle is None:
        fail("start the review cycle before recording a review")
    if cycle.get("status") in {"passed", "pass_with_followups", "adjudicated"}:
        fail("review cycle is already terminal; start a new cycle for a new commit delta")
    if cycle.get("status") == "adjudication_required":
        fail("review attempt limit reached; use adjudicate instead of a third full review")
    active = cycle.get("active_attempt")
    if cycle.get("status") != "reviewing" or not isinstance(active, dict):
        fail("start the review cycle before recording a review")
    if len(cycle["attempts"]) >= MAX_ATTEMPTS:
        cycle["status"] = "adjudication_required"
        fail("review attempt limit reached; use adjudicate instead of a third full review")
    if not reviewer.strip():
        fail("reviewer is required")
    if not evidence.strip():
        fail("review evidence is required")
    counts = {
        "block": block_count,
        "nit": nit_count,
        "tooling_debt": tooling_debt_count,
    }
    if any(value < 0 for value in counts.values()):
        fail("finding counts cannot be negative")
    if outcome == "pass" and any(counts.values()):
        fail("pass cannot carry finding counts; use outcome findings")
    if outcome == "findings" and not any(counts.values()):
        fail("findings must name at least one BLOCK, NIT, or TOOLING-DEBT")
    if outcome not in {"pass", "findings"}:
        fail("outcome must be pass or findings")

    attempt = active["number"]
    cycle["attempts"].append({
        "number": attempt,
        "recorded_at": now(),
        "reviewer": reviewer.strip(),
        "outcome": outcome,
        "findings": counts,
        "evidence": evidence.strip(),
    })
    cycle.pop("active_attempt", None)
    if outcome == "pass":
        cycle["status"] = "passed"
        action = "complete"
        message = "review passed; continue the workflow"
    elif block_count > 0 and attempt >= MAX_ATTEMPTS:
        cycle["status"] = "adjudication_required"
        action = "adjudication_required"
        message = "second blocker-bearing pass reached; stop automatic re-review and adjudicate"
    elif block_count > 0:
        cycle["status"] = "review_again"
        action = "fix_then_review_once"
        message = "fix only in-scope BLOCKs, then one final independent review is allowed"
    else:
        cycle["status"] = "pass_with_followups"
        action = "complete_with_followups"
        message = "no BLOCK remains; carry NIT/TOOLING-DEBT as named follow-ups"
    cycle["updated_at"] = now()
    return {**public_cycle(cycle), "action": action, "message": message}


def adjudicate(
    payload: dict[str, Any], scope: str, commit_sha: str, decision: str, reason: str
) -> dict[str, Any]:
    cycle = cycle_for(payload, scope, commit_sha)
    if cycle is None:
        fail("cannot adjudicate a cycle that was not started")
    if cycle.get("status") != "adjudication_required":
        fail("adjudication is only available after two blocker-bearing review passes")
    if decision not in DECISIONS:
        fail("decision must be accept, fix, or defer")
    if not reason.strip():
        fail("adjudication reason is required")
    cycle["adjudication"] = {
        "decided_at": now(),
        "decision": decision,
        "reason": reason.strip(),
    }
    cycle["status"] = "adjudicated"
    cycle["updated_at"] = now()
    return {
        **public_cycle(cycle),
        "action": "adjudicated",
        "allowed": False,
        "message": "cycle is closed; a new commit starts a new bounded cycle",
    }


def cancel_review(payload: dict[str, Any], scope: str, commit_sha: str, reason: str) -> dict[str, Any]:
    cycle = cycle_for(payload, scope, commit_sha)
    if cycle is None:
        fail("cannot cancel a cycle that was not started")
    active = cycle.get("active_attempt")
    if cycle.get("status") != "reviewing" or not isinstance(active, dict):
        fail("there is no active review attempt to cancel")
    if not reason.strip():
        fail("cancellation reason is required")
    cycle.setdefault("cancellations", []).append({
        "attempt": active["number"],
        "cancelled_at": now(),
        "reason": reason.strip(),
    })
    cycle["status"] = active.get("previous_status", "ready")
    cycle.pop("active_attempt", None)
    cycle["updated_at"] = now()
    return {
        **public_cycle(cycle),
        "action": "review_cancelled",
        "allowed": False,
        "message": "the abandoned attempt was released without consuming a review slot; start it again when ready",
    }


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"[review-cycle] {payload.get('action', payload.get('status'))}: {payload.get('message', '')}")
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


class ReviewArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CycleError(message)


def parser() -> argparse.ArgumentParser:
    p = ReviewArgumentParser(description="Bound independent review attempts for one commit scope")
    p.add_argument("--state", type=Path, default=Path(".cache/review_cycles.json"))
    p.add_argument("--json", action="store_true", help="emit one machine-readable JSON object")
    sp = p.add_subparsers(dest="command", required=True, parser_class=ReviewArgumentParser)

    start = sp.add_parser("start", help="reserve the next review attempt or require adjudication")
    start.add_argument("--scope", required=True)
    start.add_argument("--commit-sha", required=True)

    record = sp.add_parser("record", help="record one independent review result")
    record.add_argument("--scope", required=True)
    record.add_argument("--commit-sha", required=True)
    record.add_argument("--outcome", choices=("pass", "findings"), required=True)
    record.add_argument("--reviewer", required=True)
    record.add_argument("--evidence-file", type=Path, required=True)
    record.add_argument("--block-count", type=int, default=0)
    record.add_argument("--nit-count", type=int, default=0)
    record.add_argument("--tooling-debt-count", type=int, default=0)

    decide = sp.add_parser("adjudicate", help="close a cycle after the bounded review limit")
    decide.add_argument("--scope", required=True)
    decide.add_argument("--commit-sha", required=True)
    decide.add_argument("--decision", choices=sorted(DECISIONS), required=True)
    decide.add_argument("--reason", required=True)

    cancel = sp.add_parser("cancel", help="release an abandoned active review attempt")
    cancel.add_argument("--scope", required=True)
    cancel.add_argument("--commit-sha", required=True)
    cancel.add_argument("--reason", required=True)

    status = sp.add_parser("status", help="read one or all review cycles")
    status.add_argument("--scope")
    status.add_argument("--commit-sha")
    return p


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in raw_argv
    try:
        args = parser().parse_args(raw_argv)
        if args.command in {"start", "record", "adjudicate", "cancel"}:
            args.scope, args.commit_sha = validate_identity(args.scope, args.commit_sha)
        state = args.state
        with state_lock(state):
            payload = load_state(state)
            if args.command == "start":
                result = start_cycle(payload, args.scope, args.commit_sha)
                save_state(state, payload)
            elif args.command == "record":
                try:
                    evidence = args.evidence_file.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    fail(f"cannot read evidence file: {exc}")
                result = record_review(
                    payload, args.scope, args.commit_sha, args.outcome, args.reviewer,
                    evidence, args.block_count, args.nit_count, args.tooling_debt_count,
                )
                save_state(state, payload)
            elif args.command == "adjudicate":
                result = adjudicate(payload, args.scope, args.commit_sha, args.decision, args.reason)
                save_state(state, payload)
            elif args.command == "cancel":
                result = cancel_review(payload, args.scope, args.commit_sha, args.reason)
                save_state(state, payload)
            else:
                cycles = payload["cycles"]
                if args.scope:
                    cycles = [c for c in cycles if c.get("scope") == args.scope]
                if args.commit_sha:
                    cycles = [c for c in cycles if c.get("commit_sha") == args.commit_sha]
                result = {"schema": SCHEMA, "cycles": [public_cycle(c) for c in cycles]}
        if args.command != "status":
            result = {"schema": SCHEMA, **result}
        emit(result, args.json)
        return 0
    except CycleError as exc:
        error = {"schema": SCHEMA, "ok": False, "error": str(exc)}
        emit(error, as_json)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
