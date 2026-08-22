"""Exact compare-and-swap lifecycle command."""

from __future__ import annotations

import argparse
import json
import sys

from .claims import claim_generation
from .constants import EXIT_CLAIMED, EXIT_OK, EXIT_USAGE
from .environment import git, load_state, repo_root, resolve_now, state_path
from .handback_cli import has_valid_physical, has_valid_stored, is_commit_sha
from .inspection import record_view
from .lifecycle import (
    TransitionRequest,
    transition_record,
    validate_terminal_proof,
)
from .records import SCHEMA, mutation_blockers, record_matches
from .storage import ledger_lock, save_state


def cmd_resolve(args: argparse.Namespace, *, resolve_statuses: tuple[str, ...]) -> int:
    if args.status not in resolve_statuses or (not args.branch and not args.path):
        print(
            "✗ resolve needs --branch/--path and a valid local disposition",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.expected_generation is None or args.expected_head_sha is None:
        print(
            "✗ resolve requires exact generation and HEAD compare-and-swap guards",
            file=sys.stderr,
        )
        return EXIT_USAGE
    terminal_proof: object = None
    if args.terminal_proof is not None:
        try:
            terminal_proof = json.loads(args.terminal_proof)
        except json.JSONDecodeError as exc:
            print(f"✗ terminal proof is invalid JSON: {exc.msg}", file=sys.stderr)
            return EXIT_USAGE
    target = state_path(args)

    def branch_head(branch: str) -> str | None:
        rc, output = git(
            ["rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"],
            repo_root(),
        )
        return output.strip() if rc == 0 and is_commit_sha(output.strip()) else None

    request = TransitionRequest(
        branch=args.branch,
        path=args.path,
        target=args.status,
        expected_generation=args.expected_generation,
        expected_head_sha=args.expected_head_sha,
    )
    with ledger_lock(target):
        state = load_state(target)
        blockers = mutation_blockers(state)
        if blockers:
            print(
                "✗ malformed ownership facts block registry mutation",
                file=sys.stderr,
            )
            return EXIT_CLAIMED
        result = transition_record(
            state,
            request,
            claim_generation=claim_generation,
            record_matches=record_matches,
            is_commit_sha=is_commit_sha,
            branch_head=branch_head,
            has_valid_handback=has_valid_physical,
            has_valid_stored_handback=has_valid_stored,
        )
        if result.record is None:
            print(f"✗ {result.reason}", file=sys.stderr)
            return EXIT_CLAIMED
        proof_problem = validate_terminal_proof(
            terminal_proof,
            record=result.record,
            request=request,
        )
        if proof_problem:
            print(f"✗ {proof_problem}", file=sys.stderr)
            return EXIT_CLAIMED
        _, now_iso = resolve_now(args.at)
        result.record["status"] = args.status
        result.record["resolved_at"] = now_iso
        if terminal_proof is not None:
            result.record["terminal_proof"] = terminal_proof
        save_state(target, state)
    records = [result.record]
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "action": "resolve",
                "status": args.status,
                "records": [record_view(record) for record in records],
            },
            indent=2,
            ensure_ascii=False,
        )
        if args.json
        else "\n".join(
            f"✓ resolved [{record.get('branch')}] -> {args.status}"
            for record in records
        )
    )
    return EXIT_OK
