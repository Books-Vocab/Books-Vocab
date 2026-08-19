#!/usr/bin/env -S uv run --python 3.13
"""Build the mandatory project -> identity -> assignment -> skill -> domain route."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

import context_route  # noqa: E402
import skill_route  # noqa: E402


SCHEMA = "kg.agent_onboarding.v1"


class OnboardingError(ValueError):
    """The agent cannot safely enter the requested task route."""


def _root(root: Path | None) -> Path:
    return (root or OPS_DIR.parent).resolve()


def _identity_payload(definition: dict[str, Any], identity_id: str) -> dict[str, Any]:
    return {
        "id": identity_id,
        "label": definition["label"],
        "machine_role": definition["machine_role"],
        "owns": definition["owns"],
        "not_owns": definition["not_owns"],
    }


def build_onboarding(root: Path | None = None, *, identity: str, intent: str, entry: str) -> dict[str, Any]:
    root = _root(root)
    try:
        manifest = context_route.load_manifest(root)
        catalog = skill_route.load_catalog(root)
        identity_id = context_route.canonical_agent_identity(manifest, identity)
        canonical_intent = context_route.canonical_intent(intent)
    except (context_route.ContextRouteError, skill_route.SkillCatalogError) as exc:
        raise OnboardingError(str(exc)) from exc

    identity_def = manifest["identities"][identity_id]
    if canonical_intent not in identity_def["allowed_intents"]:
        raise OnboardingError(f"identity 不允許 intent: {identity_id} -> {canonical_intent}")
    if entry not in identity_def["entry_modes"]:
        raise OnboardingError(f"entry 不符合 identity: {identity_id} -> {entry}")

    intent_def = manifest["intents"][canonical_intent]
    skill_intent = identity_def["skill_routes"][canonical_intent][entry]
    try:
        skill_route_payload = skill_route.resolve_route(catalog, skill_intent)
    except skill_route.SkillCatalogError as exc:
        raise OnboardingError(f"skill route 無法解析: {skill_intent}: {exc}") from exc

    onboarding_source = manifest["onboarding"]["source"]
    role_def = manifest["roles"][identity_def["machine_role"]]
    required_external = identity_def["assignment_requirements"][entry]
    catalog_by_name = {skill["name"]: skill for skill in catalog["skills"]}
    skill_sources = [catalog_by_name[name]["path"] for name in skill_route_payload["skills"]]
    return {
        "schema": SCHEMA,
        "status": "ready",
        "project": {
            "source": onboarding_source,
            "overview": "KG product surfaces, GitHub-native delivery control plane, and local coordinator boundary",
        },
        "identity": _identity_payload(identity_def, identity_id),
        "task": {
            "requested_intent": intent,
            "intent": canonical_intent,
            "skill_intent": skill_intent,
            "entry": entry,
        },
        "assignment": {
            "required_external": required_external,
            "next_action": role_def["next_action"],
        },
        "skills": {
            "primary": skill_route_payload["primary"],
            "selected": skill_route_payload["skills"],
            "dependencies": skill_route_payload["dependencies"],
            "route_command": f"./ops/skill_route.py route --intent {skill_intent} --json",
        },
        "domain_sources": intent_def["sources"],
        "load_order": [
            {"phase": "project", "required": True, "sources": [onboarding_source]},
            {"phase": "identity", "required": True, "sources": role_def["sources"]},
            {"phase": "assignment", "required": True, "sources": [], "required_external": required_external},
            {"phase": "skill", "required": True, "sources": skill_sources},
            {"phase": "domain", "required": True, "sources": intent_def["sources"]},
        ],
        "next_action": role_def["next_action"],
        "authority": {"granted": False, "note": "onboarding 只建立上下文，不授予 GitHub、merge 或 production 權限"},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="build the mandatory KG agent onboarding route")
    parser.add_argument("--identity", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        payload = build_onboarding(args.root, identity=args.identity, intent=args.intent, entry=args.entry)
    except OnboardingError as exc:
        print(f"agent_onboard: ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
