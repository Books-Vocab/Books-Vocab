#!/usr/bin/env python3
"""Honest local fixture selftest; live Felix/Oscar proof is operator-only."""

from __future__ import annotations

import json
import sys


def selftest_payload() -> dict[str, object]:
    return {
        "mode": "local-fixture",
        "cross_host_verified": False,
        "operator_remote_evidence_required": True,
        "runner": {"verified": False},
        "receipt": {"verifier": "none", "signature_verified": False, "nonce_verified": False, "ack_verified": False},
        "cleanup": {"state": "not-run"},
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:2] == ["selftest", "--json"]:
        print(json.dumps(selftest_payload(), sort_keys=True))
        return 0
    print("usage: felix_compute_admin.py selftest --json", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())

