#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Create immutable Gate-cost identities and audit acceptance command scope.

This module is deliberately read-only.  A fingerprint describes the exact inputs
that make a Gate or acceptance verdict meaningful; the audit reports findings but
never edits the ticket that supplied those inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from kg_board.scope import normalise_scope, scope_problems
from lib.worktree_gate_tiers import GateTierError, normalize_gate_tier

FINGERPRINT_SCHEMA = "kg.gate.cost-fingerprint.v1"
AUDIT_SCHEMA = "kg.gate.acceptance-audit.v1"
SHA256_LENGTH = 64
HEAD_LENGTH = 40

_REPO_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:ops|backend|ios|lab|docs|\.github)/"
    r"[A-Za-z0-9_./-]+)"
)
_SELECTOR_FLAGS = frozenset({
    "-g", "--grep", "-k", "--keyword", "-m", "--markers",
    "--file", "--test-filter", "--filter", "--only-testing",
    "-only-testing", "--test-name", "--test-class", "--nodeid",
})
_IOS_SELECTOR_VALUE_FLAGS = frozenset({
    "--dataset", "--dataset-file", "--device", "--destination", "--configuration",
    "--evidence-kind", "--evidence-locale", "--evidence-timezone",
    "--evidence-appearance", "--ui-launch-profile", "--coverage-fail-under",
})
_FULL_TEST_ROOTS = frozenset({"ops/tests", "backend/tests"})
_UI_PATH_RE = re.compile(r"(^|/)(?:.*UI|UITests?)(?:/|$)|(?:^|/)ios/", re.IGNORECASE)


class FingerprintError(ValueError):
    """Input or repository state cannot produce an honest fingerprint."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normalise_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FingerprintError("repository path must be a non-empty string")
    path = value.strip()
    if "\x00" in path or "\\" in path:
        raise FingerprintError(f"repository path is invalid: {value!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".."} for part in path.split("/")):
        raise FingerprintError(f"repository path must be relative: {value!r}")
    normalised = pure.as_posix()
    if normalised in {"", ".", ".."} or normalised.startswith("../"):
        raise FingerprintError(f"repository path is invalid: {value!r}")
    return normalised


def _repo_file(repo: Path, rel: str) -> Path:
    root = repo.resolve()
    candidate = (root / rel).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FingerprintError(f"repository path escapes repo: {rel!r}") from exc
    return candidate


def _unique_paths(values: Iterable[str]) -> list[str]:
    result: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            result.add(_normalise_path(value))
    return sorted(result)


def _file_entries(repo: Path, paths: Iterable[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for rel in _unique_paths(paths):
        path = _repo_file(repo, rel)
        entry: dict[str, Any] = {"path": rel}
        if not path.exists():
            entry["state"] = "missing"
        elif path.is_dir():
            entry["state"] = "directory"
        else:
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise FingerprintError(f"cannot read fingerprint input {rel}: {exc}") from exc
            entry.update({"state": "file", "sha256": hashlib.sha256(content).hexdigest()})
        entries.append(entry)
    return entries


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True,
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise FingerprintError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _porcelain_paths(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        value = line[3:] if len(line) >= 3 else line
        if " -> " in value:
            value = value.rsplit(" -> ", 1)[-1]
        if value:
            paths.append(value)
    return paths


def changed_paths(repo: Path, base: str = "main") -> list[str]:
    """Return committed and working-tree paths used by the current Gate input."""
    names: set[str] = set()
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"], cwd=repo,
        text=True, capture_output=True, check=False,
    )
    if diff.returncode != 0:
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..HEAD"], cwd=repo,
            text=True, capture_output=True, check=False,
        )
    if diff.returncode == 0:
        names.update(line for line in diff.stdout.splitlines() if line)
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo,
        text=True, capture_output=True, check=False,
    )
    if status.returncode == 0:
        names.update(_porcelain_paths(status.stdout))
    if not names and diff.returncode != 0:
        detail = diff.stderr.strip() or "base ref is unavailable"
        raise FingerprintError(f"cannot determine changed files: {detail}")
    return _unique_paths(names)


def _scope_value(scope: Any) -> dict[str, Any]:
    if scope is None or scope == "":
        return {"status": "unknown", "files": []}
    if isinstance(scope, dict):
        problems = scope_problems(scope)
        if problems:
            return {"status": "unknown", "value": scope, "problems": problems}
        try:
            return normalise_scope(scope)
        except ValueError as exc:
            return {"status": "unknown", "value": scope, "problems": [str(exc)]}
    if isinstance(scope, str):
        return {"status": "unknown", "value": scope}
    return {"status": "unknown", "value": scope}


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        result: list[str] = []
        for key in ("path", "file", "name", "value"):
            if isinstance(value.get(key), str):
                result.append(value[key])
        return result
    return []


def _repo_paths_from_command(command: str) -> list[str]:
    return _unique_paths(match.group(1).rstrip(".,;:'\")") for match in _REPO_PATH_RE.finditer(command))


def _test_paths_from_tokens(tokens: Sequence[str]) -> list[str]:
    """Find relative test files even when the command uses a non-standard root."""
    candidates: list[str] = []
    for token in tokens:
        if token.startswith("-") or "://" in token:
            continue
        candidate = token.split("::", 1)[0]
        if not candidate.endswith((".py", ".sh", ".swift")):
            continue
        try:
            normalised = _normalise_path(candidate)
        except FingerprintError:
            continue
        if _is_test_path(normalised):
            candidates.append(normalised)
    return candidates


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _flag_values(tokens: Sequence[str], names: set[str]) -> list[str]:
    values: list[str] = []
    for index, token in enumerate(tokens):
        if token in names and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        for name in names:
            prefix = name + "="
            if token.startswith(prefix):
                values.append(token[len(prefix):])
    return values


def _selector_values(tokens: Sequence[str]) -> list[str]:
    values: list[str] = []
    for index, token in enumerate(tokens):
        if token in _SELECTOR_FLAGS and index + 1 < len(tokens):
            values.append(f"{token}={tokens[index + 1]}")
        elif token.startswith(("-only-testing:", "--only-testing=")):
            values.append(token)
    return sorted(set(values))


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return (
        "/tests/" in lowered
        or lowered.startswith(("tests/", "ops/test", "test_"))
        or lowered.endswith(("_test.py", "_tests.swift", "uitests.swift"))
    )


def _definition_paths(
    repo: Path, command: str, explicit: Iterable[str], tokens: Sequence[str],
) -> list[str]:
    candidates = list(explicit)
    candidates.extend(path for path in _repo_paths_from_command(command) if _is_test_path(path))
    candidates.extend(_test_paths_from_tokens(tokens))
    file_values = _flag_values(tokens, {"--file"})
    for value in file_values:
        if "/" in value:
            candidates.append(value)
            continue
        stem = value.removesuffix(".swift")
        for root in (
            repo / "ios" / "BooksAndVocabTests",
            repo / "ios" / "BooksAndVocabUITests",
        ):
            if not root.is_dir():
                continue
            for path in root.glob(f"{stem}.swift"):
                candidates.append(path.relative_to(repo).as_posix())
    return _unique_paths(candidates)


def _fixture_paths(command: str, explicit: Iterable[str], tokens: Sequence[str]) -> list[str]:
    candidates = list(explicit)
    candidates.extend(
        path for path in _repo_paths_from_command(command)
        if "fixture" in path.lower() or path.startswith("ops/demo/generated/")
    )
    for value in _flag_values(tokens, {"--dataset-file", "--fixture", "--fixture-file"}):
        candidates.extend([value])
    for value in _flag_values(tokens, {"--dataset"}):
        if "/" not in value and not value.endswith(".json"):
            candidates.append(f"ops/fixtures/ui_worlds/{value}.json")
        else:
            candidates.append(value)
    return _unique_paths(candidates)


def _test_definition(
    repo: Path, command: str, explicit: Iterable[str], tokens: Sequence[str],
) -> dict[str, Any]:
    paths = _definition_paths(repo, command, explicit, tokens)
    selectors = _selector_values(tokens)
    group_markers: list[str] = []
    for index, token in enumerate(tokens):
        if Path(token).name in {"test_ops.sh", "test_ios_ops.sh"} and index + 1 < len(tokens):
            group_markers.append(f"{Path(token).name}:{tokens[index + 1]}")
    if not paths and not selectors and not group_markers:
        group_markers.append("command-only")
    return {
        "files": _file_entries(repo, paths),
        "selectors": selectors,
        "groups": sorted(set(group_markers)),
    }


def _fixture_definition(repo: Path, command: str, explicit: Iterable[str], tokens: Sequence[str]) -> dict[str, Any]:
    paths = _fixture_paths(command, explicit, tokens)
    return {"files": _file_entries(repo, paths)}


def _run_version(command: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            list(command), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable:{type(exc).__name__}"
    output = "\n".join(line.rstrip() for line in result.stdout.splitlines()).strip()
    return output or f"unavailable:exit-{result.returncode}"


def collect_toolchain() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "uv": _run_version(("uv", "--version")),
        "swift": _run_version(("swift", "--version")),
        "xcode": _run_version(("xcodebuild", "-version")),
        "xcode_select": _run_version(("xcode-select", "-p")),
    }


def _previous_fingerprint(ticket: Mapping[str, Any], supplied: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if supplied is not None:
        return supplied
    for key in ("gate_fingerprint", "fingerprint", "acceptance_fingerprint", "verdict_fingerprint"):
        value = ticket.get(key)
        if isinstance(value, dict):
            return value
    evidence = ticket.get("gate_evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("fingerprint"), dict):
        return evidence["fingerprint"]
    return None


def build_fingerprint(
    repo: Path | str,
    *,
    changed_files: Iterable[str] | None = None,
    acceptance_command: str = "",
    test_definitions: Iterable[str] | None = None,
    fixtures: Iterable[str] | None = None,
    scope: Any = None,
    gate_tier: str | None = None,
    base: str = "main",
    toolchain: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable identity from the current checkout and supplied contract."""
    root = Path(repo).resolve()
    head = _git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head):
        raise FingerprintError(f"git returned a non-exact HEAD: {head!r}")
    current_changed = _unique_paths(changed_files) if changed_files is not None else changed_paths(root, base)
    command = str(acceptance_command or "").strip()
    tokens = _command_tokens(command)
    definition = _test_definition(root, command, test_definitions or (), tokens)
    fixture_definition = _fixture_definition(root, command, fixtures or (), tokens)
    changed_entries = _file_entries(root, current_changed)
    scope_value = _scope_value(scope)
    tier = normalize_gate_tier(gate_tier)
    toolchain_value = dict(toolchain) if toolchain is not None else collect_toolchain()
    toolchain_version = toolchain_value.get("xcode") or toolchain_value.get("xcodebuild")
    if not isinstance(toolchain_version, str) or not toolchain_version.strip():
        raise FingerprintError("toolchain must include a non-empty Xcode/toolchain version")
    result: dict[str, Any] = {
        "schema": FINGERPRINT_SCHEMA,
        "exact_head": head,
        "head_sha": head,
        "changed_files": changed_entries,
        "changed_file_digest": _digest(changed_entries),
        "acceptance_command": command,
        "acceptance_command_digest": _digest({"command": command}),
        "test_definition": definition,
        "test_definition_digest": _digest(definition),
        "fixtures": fixture_definition,
        "fixture_digest": _digest(fixture_definition),
        "toolchain": toolchain_value,
        "toolchain_version": toolchain_version,
        "scope": scope_value,
        "gate_tier": tier,
    }
    if _git(root, "rev-parse", "HEAD") != head:
        raise FingerprintError("HEAD changed while fingerprint inputs were being read; re-run")
    result["fingerprint_digest"] = _digest(result)
    return result


def _finding(code: str, severity: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


def _is_ui_ticket(ticket: Mapping[str, Any], fingerprint: Mapping[str, Any]) -> bool:
    if str(ticket.get("id") or "").upper().startswith("APP-"):
        return True
    values: list[str] = [str(ticket.get("fix_site") or "")]
    scope = fingerprint.get("scope")
    if isinstance(scope, dict):
        values.extend(str(item.get("path") or "") for item in scope.get("files", []) if isinstance(item, dict))
    return any(_UI_PATH_RE.search(value) for value in values)


def _has_precise_selector(tokens: Sequence[str]) -> bool:
    for index, token in enumerate(tokens):
        if token in _SELECTOR_FLAGS and index + 1 < len(tokens) and tokens[index + 1].strip():
            return True
        if token.startswith(("-only-testing:", "--only-testing=")):
            return True
        if "::" in token and not token.startswith("http"):
            return True
        if token.endswith((".py", ".sh", ".swift")):
            try:
                if _is_test_path(_normalise_path(token)):
                    return True
            except FingerprintError:
                pass
    for index, token in enumerate(tokens):
        if Path(token).name not in {"ios_test.sh", "ios_ops.sh"}:
            continue
        after_runner = list(tokens[index + 1:])
        if not after_runner or after_runner[0] != "test":
            continue
        after_runner = after_runner[1:]
        value_index = 0
        while value_index < len(after_runner):
            value = after_runner[value_index]
            if value in {"test", "--json", "--list", "--lease", "--unit", "--ui", "--all-targets"}:
                value_index += 1
                continue
            if value in _IOS_SELECTOR_VALUE_FLAGS:
                value_index += 2
                continue
            if value.startswith("-"):
                value_index += 1
                continue
            return True
    return False


def _full_group_reasons(tokens: Sequence[str]) -> list[str]:
    reasons: list[str] = []
    names = [Path(token).name for token in tokens]
    if "--all-targets" in tokens:
        reasons.append("--all-targets")
    for index, name in enumerate(names):
        if name == "test_ops.sh":
            next_value = tokens[index + 1] if index + 1 < len(tokens) else ""
            if not next_value or not next_value.startswith("-"):
                reasons.append("test_ops group")
        if name in {"ios_test.sh", "ios_ops.sh"} and (
            "--all-targets" in tokens
            or (any(flag in tokens for flag in ("--unit", "--ui"))
                and not _has_precise_selector(tokens))
        ):
            reasons.append(f"{name} unfiltered scope")
    pytest_indices = [index for index, token in enumerate(tokens) if Path(token).name == "pytest"]
    for index in pytest_indices:
        args = list(tokens[index + 1:])
        if (
            (any(root in args for root in _FULL_TEST_ROOTS) or not any(
                token.endswith((".py", ".sh", ".swift")) or "::" in token for token in args
            ))
            and not _has_precise_selector(tokens)
        ):
            reasons.append("pytest full group")
    return sorted(set(reasons))


def _prior_has_verdict(ticket: Mapping[str, Any]) -> bool:
    return any(
        ticket.get(key) not in (None, "", [], {})
        for key in ("verdict", "verified_evidence", "gate_verdict", "resolution", "fixed_by")
    )


def _compare_previous(
    previous: Mapping[str, Any], current: Mapping[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    required_fields = {
        "schema", "exact_head", "head_sha", "changed_files", "changed_file_digest",
        "acceptance_command", "acceptance_command_digest", "test_definition",
        "test_definition_digest", "fixtures", "fixture_digest", "toolchain",
        "toolchain_version", "scope", "gate_tier", "fingerprint_digest",
    }
    missing_fields = sorted(field for field in required_fields if field not in previous)
    if missing_fields:
        findings.append(_finding(
            "fingerprint-fields-missing", "block",
            "previous fingerprint is incomplete; verdict cannot be reused",
            fields=missing_fields,
        ))
    if previous.get("schema") != FINGERPRINT_SCHEMA:
        findings.append(_finding(
            "fingerprint-schema-mismatch", "block",
            "previous fingerprint schema is not the current Gate-cost identity contract",
            previous=previous.get("schema"), current=FINGERPRINT_SCHEMA,
        ))
    previous_digest = previous.get("fingerprint_digest")
    if previous_digest:
        payload = {key: value for key, value in previous.items() if key != "fingerprint_digest"}
        expected_digest = _digest(payload)
        if previous_digest != expected_digest:
            findings.append(_finding(
                "fingerprint-digest-invalid", "block",
                "previous fingerprint digest does not match its recorded inputs",
            ))
    else:
        findings.append(_finding(
            "fingerprint-digest-missing", "block",
            "previous fingerprint has no integrity digest; verdict cannot be reused",
        ))

    def previous_value(key: str) -> Any:
        if key == "head_sha":
            return previous.get("head_sha") or previous.get("exact_head") or previous.get("head")
        return previous.get(key)

    comparisons = (
        ("changed_file_digest", "stale-changed-files", "changed files changed"),
        ("head_sha", "stale-head", "HEAD changed"),
        ("acceptance_command_digest", "stale-acceptance-command", "acceptance command changed"),
        ("fixture_digest", "stale-fixture", "fixture input changed"),
        ("test_definition_digest", "stale-test-definition", "test definition changed"),
    )
    for key, code, message in comparisons:
        old = previous_value(key)
        new = current.get(key)
        if old not in (None, "") and old != new:
            findings.append(_finding(code, "block", f"cannot reuse verdict: {message}", previous=old, current=new))
        elif old in (None, ""):
            findings.append(_finding(f"{code}-missing", "block", f"previous fingerprint has no {key}"))
    if previous.get("toolchain") in (None, {}):
        findings.append(_finding("toolchain-missing", "block", "previous fingerprint has no toolchain/Xcode version"))
    elif previous.get("toolchain") != current.get("toolchain"):
        findings.append(_finding(
            "stale-toolchain", "block", "cannot reuse verdict: toolchain/Xcode version changed",
            previous=previous.get("toolchain"), current=current.get("toolchain"),
        ))
    if previous.get("scope") in (None, {}):
        findings.append(_finding("scope-missing", "block", "previous fingerprint has no scope"))
    elif previous.get("scope") != current.get("scope"):
        findings.append(_finding("stale-scope", "block", "cannot reuse verdict: scope changed"))
    if previous.get("gate_tier") in (None, ""):
        findings.append(_finding("gate-tier-missing", "block", "previous fingerprint has no Gate tier"))
    elif previous.get("gate_tier") != current.get("gate_tier"):
        findings.append(_finding("stale-gate-tier", "block", "cannot reuse verdict: Gate tier changed"))
    return findings


def audit_acceptance(
    ticket: Mapping[str, Any],
    *,
    repo: Path | str,
    previous_fingerprint: Mapping[str, Any] | None = None,
    toolchain: Mapping[str, Any] | None = None,
    base: str = "main",
) -> dict[str, Any]:
    """Audit a ticket without executing its acceptance command or mutating it."""
    root = Path(repo).resolve()
    command = str(ticket.get("acceptance_cmd") or ticket.get("acceptance_command") or "").strip()
    scope = ticket.get("scope")
    scope_obj = _scope_value(scope)
    changed = ticket.get("changed_files")
    changed_files = _string_values(changed) if changed is not None else changed_paths(root, base)
    definitions: list[str] = []
    for key in ("test_definitions", "test_definition", "test_files", "test_paths"):
        definitions.extend(_string_values(ticket.get(key)))
    fixtures: list[str] = []
    for key in ("fixtures", "fixture", "fixture_paths", "dataset_file"):
        fixtures.extend(_string_values(ticket.get(key)))
    try:
        current = build_fingerprint(
            root,
            changed_files=changed_files,
            acceptance_command=command,
            test_definitions=definitions,
            fixtures=fixtures,
            scope=scope,
            gate_tier=ticket.get("gate_tier") or ticket.get("required_tier"),
            base=base,
            toolchain=toolchain,
        )
    except (FingerprintError, GateTierError, TypeError, ValueError) as exc:
        return {
            "schema": AUDIT_SCHEMA,
            "ticket_id": ticket.get("id"),
            "fingerprint": None,
            "findings": [_finding("fingerprint-unavailable", "block", str(exc))],
            "verdict_reuse": {"allowed": False, "reason": "current fingerprint unavailable"},
            "ticket_mutated": False,
        }

    findings: list[dict[str, Any]] = []
    if not command:
        findings.append(_finding("acceptance-command-missing", "block", "ticket has no acceptance command"))
    tokens = _command_tokens(command)
    if command and not tokens:
        findings.append(_finding("acceptance-command-unparseable", "block", "acceptance command is not safely tokenizable"))
    try:
        tier = normalize_gate_tier(ticket.get("gate_tier") or ticket.get("required_tier"))
    except GateTierError:
        tier = current["gate_tier"]
        findings.append(_finding("invalid-gate-tier", "block", "ticket Gate tier is invalid", value=ticket.get("gate_tier")))
    if ticket.get("gate_tier") in (None, "") and ticket.get("required_tier") in (None, ""):
        findings.append(_finding("gate-tier-missing", "block", "ticket does not state a Gate tier"))
    if scope_obj.get("status") == "unknown":
        findings.append(_finding("scope-missing-or-legacy", "block", "ticket scope is not structured and cannot be fingerprinted"))

    full_reasons = _full_group_reasons(tokens)
    if full_reasons and tier not in {"S3", "S4"}:
        findings.append(_finding(
            "unnecessary-full-test-group", "warn",
            "acceptance command selects a complete test group at a non-release tier",
            reasons=full_reasons, gate_tier=tier,
        ))
        if not _has_precise_selector(tokens):
            findings.append(_finding(
                "missing-test-scope-selector", "warn",
                "acceptance command lacks --file, -g, -k, nodeid, or an equivalent restriction",
                reasons=full_reasons,
            ))
    if _is_ui_ticket(ticket, current) and command and not _has_precise_selector(tokens):
        findings.append(_finding(
            "ui-ticket-missing-precise-selector", "warn",
            "UI ticket acceptance must use --file, -g, or an equivalent precise selector",
        ))

    previous = _previous_fingerprint(ticket, previous_fingerprint)
    if previous is not None:
        findings.extend(_compare_previous(previous, current))
    elif _prior_has_verdict(ticket):
        findings.append(_finding(
            "verdict-fingerprint-missing", "block",
            "a prior verdict exists without a complete current-input fingerprint; it cannot be reused",
        ))
    stale_codes = {
        "stale-changed-files", "stale-head", "stale-acceptance-command", "stale-fixture", "stale-test-definition",
        "stale-toolchain", "stale-scope", "stale-gate-tier", "verdict-fingerprint-missing",
        "stale-changed-files-missing", "stale-head-missing", "stale-acceptance-command-missing",
        "stale-fixture-missing", "stale-test-definition-missing", "toolchain-missing", "scope-missing",
        "gate-tier-missing",
    }
    blocked_reuse = any(
        item["severity"] == "block" or item["code"] in stale_codes
        for item in findings
    )
    return {
        "schema": AUDIT_SCHEMA,
        "ticket_id": ticket.get("id"),
        "fingerprint": current,
        "findings": findings,
        "verdict_reuse": {
            "allowed": bool(previous is not None and not blocked_reuse),
            "reason": "all fingerprint identities match" if previous is not None and not blocked_reuse
            else "current identity is missing or stale",
        },
        "ticket_mutated": False,
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FingerprintError(f"cannot read JSON {path}: {exc}") from exc


def _scope_from_args(args: argparse.Namespace) -> Any:
    if args.scope_file:
        return _load_json(Path(args.scope_file))
    if args.scope_json:
        try:
            return json.loads(args.scope_json)
        except json.JSONDecodeError as exc:
            raise FingerprintError(f"invalid --scope-json: {exc}") from exc
    return args.ticket_payload.get("scope") if args.ticket_payload else None


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--base", default="main", help="base ref for changed-file discovery")
    parser.add_argument("--acceptance-command", default=None)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--test-definition", action="append", default=[])
    parser.add_argument("--fixture", action="append", default=[])
    parser.add_argument("--scope-file")
    parser.add_argument("--scope-json")
    parser.add_argument("--gate-tier")
    parser.add_argument("--toolchain-file")


def _command_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fp = sub.add_parser("fingerprint", help="emit a current Gate-cost fingerprint")
    _common_parser(fp)
    fp.add_argument("--ticket")
    audit = sub.add_parser("audit", help="emit acceptance scope findings without mutation")
    audit.add_argument("--ticket", required=True)
    audit.add_argument("--previous-fingerprint")
    audit.add_argument("--repo", default=".")
    audit.add_argument("--base", default="main")
    audit.add_argument("--toolchain-file")
    return parser


def _toolchain_arg(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    value = _load_json(Path(path))
    if not isinstance(value, dict):
        raise FingerprintError("toolchain JSON must be an object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = _command_args()
    args = parser.parse_args(argv)
    try:
        if args.command == "fingerprint":
            ticket_payload: dict[str, Any] = {}
            if args.ticket:
                loaded = _load_json(Path(args.ticket))
                if not isinstance(loaded, dict):
                    raise FingerprintError("ticket JSON must be an object")
                ticket_payload = loaded
            args.ticket_payload = ticket_payload
            command = args.acceptance_command
            if command is None:
                command = ticket_payload.get("acceptance_cmd") or ticket_payload.get("acceptance_command") or ""
            changed = args.changed_file or ticket_payload.get("changed_files")
            definitions = args.test_definition or ticket_payload.get("test_definitions") or ticket_payload.get("test_files") or []
            fixtures = args.fixture or ticket_payload.get("fixtures") or ticket_payload.get("fixture") or []
            tier = args.gate_tier or ticket_payload.get("gate_tier") or ticket_payload.get("required_tier")
            result = build_fingerprint(
                Path(args.repo), changed_files=changed or None, acceptance_command=command,
                test_definitions=_string_values(definitions), fixtures=_string_values(fixtures),
                scope=_scope_from_args(args), gate_tier=tier, base=args.base,
                toolchain=_toolchain_arg(args.toolchain_file),
            )
        else:
            ticket = _load_json(Path(args.ticket))
            if not isinstance(ticket, dict):
                raise FingerprintError("ticket JSON must be an object")
            previous = _load_json(Path(args.previous_fingerprint)) if args.previous_fingerprint else None
            if previous is not None and not isinstance(previous, dict):
                raise FingerprintError("previous fingerprint JSON must be an object")
            result = audit_acceptance(
                ticket, repo=Path(args.repo), previous_fingerprint=previous,
                base=args.base, toolchain=_toolchain_arg(args.toolchain_file),
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (FingerprintError, GateTierError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"schema": FINGERPRINT_SCHEMA, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
