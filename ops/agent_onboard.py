#!/usr/bin/env -S uv run --python 3.13
"""Build the mandatory project -> identity -> assignment -> skill -> domain route."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

import context_route  # noqa: E402
import skill_route  # noqa: E402


SCHEMA = "kg.agent_onboarding.v2"


class OnboardingError(ValueError):
    """The agent cannot safely enter the requested task route."""


def _evidence_value_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None


def _root(root: Path | None) -> Path:
    return (root or OPS_DIR.parent).resolve()


def _identity_payload(definition: dict[str, Any], identity_id: str) -> dict[str, Any]:
    payload = {
        "id": identity_id,
        "label": definition["label"],
        "owns": definition["owns"],
        "not_owns": definition["not_owns"],
    }
    for key in ("allowed_surfaces", "forbidden_surfaces", "handoff_contract"):
        if key in definition:
            payload[key] = definition[key]
    return payload


def _is_im_target(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"im(?:[-_ ].+)?", value.strip(), re.IGNORECASE))


def _resolve_worker_dispatch(identity_id: str, entry: str, evidence: dict[str, Any]) -> dict[str, Any] | None:
    if identity_id != "worker" or entry != "direct-assignment":
        return None

    channel_value = evidence.get("dispatch_channel")
    if not isinstance(channel_value, str) or channel_value.strip().casefold() not in {"im", "user"}:
        raise OnboardingError("worker direct assignment 的 dispatch_channel 必須是 im 或 user")
    channel = channel_value.strip().casefold()
    requested_target = evidence.get("handback_target")

    if channel == "im":
        dispatch_owner = evidence.get("dispatch_owner")
        if not _is_im_target(dispatch_owner):
            raise OnboardingError("IM dispatch 必須提供有效的 dispatch_owner")
        if requested_target is not None:
            if not _is_im_target(requested_target):
                raise OnboardingError("handback_target 必須是 IM")
            if requested_target.strip().casefold() != dispatch_owner.strip().casefold():
                raise OnboardingError("IM dispatch 的 handback_target 必須等於 same dispatching IM")
        requested_im_target = requested_target.strip() if isinstance(requested_target, str) else None
        return {
            "channel": channel,
            "discussion_with": dispatch_owner.strip(),
            "handback": {
                "policy": context_route.WORKER_DISPATCH_CHANNELS[channel]["handback_policy"],
                "requested_target": requested_im_target,
                "resolved_target": dispatch_owner.strip(),
                "selection_required": False,
            },
        }

    if requested_target is not None and not _is_im_target(requested_target):
        raise OnboardingError("handback_target 必須是 IM")
    target = requested_target.strip() if isinstance(requested_target, str) else None
    return {
        "channel": channel,
        "discussion_with": context_route.WORKER_DISPATCH_CHANNELS[channel]["discussion_with"],
        "handback": {
            "policy": context_route.WORKER_DISPATCH_CHANNELS[channel]["handback_policy"],
            "requested_target": target,
            "resolved_target": target,
            "selection_required": target is None,
        },
    }


def build_onboarding(
    root: Path | None = None,
    *,
    identity: str,
    intent: str,
    entry: str,
    evidence: dict[str, Any] | None = None,
    specialist_intent: str | None = None,
) -> dict[str, Any]:
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
    allowed_specialists = identity_def["specialist_routes"][canonical_intent][entry]
    specialist_route_payload: dict[str, Any] | None = None
    canonical_specialist_intent: str | None = None
    domain_sources: list[str] = []
    for source in intent_def["sources"]:
        if source not in domain_sources:
            domain_sources.append(source)
    onboarding_source = manifest["onboarding"]["source"]
    role_def = manifest["roles"][identity_def["machine_role"]]
    required_external = identity_def["assignment_requirements"][entry]
    evidence = {} if evidence is None else evidence
    if not isinstance(evidence, dict):
        raise OnboardingError("assignment evidence 必須是 object")
    missing_external = [
        requirement for requirement in required_external
        if not _evidence_value_present(evidence.get(requirement))
    ]
    dispatch_resolution = None
    if not missing_external:
        dispatch_resolution = _resolve_worker_dispatch(identity_id, entry, evidence)
    base_load_order = [
        {"phase": "project", "required": True, "sources": [onboarding_source]},
        {"phase": "identity", "required": True, "sources": role_def["sources"]},
        {"phase": "assignment", "required": True, "sources": [], "required_external": required_external},
    ]
    base_payload = {
        "schema": SCHEMA,
        "project": {
            "source": onboarding_source,
            "overview": "KG product surfaces, GitHub-native delivery control plane, and local coordinator boundary",
        },
        "identity": _identity_payload(identity_def, identity_id),
        "task": {
            "requested_intent": intent,
            "intent": canonical_intent,
            "skill_intent": skill_intent,
            "effective_skill_intent": canonical_specialist_intent or skill_intent,
            "specialist_intent": canonical_specialist_intent,
            "entry": entry,
        },
        "assignment": {
            "required_external": required_external,
            "provided": sorted(requirement for requirement in required_external if requirement not in missing_external),
            "missing": missing_external,
            "evidence": evidence,
            "evidence_digest": hashlib.sha256(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "next_action": role_def["next_action"],
        },
        "load_order": base_load_order,
        "authority": {"granted": False, "note": "onboarding 只建立上下文，不授予 GitHub、merge 或 production 權限"},
    }
    if dispatch_resolution is not None:
        base_payload["assignment"]["dispatch"] = dispatch_resolution
    if missing_external:
        return {
            **base_payload,
            "status": "awaiting-assignment",
            "blocked_at": "assignment",
            "next_action": "complete the required assignment evidence before loading skills or domain docs",
        }

    # Assignment is the hard boundary. A cold agent with no assignment must
    # stop here even if it also supplied an invalid specialist string.
    if specialist_intent is not None:
        try:
            specialist_route_payload = skill_route.resolve_route(catalog, specialist_intent)
        except skill_route.SkillCatalogError as exc:
            raise OnboardingError(f"specialist skill route 無法解析: {specialist_intent}: {exc}") from exc
        canonical_specialist_intent = specialist_route_payload["intent"]
        if canonical_specialist_intent not in allowed_specialists:
            allowed = ", ".join(allowed_specialists) or "(none)"
            raise OnboardingError(
                f"identity/intent/entry 不允許 specialist: {identity_id}/{canonical_intent}/{entry} "
                f"-> {canonical_specialist_intent}; allowed={allowed}"
            )
        for source in manifest["specialist_sources"].get(canonical_specialist_intent, []):
            if source not in domain_sources:
                domain_sources.append(source)

    try:
        control_route_payload = skill_route.resolve_route(catalog, skill_intent)
    except skill_route.SkillCatalogError as exc:
        raise OnboardingError(f"skill route 無法解析: {skill_intent}: {exc}") from exc
    effective_route_payload = specialist_route_payload or control_route_payload

    catalog_by_name = {skill["name"]: skill for skill in catalog["skills"]}
    skill_sources = [catalog_by_name[name]["path"] for name in effective_route_payload["skills"]]
    skills_payload: dict[str, Any] = {
        "primary": effective_route_payload["primary"],
        "selected": effective_route_payload["skills"],
        "dependencies": effective_route_payload["dependencies"],
    }
    if specialist_route_payload is not None:
        skills_payload["control_primary"] = control_route_payload["primary"]
        skills_payload["specialist"] = {
            "intent": specialist_route_payload["intent"],
            "primary": specialist_route_payload["primary"],
            "selected": specialist_route_payload["skills"],
        }
    ready_assignment = {
        "required_external": required_external,
        "provided": sorted(required_external),
        "missing": [],
        "evidence": evidence,
        "evidence_digest": base_payload["assignment"]["evidence_digest"],
        "next_action": role_def["next_action"],
    }
    if dispatch_resolution is not None:
        ready_assignment["dispatch"] = dispatch_resolution
    return {
        **base_payload,
        "task": {
            **base_payload["task"],
            "effective_skill_intent": canonical_specialist_intent or skill_intent,
            "specialist_intent": canonical_specialist_intent,
        },
        "status": "ready",
        "assignment": ready_assignment,
        "skills": skills_payload,
        "domain_sources": domain_sources,
        "load_order": [
            *base_load_order,
            {"phase": "skill", "required": True, "sources": skill_sources},
            {"phase": "domain", "required": True, "sources": domain_sources},
        ],
        "next_action": role_def["next_action"],
        "authority": {"granted": False, "note": "onboarding 只建立上下文，不授予 GitHub、merge 或 production 權限"},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="build the mandatory KG agent onboarding route")
    parser.add_argument("--identity", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--specialist-intent", help="optional canonical specialist route allowed by identity/intent/entry")
    parser.add_argument("--evidence", help="JSON object containing every required assignment evidence field")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        evidence = None
        if args.evidence:
            parsed = json.loads(args.evidence)
            if not isinstance(parsed, dict):
                raise OnboardingError("--evidence 必須是 JSON object")
            evidence = parsed
        payload = build_onboarding(
            args.root,
            identity=args.identity,
            intent=args.intent,
            entry=args.entry,
            evidence=evidence,
            specialist_intent=args.specialist_intent,
        )
    except OnboardingError as exc:
        print(f"agent_onboard: ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if payload["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
