#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Safely terminalize one malformed published PR."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from delivery_control.application import build_application
from delivery_control.domain.errors import DeliverySourceError
from delivery_control.services.quarantine import QuarantineService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="close and release one malformed published PR with exact CAS guards"
    )
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        application = build_application(repo=Path.cwd())
        result = QuarantineService(
            registry_query=application.registry,
            registry_command=application.registry,
            git_query=application.git,
            git_command=application.git,
            github_query=application.github,
            github_command=application.github,
        ).quarantine(pull_request_number=args.pr)
    except (DeliverySourceError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "kg.delivery.quarantine.v1",
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "schema": "kg.delivery.quarantine.v1",
                "ok": True,
                "result": asdict(result),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
