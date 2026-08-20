#!/usr/bin/env -S uv run --python 3.13
"""Validate and resolve the bounded KG agent context plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

import skill_route  # noqa: E402


SCHEMA = "kg.context_plane.v4"
ROUTE_SCHEMA = "kg.context.route.v3"
IDENTITY_SCHEMA = "kg.context.identity.v3"
WORKER_DISPATCH_CHANNELS = {
    "im": {
        "discussion_with": "dispatching IM",
        "handback_policy": "same-dispatching-im",
    },
    "user": {
        "discussion_with": "User",
        "handback_policy": "specified-or-worker-selected-im",
    },
}
ROLES = {"manager", "contributor", "reviewer", "docs-steward", "release-operator"}
IDENTITIES = {"cm", "im", "worker", "issue-solver", "cr", "ds", "release-operator"}
ROUTE_CLASSES = {"coordination", "implementation", "implementation-ios", "review", "docs", "release"}
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
    "delivery-worktree": "delivery",
    "worktree-open": "delivery",
    "worktree-coordination": "delivery",
    "backend-routing": "backend",
    "backend": "backend",
    "ios-routing": "ios",
    "ios": "ios",
    "simulator-verification": "ios",
    "ui-test-evidence": "ios",
    "docs-registry": "docs",
    "docs": "docs",
    "docs-audit": "docs",
    "docs-impact": "docs",
    "skill-doc-sync": "docs",
    "read-only-audit": "docs",
    "release": "release",
    "release-command": "release",
    "version-release": "release",
    "app-store-release": "release",
    "review": "review",
    "code-review": "review",
}


class ContextRouteError(ValueError):
    """A missing or invalid context contract."""


def repo_root(root: Path | None = None) -> Path:
    return (root or OPS_DIR.parent).resolve()


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


def _require_nonempty_strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise ContextRouteError(f"{name} 必須是非空字串陣列")
    if len(value) != len(set(value)):
        raise ContextRouteError(f"{name} 不可重複")
    return value


def _require_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ContextRouteError(f"{name} 必須是字串陣列")
    if len(value) != len(set(value)):
        raise ContextRouteError(f"{name} 不可重複")
    return value


def _require_sources(sources: Any, name: str, root: Path) -> None:
    for source in _require_nonempty_strings(sources, f"{name}.sources"):
        if not (root / source).is_file():
            raise ContextRouteError(f"{name}.sources 不存在: {source}")


def _validate_worker_dispatch_channels(identity_id: str, handoff_contract: dict[str, Any]) -> None:
    if identity_id != "worker":
        return
    channels = _require_mapping(
        handoff_contract.get("dispatch_channels"),
        "identities.worker.handoff_contract.dispatch_channels",
    )
    if set(channels) != set(WORKER_DISPATCH_CHANNELS):
        raise ContextRouteError(
            "identities.worker.handoff_contract.dispatch_channels 必須剛好包含 im、user"
        )
    for channel, expected in WORKER_DISPATCH_CHANNELS.items():
        definition = _require_mapping(
            channels[channel],
            f"identities.worker.handoff_contract.dispatch_channels.{channel}",
        )
        if definition != expected:
            raise ContextRouteError(
                f"identities.worker.handoff_contract.dispatch_channels.{channel} "
                f"必須是 {expected}"
            )


def _validate_identity(
    identity_id: str,
    definition: dict[str, Any],
    intents: dict[str, Any],
    catalog: dict[str, Any],
    specialist_sources: dict[str, Any],
) -> None:
    required = {
        "label", "aliases", "machine_role", "allowed_intents", "entry_modes", "route_classes",
        "owns", "not_owns", "assignment_requirements", "skill_routes", "specialist_routes",
    }
    contract_fields = {"allowed_surfaces", "forbidden_surfaces", "handoff_contract"}
    present_contract_fields = set(definition) & contract_fields
    unknown_fields = set(definition) - required - contract_fields
    if unknown_fields or present_contract_fields not in (set(), contract_fields):
        expected = sorted(required | contract_fields)
        raise ContextRouteError(f"identities.{identity_id} 欄位必須是 {sorted(required)} 或完整責任契約欄位 {expected}")
    if present_contract_fields == contract_fields:
        allowed_surfaces = _require_nonempty_strings(
            definition["allowed_surfaces"], f"identities.{identity_id}.allowed_surfaces"
        )
        forbidden_surfaces = _require_nonempty_strings(
            definition["forbidden_surfaces"], f"identities.{identity_id}.forbidden_surfaces"
        )
        overlap = sorted(set(allowed_surfaces) & set(forbidden_surfaces))
        if overlap:
            raise ContextRouteError(f"identities.{identity_id}.allowed_surfaces/forbidden_surfaces 重疊: {overlap}")
    if "handoff_contract" in definition and not isinstance(definition["handoff_contract"], dict):
        raise ContextRouteError(f"identities.{identity_id}.handoff_contract 必須是 object")
    if "handoff_contract" in definition:
        _validate_worker_dispatch_channels(identity_id, definition["handoff_contract"])
    if not isinstance(definition["label"], str) or not definition["label"].strip():
        raise ContextRouteError(f"identities.{identity_id}.label 必須是非空字串")
    _require_nonempty_strings(definition["aliases"], f"identities.{identity_id}.aliases")
    if definition["machine_role"] not in ROLES:
        raise ContextRouteError(f"identities.{identity_id}.machine_role 未知: {definition['machine_role']}")
    allowed_intents = _require_nonempty_strings(definition["allowed_intents"], f"identities.{identity_id}.allowed_intents")
    if set(allowed_intents) - set(intents):
        raise ContextRouteError(f"identities.{identity_id}.allowed_intents 未知: {sorted(set(allowed_intents) - set(intents))}")
    entry_modes = _require_nonempty_strings(definition["entry_modes"], f"identities.{identity_id}.entry_modes")
    route_classes = _require_mapping(definition["route_classes"], f"identities.{identity_id}.route_classes")
    if set(route_classes) != set(allowed_intents):
        raise ContextRouteError(f"identities.{identity_id}.route_classes 必須覆蓋所有 allowed_intents")
    for route_intent, routes in route_classes.items():
        routes = _require_mapping(routes, f"identities.{identity_id}.route_classes.{route_intent}")
        if set(routes) != set(entry_modes):
            raise ContextRouteError(
                f"identities.{identity_id}.route_classes.{route_intent} 必須覆蓋所有 entry_modes"
            )
        if set(routes.values()) - ROUTE_CLASSES:
            raise ContextRouteError(f"identities.{identity_id}.route_classes.{route_intent} 有未知 class")
    if not isinstance(definition["owns"], str) or not definition["owns"].strip() or not isinstance(definition["not_owns"], str) or not definition["not_owns"].strip():
        raise ContextRouteError(f"identities.{identity_id}.owns/not_owns 必須是非空字串")
    requirements = _require_mapping(definition["assignment_requirements"], f"identities.{identity_id}.assignment_requirements")
    if set(requirements) != set(entry_modes):
        raise ContextRouteError(f"identities.{identity_id}.assignment_requirements 必須覆蓋所有 entry_modes")
    for entry, values in requirements.items():
        _require_nonempty_strings(values, f"identities.{identity_id}.assignment_requirements.{entry}")
    skill_routes = _require_mapping(definition["skill_routes"], f"identities.{identity_id}.skill_routes")
    if set(skill_routes) != set(allowed_intents):
        raise ContextRouteError(f"identities.{identity_id}.skill_routes 必須覆蓋所有 allowed_intents")
    for route_intent, routes in skill_routes.items():
        routes = _require_mapping(routes, f"identities.{identity_id}.skill_routes.{route_intent}")
        if set(routes) != set(entry_modes):
            raise ContextRouteError(f"identities.{identity_id}.skill_routes.{route_intent} 必須覆蓋所有 entry_modes")
        for entry, skill_intent in routes.items():
            if not isinstance(skill_intent, str) or not skill_intent.strip():
                raise ContextRouteError(f"identities.{identity_id}.skill_routes.{route_intent}.{entry} 必須是非空字串")
    specialist_routes = _require_mapping(definition["specialist_routes"], f"identities.{identity_id}.specialist_routes")
    if set(specialist_routes) != set(allowed_intents):
        raise ContextRouteError(f"identities.{identity_id}.specialist_routes 必須覆蓋所有 allowed_intents")
    for route_intent, routes in specialist_routes.items():
        routes = _require_mapping(routes, f"identities.{identity_id}.specialist_routes.{route_intent}")
        if set(routes) != set(entry_modes):
            raise ContextRouteError(
                f"identities.{identity_id}.specialist_routes.{route_intent} 必須覆蓋所有 entry_modes"
            )
        for entry, specialist_intents in routes.items():
            for specialist_intent in _require_string_list(
                specialist_intents,
                f"identities.{identity_id}.specialist_routes.{route_intent}.{entry}",
            ):
                try:
                    routed = skill_route.resolve_route(catalog, specialist_intent)
                except skill_route.SkillCatalogError as exc:
                    raise ContextRouteError(
                        f"identities.{identity_id}.specialist_routes.{route_intent}.{entry} 無法解析: {exc}"
                    ) from exc
                if routed["intent"] != specialist_intent:
                    raise ContextRouteError(
                        f"identity specialist route 未使用 canonical skill intent: {specialist_intent}"
                    )
                if specialist_intent not in specialist_sources:
                    raise ContextRouteError(f"specialist_sources 缺少: {specialist_intent}")


def validate_manifest(payload: dict[str, Any], root: Path | None = None) -> None:
    root = repo_root(root)
    expected_top_level = {
        "schema", "version", "registry", "onboarding", "route_policy", "specialist_sources",
        "identities", "roles", "intents",
    }
    if set(payload) != expected_top_level:
        raise ContextRouteError(f"manifest 欄位必須剛好是 {sorted(expected_top_level)}")
    if payload.get("schema") != SCHEMA or payload.get("version") != 4:
        raise ContextRouteError(f"manifest 必須是 {SCHEMA} version=4")
    onboarding = _require_mapping(payload.get("onboarding"), "onboarding")
    if onboarding.get("source") != "docs/reference/project_onboarding.md" or onboarding.get("required") is not True:
        raise ContextRouteError("onboarding 必須要求存在的 project onboarding source")
    onboarding_source = onboarding["source"]
    if not (root / onboarding_source).is_file():
        raise ContextRouteError(f"onboarding source 不存在: {onboarding_source}")
    registry = payload.get("registry")
    if not isinstance(registry, str) or not (root / registry).is_file():
        raise ContextRouteError("manifest.registry 必須指向存在的 registry")
    route_policy = _require_mapping(payload.get("route_policy"), "route_policy")
    if set(route_policy) != ROUTE_CLASSES or any(not isinstance(value, str) or not value.strip() for value in route_policy.values()):
        raise ContextRouteError(f"route_policy 必須剛好定義 {sorted(ROUTE_CLASSES)} 的 canonical skill intents")

    try:
        catalog = skill_route.load_catalog(root)
    except skill_route.SkillCatalogError as exc:
        raise ContextRouteError(f"skill catalog 無效: {exc}") from exc

    specialist_sources = _require_mapping(payload.get("specialist_sources"), "specialist_sources")
    for specialist_intent, sources in specialist_sources.items():
        if not isinstance(specialist_intent, str) or not specialist_intent.strip():
            raise ContextRouteError("specialist_sources key 必須是非空字串")
        try:
            routed = skill_route.resolve_route(catalog, specialist_intent)
        except skill_route.SkillCatalogError as exc:
            raise ContextRouteError(f"specialist_sources intent 無法解析: {specialist_intent}: {exc}") from exc
        if routed["intent"] != specialist_intent:
            raise ContextRouteError(f"specialist_sources 必須使用 canonical skill intent: {specialist_intent}")
        _require_sources(sources, f"specialist_sources.{specialist_intent}", root)

    intents = _require_mapping(payload.get("intents"), "intents")
    if not intents:
        raise ContextRouteError("intents 不可為空")
    for intent, definition in intents.items():
        definition = _require_mapping(definition, f"intents.{intent}")
        if set(definition) != {"skill", "skill_intent", "sources"}:
            raise ContextRouteError(f"intents.{intent} 欄位必須是 skill、skill_intent、sources")
        if not isinstance(definition["skill"], str) or not definition["skill"].strip() or not isinstance(definition["skill_intent"], str) or not definition["skill_intent"].strip():
            raise ContextRouteError(f"intents.{intent}.skill/skill_intent 必須是非空字串")
        _require_sources(definition["sources"], f"intents.{intent}", root)

    known_skills = {skill["name"] for skill in catalog["skills"]}
    for intent, definition in intents.items():
        if definition["skill"] not in known_skills:
            raise ContextRouteError(f"intents.{intent}.skill 不存在: {definition['skill']}")
        try:
            routed = skill_route.resolve_route(catalog, definition["skill_intent"])
        except skill_route.SkillCatalogError as exc:
            raise ContextRouteError(f"intents.{intent}.skill_intent 無法解析: {exc}") from exc
        if routed["primary"] != definition["skill"]:
            raise ContextRouteError(f"intents.{intent} skill/skill_intent primary 不一致")
    for route_class, skill_intent in route_policy.items():
        try:
            skill_route.resolve_route(catalog, skill_intent)
        except skill_route.SkillCatalogError as exc:
            raise ContextRouteError(f"route_policy.{route_class} 無法解析: {exc}") from exc

    identities = _require_mapping(payload.get("identities"), "identities")
    if set(identities) != IDENTITIES:
        raise ContextRouteError(f"identities 必須剛好是 {sorted(IDENTITIES)}")
    identity_names: dict[str, str] = {}
    for identity_id, definition in identities.items():
        definition = _require_mapping(definition, f"identities.{identity_id}")
        _validate_identity(identity_id, definition, intents, catalog, specialist_sources)
        for name in [identity_id, definition["label"], *definition["aliases"]]:
            normalized = _normalize(name)
            previous = identity_names.setdefault(normalized, identity_id)
            if previous != identity_id:
                raise ContextRouteError(f"identity alias 重複: {name} -> {previous}/{identity_id}")
        for route_intent, routes in definition["skill_routes"].items():
            for entry, skill_intent in routes.items():
                try:
                    routed = skill_route.resolve_route(catalog, skill_intent)
                except skill_route.SkillCatalogError as exc:
                    raise ContextRouteError(
                        f"identities.{identity_id}.skill_routes.{route_intent}.{entry} 無法解析: {exc}"
                    ) from exc
                if not routed["intent"] == skill_intent:
                    raise ContextRouteError(f"identity skill route 未使用 canonical skill intent: {skill_intent}")
                route_class = definition["route_classes"][route_intent][entry]
                if skill_intent != route_policy[route_class]:
                    raise ContextRouteError(
                        f"identity skill route 不符合 route_policy: {identity_id}.{route_intent}.{entry}"
                    )

    roles = _require_mapping(payload.get("roles"), "roles")
    if set(roles) != ROLES:
        raise ContextRouteError(f"roles 必須剛好是 {sorted(ROLES)}")
    for role, definition in roles.items():
        definition = _require_mapping(definition, f"roles.{role}")
        required = {"identity_ids", "sources", "next_action"}
        if set(definition) != required:
            raise ContextRouteError(f"roles.{role} 欄位必須是 identity_ids、sources、next_action")
        identity_ids = _require_nonempty_strings(definition["identity_ids"], f"roles.{role}.identity_ids")
        if set(identity_ids) - IDENTITIES:
            raise ContextRouteError(f"roles.{role}.identity_ids 未知: {sorted(set(identity_ids) - IDENTITIES)}")
        if {identity_id for identity_id, item in identities.items() if item["machine_role"] == role} != set(identity_ids):
            raise ContextRouteError(f"roles.{role}.identity_ids 與 identities.machine_role 不一致")
        _require_sources(definition["sources"], f"roles.{role}", root)
        if not isinstance(definition["next_action"], str) or not definition["next_action"].strip():
            raise ContextRouteError(f"roles.{role}.next_action 必須是非空字串")


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", "-").split())


def canonical_agent_identity(manifest: dict[str, Any], identity: str) -> str:
    candidate = _normalize(identity)
    for identity_id, definition in manifest["identities"].items():
        options = {_normalize(identity_id), _normalize(definition["label"]), *(_normalize(alias) for alias in definition["aliases"])}
        if candidate in options:
            return identity_id
    raise ContextRouteError(f"未知 canonical identity: {identity}")


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
    """Compatibility helper; machine role is routing context, not authority."""
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
    identity: str | None = None,
    entry: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root(root)
    validate_manifest(manifest, root)
    role = canonical_role(role)
    if work_mode not in (None, "none"):
        raise ContextRouteError("GitHub-native route 不接受 work_mode 覆寫")
    intent = canonical_intent(intent, surface, task)
    role_def = manifest["roles"][role]
    intent_def = manifest["intents"][intent]
    selected_identity: str | None = None
    if identity is not None:
        selected_identity = canonical_agent_identity(manifest, identity)
        if selected_identity not in role_def["identity_ids"]:
            raise ContextRouteError(f"identity 不屬於 role: {selected_identity} -> {role}")

    candidates: list[tuple[str, str, str]] = []
    identity_ids = [selected_identity] if selected_identity else role_def["identity_ids"]
    for identity_id in identity_ids:
        identity_def = manifest["identities"][identity_id]
        if intent not in identity_def["allowed_intents"]:
            continue
        routes = identity_def["skill_routes"][intent]
        entries = [entry] if entry is not None else list(routes)
        for candidate_entry in entries:
            if candidate_entry not in routes:
                raise ContextRouteError(f"entry 不符合 identity/intent: {identity_id}/{intent} -> {candidate_entry}")
            candidates.append((identity_id, candidate_entry, routes[candidate_entry]))
    if not candidates:
        raise ContextRouteError(f"role 不允許 intent: {role} -> {intent}")
    skill_intents = {candidate[2] for candidate in candidates}
    if len(skill_intents) != 1:
        choices = ", ".join(f"{identity_id}/{candidate_entry}={skill_intent}" for identity_id, candidate_entry, skill_intent in candidates)
        raise ContextRouteError(
            f"role/intent route 不唯一，請提供 --identity 與 --entry: {role}/{intent} ({choices})"
        )
    selected_skill_intent = next(iter(skill_intents))
    catalog = skill_route.load_catalog(root)
    skill_route_payload = skill_route.resolve_route(catalog, selected_skill_intent)
    expected_skill = skill_route_payload["primary"]
    if skill is not None and skill != expected_skill:
        raise ContextRouteError(f"skill 與 intent route 不一致: expected={expected_skill} actual={skill}")
    catalog_by_name = {item["name"]: item for item in catalog["skills"]}
    skill_sources = [catalog_by_name[name]["path"] for name in skill_route_payload["skills"]]
    sources: list[str] = [manifest["onboarding"]["source"]]
    for source in [*role_def["sources"], *intent_def["sources"]]:
        if source not in sources:
            sources.append(source)
    return {
        "schema": ROUTE_SCHEMA,
        "status": "confirmed",
        "role": role,
        "identity_ids": role_def["identity_ids"],
        "work_mode": "none",
        "intent": intent,
        "skill": expected_skill,
        "skill_intent": selected_skill_intent,
        "route_selection": {
            "identity": selected_identity,
            "entry": entry,
            "candidates": [
                {"identity": identity_id, "entry": candidate_entry, "skill_intent": candidate_skill_intent}
                for identity_id, candidate_entry, candidate_skill_intent in candidates
            ],
        },
        "skill_route": {
            "primary": skill_route_payload["primary"],
            "selected": skill_route_payload["skills"],
            "dependencies": skill_route_payload["dependencies"],
        },
        "onboarding": {"required": True, "source": manifest["onboarding"]["source"]},
        "load_order": [
            {"phase": "project", "required": True, "sources": [manifest["onboarding"]["source"]]},
            {"phase": "identity", "required": True, "sources": role_def["sources"]},
            {"phase": "skill", "required": True, "sources": skill_sources},
            {"phase": "domain", "required": True, "sources": intent_def["sources"]},
        ],
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    identify = subparsers.add_parser("identify", help="maintainer diagnostic: inspect a compatibility role")
    identify.add_argument("--diagnostic", action="store_true", help="explicitly allow maintainer-only diagnostics")
    identify.add_argument("--role", required=True)
    identify.add_argument("--work-mode")
    identify.add_argument("--root", type=Path)
    identify.add_argument("--json", action="store_true")

    validate = subparsers.add_parser("validate", help="validate the context manifest")
    validate.add_argument("--root", type=Path)
    validate.add_argument("--json", action="store_true")

    for name in ("route", "render"):
        command = subparsers.add_parser(name, help="maintainer diagnostic: resolve or render bounded sources")
        command.add_argument("--diagnostic", action="store_true", help="explicitly allow maintainer-only diagnostics")
        command.add_argument("--role", required=True)
        command.add_argument("--work-mode")
        command.add_argument("--intent")
        command.add_argument("--surface")
        command.add_argument("--task")
        command.add_argument("--skill")
        command.add_argument("--identity")
        command.add_argument("--entry")
        command.add_argument("--root", type=Path)
        command.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command != "validate" and not args.diagnostic:
        print(
            "context_route: ERROR agent-facing loader is ./ops/agent_onboard.py; "
            "use --diagnostic only for maintainer inspection",
            file=sys.stderr,
        )
        return 2
    try:
        root = getattr(args, "root", None)
        manifest = load_manifest(root)
        if args.command == "validate":
            return _emit({"schema": SCHEMA, "status": "valid", "roles": sorted(ROLES), "identities": sorted(IDENTITIES), "intents": sorted(manifest["intents"])}, args.json)
        if args.command == "identify":
            role = canonical_role(args.role)
            definition = manifest["roles"][role]
            if args.work_mode not in (None, "none"):
                raise ContextRouteError("GitHub-native identity 不接受 work_mode 覆寫")
            payload = {
                "schema": IDENTITY_SCHEMA,
                "status": "confirmed",
                "role": role,
                "identity_ids": definition["identity_ids"],
                "work_mode": "none",
                "onboarding": manifest["onboarding"],
                "sources": [manifest["onboarding"]["source"], *definition["sources"]],
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
            identity=args.identity,
            entry=args.entry,
            root=root,
        )
        payload["phase"] = args.command
        return _emit(payload, args.json)
    except (ContextRouteError, skill_route.SkillCatalogError) as exc:
        print(f"context_route: ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
