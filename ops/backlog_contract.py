"""Acceptance-contract and selector helpers for the backlog CLI.

The backlog entry schema and CLI remain owned by :mod:`backlog`; this module
owns the narrower question of whether a recorded acceptance contract is
complete and how much of a pytest selector it would collect.  Functions take
their policy values and command runner explicitly so they stay independent of
the CLI module and remain easy to test in the stdlib-only ops sandbox.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable


def site_paths(fix_site: str) -> list[str]:
    """Extract conservative repository-relative anchors from ``fix_site``."""
    paths: list[str] = []
    for raw in re.split(r"[;；]+", fix_site):
        token = raw.strip().split()[0] if raw.strip() else ""
        if not token:
            continue
        token = token.split("::", 1)[0]
        token = re.split(r"(?::\d|：\d)", token, maxsplit=1)[0]
        paths.append(token.strip("`'\""))
    return paths


def command_paths(command: str) -> list[str]:
    """Find explicit repository paths without pretending to parse shell code."""
    paths: list[str] = []
    pattern = re.compile(
        r"(?<![A-Za-z0-9_./-])((?:ops|backend|ios|lab|docs|\.github)/[A-Za-z0-9_./-]+)"
    )
    for match in pattern.finditer(command):
        value = match.group(1).rstrip(".,;:'\")")
        if value not in paths:
            paths.append(value)
    return paths


def preflight(
    payload: dict,
    *,
    repo: Path | None,
    default_root: Path,
    required_since: str,
    contract_fields: Iterable[str],
    contract_statuses: Iterable[str],
    contract_baselines: Iterable[str],
) -> list[dict]:
    """Return typed reasons a groomed ticket cannot enter dispatch."""
    fields = tuple(contract_fields)
    statuses = set(contract_statuses)
    baselines = set(contract_baselines)
    root = (repo or default_root).resolve()
    if payload.get("status") == "contract-blocked":
        return [{"kind": "contract-blocked",
                 "reason": "status=contract-blocked is never dispatchable"}]
    groomed_at = str(payload.get("groomed_at") or "")
    if groomed_at and groomed_at < required_since \
            and not any(payload.get(field) is not None for field in fields):
        return []

    problems: list[dict] = []
    if payload.get("contract_status") not in statuses \
            or payload.get("contract_status") != "ready":
        problems.append({"kind": "contract-evidence-missing",
                         "reason": "contract_status is not ready"})
    if payload.get("contract_baseline") not in baselines \
            or payload.get("contract_baseline") != "red":
        problems.append({"kind": "contract-baseline-not-red",
                         "value": payload.get("contract_baseline") or "missing"})
    if not str(payload.get("contract_evidence") or "").strip():
        problems.append({"kind": "contract-evidence-missing",
                         "reason": "contract_evidence is empty"})
    for field in ("contract_checked_at", "contract_checked_by"):
        if not str(payload.get(field) or "").strip():
            problems.append({"kind": "contract-check-metadata-missing", "field": field})

    fix_site = str(payload.get("fix_site") or "").strip()
    if not fix_site:
        problems.append({"kind": "fix-site-missing"})
    else:
        for rel in site_paths(fix_site):
            if any(ch in rel for ch in "{}[]*$") or not (root / rel).exists():
                problems.append({"kind": "fix-site-missing", "path": rel})

    command = str(payload.get("acceptance_cmd") or "").strip()
    if not command:
        problems.append({"kind": "acceptance-dependency-missing",
                         "reason": "acceptance_cmd is empty"})
    else:
        for rel in command_paths(command):
            if any(ch in rel for ch in "{}[]*$") or not (root / rel).exists():
                problems.append({"kind": "acceptance-dependency-missing", "path": rel})
    return problems


_SHELL_OPERATOR_TOKENS = frozenset((";", "&&", "||", "|", "<", ">"))


def pytest_selector_probe(cmd: str) -> list[str] | None:
    """Return a safe argv probe for a direct ``pytest -k`` command."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None
    if not tokens or any(
            token in _SHELL_OPERATOR_TOKENS
            or any(operator in token for operator in (";", "|", "<", ">"))
            for token in tokens):
        return None
    pytest_indexes = [index for index, token in enumerate(tokens)
                      if Path(token).name == "pytest"]
    if not pytest_indexes:
        return None
    pytest_index = pytest_indexes[-1]
    args = tokens[pytest_index + 1:]
    try:
        selector_index = args.index("-k")
    except ValueError:
        return None
    if selector_index + 1 >= len(args) or not args[selector_index + 1].strip():
        return None
    probe = list(tokens)
    if "--collect-only" not in args:
        probe.insert(pytest_index + 1, "--collect-only")
    return probe


def pytest_collected_count(output: str) -> int | None:
    """Extract pytest's selected count, with a node-line fallback."""
    summary = re.search(r"\b(\d+)(?:/\d+)?\s+(?:tests?|items?)\s+collected\b",
                        output)
    if summary:
        return int(summary.group(1))
    if re.search(r"\bno tests collected\b", output, flags=re.IGNORECASE):
        return 0
    node_lines = [line for line in output.splitlines()
                  if "::" in line and not line.lstrip().startswith(("=", "-"))]
    return len(node_lines) if node_lines else None


def report_pytest_selector_count(
    entry_id: str,
    cmd: str,
    *,
    runner: Callable[..., object],
    root: Path,
    timeout_seconds: float,
) -> None:
    """Print a non-blocking selection count while an acceptance command is edited."""
    probe = pytest_selector_probe(cmd)
    if probe is None:
        return
    try:
        result = runner(
            probe,
            cwd=root,
            label_key="entry",
            label=entry_id,
            progress_prefix="[backlog][selector-count]",
            merge_stderr=True,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[backlog][selector-count] {entry_id} selected=unavailable "
              f"error={type(exc).__name__} (non-blocking)",
              file=sys.stderr, flush=True)
        return
    if getattr(result, "timed_out", False):
        print(f"[backlog][selector-count] {entry_id} selected=unavailable "
              f"timeout={timeout_seconds:g}s (non-blocking)",
              file=sys.stderr, flush=True)
        return
    output = result.stdout or ""
    count = pytest_collected_count(output)
    selected = str(count) if count is not None else "unavailable"
    print(f"[backlog][selector-count] {entry_id} selected={selected} "
          f"rc={result.returncode} (non-blocking)", file=sys.stderr, flush=True)
