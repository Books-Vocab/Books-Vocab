"""Read-only dispatch preflight compiler.

This module deliberately has no registry, git, or subprocess side effects.  The
callers supply those observations and this module compiles them into one stable
classification before a worktree claim is attempted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "kg.dispatch.preflight.v1"
CLASSIFICATIONS = (
    "executable",
    "contract-blocked",
    "baseline-green",
    "active-overlap",
    "environment-blocked",
    "dependency-blocked",
)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _site_paths(fix_site: str) -> list[str]:
    paths: list[str] = []
    for raw in str(fix_site or "").replace("；", ";").split(";"):
        token = raw.strip().split()[0] if raw.strip() else ""
        if not token:
            continue
        token = token.split("::", 1)[0]
        if ":" in token:
            head, tail = token.rsplit(":", 1)
            if tail.isdigit():
                token = head
        paths.append(token.strip("`'\""))
    return _unique(paths)


@dataclass(frozen=True)
class PreflightResult:
    ticket_id: str
    classification: str
    problems: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    repair_hints: tuple[str, ...] = field(default_factory=tuple)
    probe: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.classification == "executable"

    @property
    def schema(self) -> str:
        return SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ticket_id": self.ticket_id,
            "classification": self.classification,
            "ok": self.ok,
            "problems": [dict(problem) for problem in self.problems],
            "repair_hints": list(self.repair_hints),
            "probe": dict(self.probe) if self.probe is not None else None,
        }


def _repair_hints(problems: Iterable[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    kinds = {str(problem.get("kind")) for problem in problems}
    if "contract-blocked" in kinds or any(
            kind in kinds for kind in ("fix-site-missing", "acceptance-dependency-missing")
    ):
        hints.append("repair contract_status/evidence, fix_site, and acceptance dependencies")
    if "dependency-blocked" in kinds:
        hints.append("finish blocked_by tickets or update the dependency edge")
    if "active-overlap" in kinds:
        hints.append("wait for the active worktree or split the fix_site into disjoint paths")
    if "baseline-green" in kinds:
        hints.append("verify the existing fix and close as baseline-green/no-op; do not open a worktree")
    if "environment-blocked" in kinds:
        hints.append("install/provision the named dependency, then rerun --probe-acceptance")
    return hints


def compile_static(
    payload: dict[str, Any],
    *,
    repo: Path,
    contract_problems: Iterable[dict[str, Any]] = (),
    unresolved_blockers: Iterable[str] = (),
    active_files: Iterable[str] = (),
) -> PreflightResult:
    """Compile supplied read-only observations into a claim decision."""
    problems: list[dict[str, Any]] = []
    contract = [dict(problem) for problem in contract_problems]
    if contract:
        problems.extend(contract)
    declared_baseline = str(payload.get("contract_baseline") or "").strip().lower()
    if not contract and declared_baseline in {"green", "baseline-green", "no-op"}:
        problems.append({"kind": "baseline-green", "source": "contract_baseline"})
    elif not contract and declared_baseline in {
        "environment", "environment-blocked", "missing-dependency",
    }:
        problems.append({"kind": "environment-blocked", "source": "contract_baseline"})
    unresolved = set(_unique(unresolved_blockers))
    for blocker in _unique(payload.get("blocked_by") or []):
        if blocker in unresolved:
            problems.append({"kind": "dependency-blocked", "ticket_id": blocker})

    active = set(_unique(active_files))
    sites = set(_site_paths(str(payload.get("fix_site") or "")))
    for path in sorted(sites & active):
        problems.append({"kind": "active-overlap", "path": path})

    known_baseline = declared_baseline in {"green", "baseline-green", "no-op"}
    known_environment = declared_baseline in {
        "environment", "environment-blocked", "missing-dependency",
    }
    if (known_baseline or known_environment) and contract and all(
            problem.get("kind") == "contract-baseline-not-red" for problem in contract
    ):
        problems = [problem for problem in problems
                    if problem.get("kind") != "contract-baseline-not-red"]
        problems.append({
            "kind": "baseline-green" if known_baseline else "environment-blocked",
            "source": "contract_baseline",
        })
    if any(problem.get("kind") == "baseline-green" for problem in problems):
        classification = "baseline-green"
    elif any(problem.get("kind") == "environment-blocked" for problem in problems):
        classification = "environment-blocked"
    elif contract:
        classification = "contract-blocked"
    elif any(problem.get("kind") == "dependency-blocked" for problem in problems):
        classification = "dependency-blocked"
    elif any(problem.get("kind") == "active-overlap" for problem in problems):
        classification = "active-overlap"
    else:
        classification = "executable"
    return PreflightResult(
        ticket_id=str(payload.get("id") or ""),
        classification=classification,
        problems=tuple(problems),
        repair_hints=tuple(_repair_hints(problems)),
    )


def with_probe(
    result: PreflightResult,
    *,
    returncode: int,
    expected_returncode: int,
    stderr: str,
) -> PreflightResult:
    """Add an explicitly requested acceptance probe without mutating the store."""
    probe = {
        "returncode": int(returncode),
        "expected_returncode": int(expected_returncode),
        "stderr": str(stderr or "")[-2000:],
    }
    if result.classification != "executable":
        return PreflightResult(
            ticket_id=result.ticket_id, classification=result.classification,
            problems=result.problems, repair_hints=result.repair_hints, probe=probe,
        )
    lowered = str(stderr or "").lower()
    environment_markers = (
        "modulenotfounderror", "no module named", "command not found",
        "filenotfounderror", "no such file or directory", "could not find",
    )
    if any(marker in lowered for marker in environment_markers):
        classification = "environment-blocked"
        extra = ({"kind": "environment-blocked", "returncode": int(returncode)},)
    elif int(returncode) == int(expected_returncode) == 0:
        classification = "baseline-green"
        extra = ({"kind": "baseline-green"},)
    else:
        classification = "executable"
        extra = ({"kind": "acceptance-red", "returncode": int(returncode)},)
    problems = tuple((*result.problems, *extra))
    return PreflightResult(
        ticket_id=result.ticket_id, classification=classification,
        problems=problems, repair_hints=tuple(_repair_hints(problems)), probe=probe,
    )
