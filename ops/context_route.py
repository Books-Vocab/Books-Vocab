#!/usr/bin/env -S uv run --python 3.13
"""Bounded context routing for the GitHub-native KG workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA = "kg.context_plane.v2"
ROLES = {"manager", "contributor", "reviewer", "docs-steward", "release-operator"}
ROLE_ALIASES = {
    "Manager": "manager",
    "CM": "manager",
    "cm": "manager",
    "Codebase Manager": "manager",
    "codebase-manager": "manager",
    "IM": "manager",
    "im": "manager",
    "Issues Manager": "manager",
    "issues-manager": "manager",
    "delivery-manager": "manager",
    "Worker": "contributor",
    "worker": "contributor",
    "Issue Solver": "contributor",
    "issue-solver": "contributor",
    "Docs Steward": "docs-steward",
    "DS": "docs-steward",
    "ds": "docs-steward",
    "Review service": "reviewer",
    "review-service": "reviewer",
    "CR": "reviewer",
    "cr": "reviewer",
    "Code Reviewer": "reviewer",
    "code-reviewer": "reviewer",
    "release": "release-operator",
}
INTENT_ALIASES = {
    "delivery": "delivery",
    "worktree": "delivery",
    "backend-routing": "backend",
    "ios-routing": "ios",
    "docs-registry": "docs",
    "release": "release",
    "review": "review",
}


class ContextRouteError(ValueError):
    """A missing or invalid context contract."""


def repo_root(root: Path | None = None) -> Path:
    return (root or Path(__file__).resolve().parents[1]).resolve()


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    root = repo_root(root)
    path = root / "ops" / "context_plane.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextRouteError(f"context manifest 無法讀取: {path}: {exc}") from exc
    validate_manifest(payload, root)
    return payload


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextRouteError(f"{name} 必須是 object")
    return value


def _require_sources(sources: Any, name: str, root: Path) -> None:
    if not isinstance(sources, list) or not sources or not all(isinstance(item, str) for item in sources):
        raise ContextRouteError(f"{name}.sources 必須是非空字串陣列")
    for source in sources:
        if not (root / source).exists():
            raise ContextRouteError(f"{name}.sources 不存在: {source}")


def validate_manifest(payload: dict[str, Any], root: Path | None = None) -> None:
    root = repo_root(root)
    if payload.get("schema") != SCHEMA or payload.get("version") != 2:
        raise ContextRouteError(f"manifest 必須是 {SCHEMA} version=2")
    registry = payload.get("registry")
    if not isinstance(registry, str) or not (root / registry).is_file():
        raise ContextRouteError("manifest.registry 必須指向存在的 registry")
    roles = _require_mapping(payload.get("roles"), "roles")
    if set(roles) != ROLES:
        raise ContextRouteError(f"roles 必須剛好是 {sorted(ROLES)}")
    for role, definition in roles.items():
        definition = _require_mapping(definition, f"roles.{role}")
        _require_sources(definition.get("sources"), f"roles.{role}", root)
        if not isinstance(definition.get("next_action"), str) or not definition["next_action"].strip():
            raise ContextRouteError(f"roles.{role}.next_action 必須是非空字串")
    intents = _require_mapping(payload.get("intents"), "intents")
    if not intents:
        raise ContextRouteError("intents 不可為空")
    for intent, definition in intents.items():
        definition = _require_mapping(definition, f"intents.{intent}")
        if not isinstance(definition.get("skill"), str) or not definition["skill"].strip():
            raise ContextRouteError(f"intents.{intent}.skill 必須是非空字串")
        _require_sources(definition.get("sources"), f"intents.{intent}", root)


def canonical_role(role: str) -> str:
    canonical = ROLE_ALIASES.get(role, role)
    if canonical not in ROLES:
        raise ContextRouteError(f"未知 role: {role}")
    return canonical


def canonical_intent(intent: str | None, surface: str | None = None, task: str | None = None) -> str:
    candidate = intent or surface or task or "delivery"
    candidate = INTENT_ALIASES.get(candidate, candidate)
    if candidate not in {"delivery", "review", "docs", "release", "backend", "ios"}:
        raise ContextRouteError(f"未知 intent: {candidate}")
    return candidate


def normalize_role_identity(role: str, work_mode: str | None = None) -> tuple[str, str, str]:
    """Compatibility helper for callers that still ask for a role triple."""
    canonical = canonical_role(role)
    if work_mode not in (None, "none"):
        raise ContextRouteError("GitHub-native route 不需要額外 work mode")
    kind = "service" if canonical in {"reviewer", "docs-steward"} else canonical
    return canonical, kind, "none"


def canonical_identity(role: str, work_mode: str | None = None) -> str:
    return normalize_role_identity(role, work_mode)[0]


def resolve_route(
    manifest: dict[str, Any],
    role: str = "manager",
    surface: str | None = None,
    task: str | None = None,
    *,
    work_mode: str | None = None,
    skill: str | None = None,
    intent: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root(root)
    validate_manifest(manifest, root)
    role = canonical_role(role)
    intent = canonical_intent(intent, surface, task)
    role_def = manifest["roles"][role]
    intent_def = manifest["intents"][intent]
    sources: list[str] = []
    for source in [*role_def["sources"], *intent_def["sources"]]:
        if source not in sources:
            sources.append(source)
    return {
        "schema": "kg.context.route.v2",
        "status": "confirmed",
        "role": role,
        "work_mode": "none",
        "intent": intent,
        "skill": skill or intent_def["skill"],
        "sources": sources,
        "next_action": role_def["next_action"],
        "authority": {"granted": False, "note": "context route 是導航，不是 GitHub 或 production 授權"},
    }


def _emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{payload.get('status', 'ok')}: role={payload.get('role', '-')} intent={payload.get('intent', '-')} skill={payload.get('skill', '-')}")
        for source in payload.get("sources", []):
            print(f"  source: {source}")
        if payload.get("next_action"):
            print(f"  next: {payload['next_action']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="resolve bounded GitHub-native KG context")
    sub = parser.add_subparsers(dest="command", required=True)

    identify = sub.add_parser("identify", help="confirm a context role without side effects")
    identify.add_argument("--role", required=True)
    identify.add_argument("--work-mode")
    identify.add_argument("--json", action="store_true")

    validate = sub.add_parser("validate", help="validate the context manifest")
    validate.add_argument("--json", action="store_true")

    for name in ("route", "render"):
        command = sub.add_parser(name, help="resolve or render bounded sources")
        command.add_argument("--role", required=True)
        command.add_argument("--work-mode")
        command.add_argument("--intent")
        command.add_argument("--surface")
        command.add_argument("--task")
        command.add_argument("--skill")
        command.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest()
        if args.command == "validate":
            return _emit({"schema": SCHEMA, "status": "valid", "roles": sorted(ROLES), "intents": sorted(manifest["intents"])}, args.json)
        if args.command == "identify":
            role = canonical_role(args.role)
            definition = manifest["roles"][role]
            payload = {
                "schema": "kg.context.identity.v2",
                "status": "confirmed",
                "role": role,
                "work_mode": "none",
                "sources": definition["sources"],
                "next_action": definition["next_action"],
                "authority": {"granted": False, "note": "identity confirmation is not mutation authorization"},
            }
            return _emit(payload, args.json)
        payload = resolve_route(
            manifest,
            args.role,
            args.surface,
            args.task,
            work_mode=args.work_mode,
            skill=args.skill,
            intent=args.intent,
        )
        payload["phase"] = args.command
        return _emit(payload, args.json)
    except ContextRouteError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
