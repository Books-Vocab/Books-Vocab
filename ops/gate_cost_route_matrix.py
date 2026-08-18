#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Pure changed-file and Gate-cost fingerprint routing policy.

The matrix describes the cheapest *known* verification tier.  It never executes
a runner and it does not treat an unknown input as a cheap route: unknown,
malformed, or contradictory inputs return a machine-readable fail-closed
decision for a Manager to adjudicate.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Iterable, Mapping
from typing import Any

from lib.worktree_gate_tiers import (
    GATE_TIERS,
    TIER_RANK,
    GateTierError,
    normalize_gate_tier,
)

ROUTE_SCHEMA = "kg.gate.cost-route.v1"
ROUTE_MATRIX_SCHEMA = "kg.gate.cost-route-matrix.v1"
FINGERPRINT_SCHEMA = "kg.gate.cost-fingerprint.v1"
VERSION = 1
UNKNOWN_ROUTE_ID = "gate.unknown.fail-closed"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_HEAD_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_FUNCTIONAL_ROOTS = frozenset({"backend", "ios", "lab", "ops", "design-system"})
_NEUTRAL_PREFIXES = ("docs/", "README", "CHANGELOG", "LICENSE")
_CONTROL_PLANE_EXACT = frozenset({
    "ops/worktree_orchestrate.py",
    "ops/ios_test.sh",
    "ops/test_ops.sh",
})
_CONTROL_PLANE_PREFIXES = (
    "ops/lib/worktree_orchestrator_",
    "ops/worktree_registry.py",
    "ops/context_route.py",
    "ops/skill_route.py",
    ".github/",
    ".claude/skills/",
)
_UI_MARKERS = (
    "/views/",
    "/ui/",
    "/uicomponents/",
    "/components/",
    "/uitests/",
    "/snapshots/",
)

ROUTE_MATRIX: dict[str, dict[str, str]] = {
    "S0": {
        "route_id": "gate.s0.static",
        "kind": "static",
        "acceptance_route": "static",
    },
    "S1": {
        "route_id": "gate.s1.focused",
        "kind": "focused",
        "acceptance_route": "unit-ops",
    },
    "S2": {
        "route_id": "gate.s2.precise",
        "kind": "precise",
        "acceptance_route": "ui-precise",
    },
    "S3": {
        "route_id": "gate.s3.integration",
        "kind": "integration",
        "acceptance_route": "full-gate",
    },
    "S4": {
        "route_id": "gate.s4.release",
        "kind": "release",
        "acceptance_route": "release-full",
    },
}


class RouteContractError(ValueError):
    """Raised when a caller supplies an unsafe repository path."""


def _normalise_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouteContractError("changed file paths must be non-empty strings")
    raw = value.strip().replace("\\", "/")
    if "\x00" in raw:
        raise RouteContractError("changed file path contains NUL")
    path = posixpath.normpath(raw).removeprefix("./")
    if path in {"", ".", ".."} or path.startswith(("/", "../")) or "/../" in f"/{path}/":
        raise RouteContractError(
            f"changed file path must be repository-relative: {value!r}"
        )
    return path


def normalize_changed_files(changed_files: Iterable[str] | None) -> list[str] | None:
    """Normalize caller-supplied paths while preserving an omitted input."""
    if changed_files is None:
        return None
    if isinstance(changed_files, (str, bytes)):
        raise RouteContractError("changed_files must be an iterable of paths")
    return sorted({_normalise_path(path) for path in changed_files})


def _is_neutral(path: str) -> bool:
    return path.startswith(_NEUTRAL_PREFIXES) or path in {".gitignore", "LICENSE"}


def _is_control_plane(path: str) -> bool:
    return path in _CONTROL_PLANE_EXACT or path.startswith(_CONTROL_PLANE_PREFIXES)


def _is_shared_fixture(path: str) -> bool:
    parts = path.lower().split("/")
    basename = parts[-1]
    return (
        "fixtures" in parts
        or "fixture" in parts
        or "fixture" in basename
        or ("snapshot" in basename and parts[0] in _FUNCTIONAL_ROOTS)
    )


def _is_ui_surface(path: str) -> bool:
    lowered = path.lower()
    if not lowered.startswith("ios/"):
        return False
    parts = lowered.split("/")
    return any(marker in lowered for marker in _UI_MARKERS) or any(
        part.endswith(("uitest", "uitests", "ui_test", "ui_tests"))
        for part in parts[1:]
    )


def _minimum_for_files(changed_files: list[str]) -> tuple[str | None, list[str]]:
    if not changed_files:
        return "S0", ["no-changes"]

    roots = {path.split("/", 1)[0] for path in changed_files}
    unknown = [
        path
        for path in changed_files
        if not _is_neutral(path)
        and not _is_control_plane(path)
        and path.split("/", 1)[0] not in _FUNCTIONAL_ROOTS
    ]
    if unknown:
        return None, ["unknown-surface", *[f"unknown-path:{path}" for path in unknown]]

    reasons: list[str] = []
    if len(roots & _FUNCTIONAL_ROOTS) >= 2:
        reasons.append("cross-functional-surface")
    if any(_is_control_plane(path) for path in changed_files):
        reasons.append("control-plane")
    if any(_is_shared_fixture(path) for path in changed_files):
        reasons.append("shared-fixture")

    if reasons:
        return "S3", reasons
    if any(_is_ui_surface(path) or path.split("/", 1)[0] == "design-system" for path in changed_files):
        return "S2", ["ui-or-design-system-surface"]
    if roots & _FUNCTIONAL_ROOTS:
        return "S1", ["single-functional-surface"]
    return "S0", ["neutral-surface"]


def _fingerprint_paths(fingerprint: Mapping[str, Any]) -> list[str]:
    raw_files = fingerprint.get("changed_files")
    if not isinstance(raw_files, list):
        raise RouteContractError("fingerprint changed_files must be a list")
    paths: list[str] = []
    for entry in raw_files:
        if isinstance(entry, Mapping):
            path = entry.get("path")
        else:
            path = entry
        if not isinstance(path, str):
            raise RouteContractError("fingerprint changed_files entries need a path")
        paths.append(path)
    return normalize_changed_files(paths) or []


def _fingerprint_summary(
    fingerprint: Mapping[str, Any] | None,
    *,
    valid: bool,
    tier: str | None = None,
    problems: list[str] | None = None,
) -> dict[str, Any]:
    if fingerprint is None:
        return {
            "provided": False,
            "valid": False,
            "schema": None,
            "gate_tier": None,
            "fingerprint_digest": None,
            "problems": [],
        }
    return {
        "provided": True,
        "valid": valid,
        "schema": fingerprint.get("schema"),
        "gate_tier": tier,
        "fingerprint_digest": fingerprint.get("fingerprint_digest"),
        "problems": sorted(set(problems or [])),
    }


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_fingerprint(
    fingerprint: Mapping[str, Any] | None,
) -> tuple[bool, list[str], list[str], str | None, dict[str, Any]]:
    if fingerprint is None:
        return True, [], [], None, _fingerprint_summary(None, valid=False)
    if not isinstance(fingerprint, Mapping):
        summary = _fingerprint_summary(None, valid=False, problems=["fingerprint-not-object"])
        return False, ["fingerprint-not-object"], [], None, summary

    problems: list[str] = []
    if fingerprint.get("schema") != FINGERPRINT_SCHEMA:
        problems.append("fingerprint-schema-unknown")

    try:
        paths = _fingerprint_paths(fingerprint)
    except RouteContractError as exc:
        problems.append(f"fingerprint-files-invalid:{exc}")
        paths = []

    raw_tier = fingerprint.get("gate_tier")
    tier: str | None = None
    if raw_tier in (None, ""):
        problems.append("fingerprint-tier-missing")
    else:
        try:
            tier = normalize_gate_tier(str(raw_tier))
        except GateTierError:
            problems.append("fingerprint-tier-unknown")

    exact_head = fingerprint.get("exact_head")
    head_sha = fingerprint.get("head_sha")
    if not isinstance(exact_head, str) or not _HEAD_RE.fullmatch(exact_head):
        problems.append("fingerprint-exact-head-invalid")
    if not isinstance(head_sha, str) or not _HEAD_RE.fullmatch(head_sha):
        problems.append("fingerprint-head-invalid")
    elif isinstance(exact_head, str) and exact_head != head_sha:
        problems.append("fingerprint-head-mismatch")
    digest = fingerprint.get("fingerprint_digest")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        problems.append("fingerprint-digest-invalid")
    else:
        try:
            body = dict(fingerprint)
            body.pop("fingerprint_digest", None)
            if digest != _canonical_digest(body):
                problems.append("fingerprint-digest-mismatch")
        except (TypeError, ValueError):
            problems.append("fingerprint-digest-uncomputable")

    raw_changed_files = fingerprint.get("changed_files")
    if not isinstance(raw_changed_files, list):
        problems.append("fingerprint-files-invalid")
    elif not isinstance(fingerprint.get("changed_file_digest"), str) \
            or not _SHA256_RE.fullmatch(fingerprint["changed_file_digest"]):
        problems.append("fingerprint-changed-file-digest-invalid")
    else:
        try:
            if fingerprint["changed_file_digest"] != _canonical_digest(raw_changed_files):
                problems.append("fingerprint-changed-file-digest-mismatch")
        except (TypeError, ValueError):
            problems.append("fingerprint-changed-file-digest-uncomputable")

    scope = fingerprint.get("scope")
    if not isinstance(scope, Mapping) or scope.get("schema") != "kg.backlog.scope.v1":
        problems.append("fingerprint-scope-unknown")
    else:
        scope_files = scope.get("files")
        scope_paths: list[str] = []
        if not isinstance(scope_files, list) or not scope_files:
            problems.append("fingerprint-scope-files-invalid")
        else:
            for item in scope_files:
                if not isinstance(item, Mapping) or item.get("operation") not in {"add", "modify"}:
                    problems.append("fingerprint-scope-files-invalid")
                    continue
                try:
                    scope_paths.append(_normalise_path(item.get("path")))
                except (RouteContractError, TypeError):
                    problems.append("fingerprint-scope-files-invalid")
            if len(scope_paths) != len(set(scope_paths)):
                problems.append("fingerprint-scope-files-invalid")
            if sorted(scope_paths) != paths:
                problems.append("fingerprint-scope-files-mismatch")

    valid = not problems
    summary = _fingerprint_summary(
        fingerprint, valid=valid, tier=tier, problems=problems,
    )
    return valid, problems, paths, tier, summary


def _unknown_decision(
    *,
    changed_files: list[str] | None,
    fingerprint: dict[str, Any],
    reasons: Iterable[str],
    minimum_tier: str | None = None,
) -> dict[str, Any]:
    normalized_reasons = sorted({str(reason) for reason in reasons if reason})
    return {
        "schema": ROUTE_SCHEMA,
        "version": VERSION,
        "changed_files": changed_files or [],
        "fingerprint": fingerprint,
        "minimum_tier": minimum_tier,
        "requested_tier": None,
        "selected_tier": None,
        "gate_tier": None,
        "route_id": UNKNOWN_ROUTE_ID,
        "route": None,
        "reasons": normalized_reasons or ["unknown-input"],
        "fail_closed": True,
        "fallback": True,
        "eligible": False,
    }


def route(
    *,
    changed_files: Iterable[str] | None = None,
    fingerprint: Mapping[str, Any] | None = None,
    requested_tier: str | None = None,
) -> dict[str, Any]:
    """Resolve changed files and an optional exact fingerprint to one tier.

    A fingerprint tier is an explicit upper route request.  It may raise the
    file-derived minimum, but it may never understate it.  S4 is only valid when
    the fingerprint itself explicitly carries ``gate_tier=S4``.
    """
    paths = normalize_changed_files(changed_files)
    fp_valid, fp_problems, fp_paths, fp_tier, fp_summary = _validate_fingerprint(fingerprint)
    reasons: list[str] = []

    if changed_files is None and fingerprint is None:
        return _unknown_decision(
            changed_files=None,
            fingerprint=fp_summary,
            reasons=["routing-input-missing"],
        )
    if fingerprint is not None and not fp_valid:
        return _unknown_decision(
            changed_files=paths if paths is not None else fp_paths,
            fingerprint=fp_summary,
            reasons=fp_problems,
        )
    if paths is None:
        paths = fp_paths
    elif fingerprint is not None and paths != fp_paths:
        return _unknown_decision(
            changed_files=paths,
            fingerprint=fp_summary,
            reasons=["fingerprint-files-mismatch"],
        )

    minimum_tier, minimum_reasons = _minimum_for_files(paths)
    if minimum_tier is None:
        return _unknown_decision(
            changed_files=paths,
            fingerprint=fp_summary,
            reasons=minimum_reasons,
        )
    reasons.extend(minimum_reasons)

    requested: str | None = None
    if requested_tier not in (None, ""):
        try:
            requested = normalize_gate_tier(str(requested_tier))
        except GateTierError:
            return _unknown_decision(
                changed_files=paths,
                fingerprint=fp_summary,
                reasons=["requested-tier-unknown"],
                minimum_tier=minimum_tier,
            )
        if requested == "S4" and (fingerprint is None or fp_tier != "S4"):
            return _unknown_decision(
                changed_files=paths,
                fingerprint=fp_summary,
                reasons=["s4-requires-explicit-release-fingerprint"],
                minimum_tier=minimum_tier,
            )
        if TIER_RANK[requested] < TIER_RANK[minimum_tier]:
            return _unknown_decision(
                changed_files=paths,
                fingerprint=fp_summary,
                reasons=["requested-tier-below-required"],
                minimum_tier=minimum_tier,
            )

    if fp_tier is not None and TIER_RANK[fp_tier] < TIER_RANK[minimum_tier]:
        return _unknown_decision(
            changed_files=paths,
            fingerprint=fp_summary,
            reasons=["fingerprint-tier-below-required"],
            minimum_tier=minimum_tier,
        )

    selected = max(
        (minimum_tier, fp_tier, requested),
        key=lambda value: TIER_RANK[value] if value is not None else -1,
    )
    if selected == "S4" and fp_tier != "S4":
        return _unknown_decision(
            changed_files=paths,
            fingerprint=fp_summary,
            reasons=["s4-requires-explicit-release-fingerprint"],
            minimum_tier=minimum_tier,
        )

    route_info = dict(ROUTE_MATRIX[selected])
    return {
        "schema": ROUTE_SCHEMA,
        "version": VERSION,
        "changed_files": paths,
        "fingerprint": fp_summary,
        "minimum_tier": minimum_tier,
        "requested_tier": requested,
        "selected_tier": selected,
        "gate_tier": selected,
        "route_id": route_info["route_id"],
        "route": {"tier": selected, **route_info},
        "reasons": sorted(set(reasons)),
        "fail_closed": False,
        "fallback": False,
        "eligible": True,
    }


def route_changed_files(
    changed_files: Iterable[str],
    *,
    fingerprint: Mapping[str, Any] | None = None,
    requested_tier: str | None = None,
) -> dict[str, Any]:
    return route(
        changed_files=changed_files,
        fingerprint=fingerprint,
        requested_tier=requested_tier,
    )


def route_fingerprint(
    fingerprint: Mapping[str, Any],
    *,
    changed_files: Iterable[str] | None = None,
    requested_tier: str | None = None,
) -> dict[str, Any]:
    return route(
        changed_files=changed_files,
        fingerprint=fingerprint,
        requested_tier=requested_tier,
    )


def select_route(
    changed_files: Iterable[str] | None = None,
    fingerprint: Mapping[str, Any] | None = None,
    *,
    requested_tier: str | None = None,
) -> dict[str, Any]:
    """Compatibility-friendly name for callers that use selector vocabulary."""
    return route(
        changed_files=changed_files,
        fingerprint=fingerprint,
        requested_tier=requested_tier,
    )


def matrix_contract() -> dict[str, Any]:
    """Return the immutable routing vocabulary for discovery and tests."""
    return {
        "schema": ROUTE_MATRIX_SCHEMA,
        "version": VERSION,
        "tiers": [
            {"tier": tier, **ROUTE_MATRIX[tier]}
            for tier in GATE_TIERS
        ],
        "unknown": {
            "route_id": UNKNOWN_ROUTE_ID,
            "fail_closed": True,
            "fallback": True,
        },
    }


__all__ = [
    "FINGERPRINT_SCHEMA",
    "GATE_TIERS",
    "ROUTE_MATRIX",
    "ROUTE_MATRIX_SCHEMA",
    "ROUTE_SCHEMA",
    "RouteContractError",
    "matrix_contract",
    "normalize_changed_files",
    "route",
    "route_changed_files",
    "route_fingerprint",
    "select_route",
]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--fingerprint-file")
    parser.add_argument("--requested-tier")
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args(argv)
    if args.matrix:
        payload = matrix_contract()
    else:
        loaded = None
        if args.fingerprint_file:
            with open(args.fingerprint_file, encoding="utf-8") as handle:
                loaded = json.load(handle)
        payload = route(
            changed_files=args.changed_file,
            fingerprint=loaded,
            requested_tier=args.requested_tier,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
