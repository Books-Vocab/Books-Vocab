#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Validate that external GitHub Actions use immutable commit references."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA = "kg.workflow_dependency_policy.v1"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<value>.*)$")


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    line: int | None = None
    value: str | None = None
    message: str = ""


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _strip_yaml_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    return line.split("#", 1)[0].rstrip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _external_ref(value: str) -> tuple[str, str] | None:
    if value.startswith("./"):
        return None
    if "@" not in value:
        return (value, "")
    action, ref = value.rsplit("@", 1)
    return action, ref


def validate_workflows(workflows_dir: Path) -> dict[str, object]:
    """Return a deterministic validation report for a workflow directory."""

    root = workflows_dir.resolve()
    violations: list[Violation] = []
    workflow_files = sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix in {".yml", ".yaml"}
    ) if root.is_dir() else []
    local_uses = 0
    external_uses = 0
    total_uses = 0

    if not root.is_dir():
        violations.append(
            Violation(
                code="workflows-dir-missing",
                path=str(workflows_dir),
                message="workflow directory does not exist",
            )
        )
    elif not workflow_files:
        violations.append(
            Violation(
                code="no-workflows",
                path=str(workflows_dir),
                message="no YAML workflow files were scanned",
            )
        )

    for workflow in workflow_files:
        display = _display_path(workflow, root)
        for line_number, raw_line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = USES_RE.match(_strip_yaml_comment(raw_line))
            if not match:
                continue
            total_uses += 1
            value = _unquote(match.group("value").strip())
            if not value:
                violations.append(
                    Violation(
                        code="empty-uses",
                        path=display,
                        line=line_number,
                        message="uses entry is empty",
                    )
                )
                continue
            if value.startswith("./"):
                local_uses += 1
                continue

            external_uses += 1
            parsed = _external_ref(value)
            if parsed is None:
                continue
            action, ref = parsed
            if "/" not in action or not ref:
                violations.append(
                    Violation(
                        code="invalid-external-ref",
                        path=display,
                        line=line_number,
                        value=value,
                        message="external action must use owner/repository@40-hex-commit",
                    )
                )
            elif not SHA_RE.fullmatch(ref):
                violations.append(
                    Violation(
                        code="mutable-ref",
                        path=display,
                        line=line_number,
                        value=value,
                        message="external action ref must be a 40-character commit SHA",
                    )
                )

    if root.is_dir() and external_uses == 0:
        violations.append(
            Violation(
                code="zero-external-actions",
                path=str(workflows_dir),
                message="no external action refs were scanned",
            )
        )

    report = {
        "schema": SCHEMA,
        "status": "pass" if not violations else "block",
        "workflows_dir": str(workflows_dir),
        "workflow_files": len(workflow_files),
        "uses": total_uses,
        "local_uses": local_uses,
        "external_uses": external_uses,
        "violations": [asdict(item) for item in violations],
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=Path(".github/workflows"),
        help="directory containing GitHub Actions workflow YAML files",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = validate_workflows(args.workflows_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"workflow dependency policy: {report['status']}")
        for violation in report["violations"]:
            location = violation["path"]
            if violation["line"] is not None:
                location += f":{violation['line']}"
            detail = violation["value"] or violation["message"]
            print(f"  - {violation['code']} {location}: {detail}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
