"""CAS recording of the GitHub base observed after PR publication.

The typed handback base describes the physical owner checkout and must not be
rewritten after the worktree is released.  GitHub can nevertheless move the
PR's target OID as ``main`` advances.  This command records that second fact
without changing ownership, Scope, claim generation, or handback provenance.
"""

from __future__ import annotations

import argparse
import json
import sys

from .claims import claim_generation
from .constants import EXIT_CLAIMED, EXIT_OK, EXIT_USAGE
from .environment import load_state, resolve_now, state_path
from .handback_cli import has_valid_stored, is_commit_sha
from .inspection import record_view
from .records import (
    SCHEMA,
    STATUS_ACTIVE,
    STATUS_CLEANUP_PENDING,
    STATUS_PUBLISHED,
    legacy_external_ids,
    mutation_blockers_for_target,
    norm_path,
    record_matches,
)
from .storage import ledger_lock, save_state


def cmd_record_published_base(args: argparse.Namespace) -> int:
    if not args.branch and not args.path:
        print(
            "✗ record-published-base needs --branch or --path",
            file=sys.stderr,
        )
        return EXIT_USAGE
    required = (
        args.expected_generation,
        args.expected_head_sha,
        args.expected_handback_base_sha,
        args.published_base_sha,
    )
    if any(value is None for value in required):
        print(
            "✗ record-published-base requires exact generation, HEAD, handback base, and published base",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if not all(
        is_commit_sha(value)
        for value in (
            args.expected_head_sha,
            args.expected_handback_base_sha,
            args.published_base_sha,
        )
    ):
        print(
            "✗ published-base arguments must be full lowercase commit SHAs",
            file=sys.stderr,
        )
        return EXIT_USAGE

    target = state_path(args)
    with ledger_lock(target):
        state = load_state(target)
        blockers = mutation_blockers_for_target(
            state,
            branch=args.branch,
            path=args.path,
            external_ids_value=args.lane,
        )
        if blockers:
            print(
                "✗ malformed ownership facts block registry mutation", file=sys.stderr
            )
            return EXIT_CLAIMED

        matches = [
            record
            for record in state.get("records", [])
            if isinstance(record, dict)
            and record.get("status")
            in {
                STATUS_ACTIVE,
                STATUS_CLEANUP_PENDING,
                STATUS_PUBLISHED,
            }
            and record_matches(record, branch=args.branch, path=args.path)
            and claim_generation(record, "claim_generation") == args.expected_generation
            and (
                not args.lane
                or args.lane in legacy_external_ids(record)
                or (
                    not legacy_external_ids(record)
                    and args.lane == record.get("branch")
                )
            )
        ]
        if len(matches) != 1:
            print(
                f"✗ no exact published-base claim matches ({len(matches)})",
                file=sys.stderr,
            )
            return EXIT_CLAIMED
        record = matches[0]
        if args.branch is not None and record.get("branch") != args.branch:
            print("✗ published-base owner branch differs", file=sys.stderr)
            return EXIT_CLAIMED
        if args.path is not None and norm_path(
            str(record.get("path") or "")
        ) != norm_path(args.path):
            print("✗ published-base owner path or branch differs", file=sys.stderr)
            return EXIT_CLAIMED
        if record.get("base_sha") != args.expected_handback_base_sha:
            print("✗ typed handback base changed during publication", file=sys.stderr)
            return EXIT_CLAIMED
        if record.get("handed_back_sha") != args.expected_head_sha:
            print("✗ typed handback HEAD changed during publication", file=sys.stderr)
            return EXIT_CLAIMED
        if not has_valid_stored(record):
            print(
                "✗ published-base recording requires a valid stored handback",
                file=sys.stderr,
            )
            return EXIT_CLAIMED
        previous = record.get("published_base_sha")
        if previous is not None and not is_commit_sha(previous):
            print("✗ existing published PR base is malformed", file=sys.stderr)
            return EXIT_CLAIMED
        if previous is not None and previous != args.published_base_sha:
            print(
                "✗ published PR base differs from the existing recorded base",
                file=sys.stderr,
            )
            return EXIT_CLAIMED
        record["published_base_sha"] = args.published_base_sha
        _, now_iso = resolve_now(args.at)
        record["published_base_recorded_at"] = now_iso
        save_state(target, state)
        result = record_view(record)

    payload = {
        "schema": SCHEMA,
        "action": "record-published-base",
        "status": "published-base-recorded",
        "records": [result],
    }
    print(
        json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json
        else "✓ recorded published PR base"
    )
    return EXIT_OK
