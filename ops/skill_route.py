#!/usr/bin/env -S uv run --python 3.13
"""Validate and resolve the KG skill routing catalog.

Natural-language descriptions remain human guidance. This command consumes an
explicit intent and returns one primary skill plus typed dependencies; it never
executes a skill or treats a skill route as an authorization grant.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA = "kg.skill_catalog.v2"
PHASES = {"bootstrap", "context", "primary", "secondary", "closure"}
KINDS = {"bootstrap", "context", "specialist", "delivery", "closure"}


class SkillCatalogError(ValueError):
    pass


def root_dir(root: Path | None = None) -> Path:
    return root.resolve() if root else Path(__file__).resolve().parents[1]


def catalog_path(root: Path | None = None) -> Path:
    return root_dir(root) / ".claude/skills/catalog.json"


def load_catalog(root: Path | None = None) -> dict[str, Any]:
    root = root_dir(root)
    path = catalog_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SkillCatalogError(f"catalog 不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SkillCatalogError(f"catalog JSON 無效: line={exc.lineno} col={exc.colno}") from exc
    validate_catalog(payload, root)
    return payload


def _frontmatter_name(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillCatalogError(f"skill 缺 frontmatter: {path}")
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    raise SkillCatalogError(f"skill frontmatter 缺 name: {path}")


def _require(value: Any, field: str, context: str) -> Any:
    if value is None:
        raise SkillCatalogError(f"{context} 缺少欄位: {field}")
    return value


def validate_catalog(payload: dict[str, Any], root: Path) -> None:
    expected_top_level = {"schema", "version", "bootstrap", "context", "intent_aliases", "skills", "fixtures"}
    if set(payload) != expected_top_level:
        raise SkillCatalogError(f"catalog 欄位必須剛好是 {sorted(expected_top_level)}")
    if payload.get("schema") != SCHEMA or payload.get("version") != 2:
        raise SkillCatalogError(f"schema 必須是 {SCHEMA} version=2")
    skills = _require(payload.get("skills"), "skills", "catalog")
    if not isinstance(skills, list) or not skills:
        raise SkillCatalogError("skills 必須是非空陣列")
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, list) or not bootstrap or len(bootstrap) != len(set(bootstrap)) or not all(isinstance(item, str) and item for item in bootstrap):
        raise SkillCatalogError("bootstrap 必須是非空且不重複的字串陣列")
    context_names = payload.get("context")
    if not isinstance(context_names, list) or not context_names or len(context_names) != len(set(context_names)) or not all(isinstance(item, str) and item for item in context_names):
        raise SkillCatalogError("context 必須是非空且不重複的字串陣列")

    actual_paths = sorted(root.glob(".claude/skills/*/SKILL.md"))
    actual_names = {path.parent.name for path in actual_paths}
    names: set[str] = set()
    allowed_fields = {"name", "path", "kind", "phase", "priority", "intents", "requires", "optional", "forbidden", "closure"}
    for index, skill in enumerate(skills):
        context = f"skills[{index}]"
        if not isinstance(skill, dict):
            raise SkillCatalogError(f"{context} 必須是 object")
        unknown = sorted(set(skill) - allowed_fields)
        if unknown:
            raise SkillCatalogError(f"{context} 未知欄位: {', '.join(unknown)}")
        name = _require(skill.get("name"), "name", context)
        if not isinstance(name, str) or name in names or name not in actual_names:
            raise SkillCatalogError(f"{context}.name 非唯一或不在實體 skill: {name}")
        names.add(name)
        rel_path = _require(skill.get("path"), "path", context)
        path = root / rel_path
        if not path.is_file() or path.parent.name != name:
            raise SkillCatalogError(f"{context}.path 與 skill 不一致: {rel_path}")
        if _frontmatter_name(path) != name:
            raise SkillCatalogError(f"{context}.frontmatter.name 不一致: {name}")
        if skill.get("kind") not in KINDS or skill.get("phase") not in PHASES:
            raise SkillCatalogError(f"{context} kind/phase 無效")
        if not isinstance(skill.get("priority"), int) or skill["priority"] < 0:
            raise SkillCatalogError(f"{context}.priority 必須是非負整數")
        if not isinstance(skill.get("intents"), list) or not all(isinstance(item, str) and item for item in skill["intents"]):
            raise SkillCatalogError(f"{context}.intents 必須是非空字串陣列")
        for relation in ("requires", "optional", "forbidden", "closure"):
            values = skill.get(relation)
            if not isinstance(values, list) or len(values) != len(set(values)) or not all(isinstance(item, str) for item in values):
                raise SkillCatalogError(f"{context}.{relation} 必須是無重複字串陣列")

    missing = sorted(actual_names - names)
    phantom = sorted(names - actual_names)
    if missing or phantom:
        raise SkillCatalogError(f"skill parity 失敗 missing={missing} phantom={phantom}")

    known = names
    unknown_bootstrap = sorted(set(bootstrap) - known)
    if unknown_bootstrap:
        raise SkillCatalogError(f"bootstrap 引用未知 skill: {', '.join(unknown_bootstrap)}")
    for name in bootstrap:
        skill = next(item for item in skills if item["name"] == name)
        if skill["phase"] != "bootstrap" or skill["kind"] != "bootstrap":
            raise SkillCatalogError(f"bootstrap skill 必須是 bootstrap phase/kind: {name}")
    unknown_context = sorted(set(context_names) - known)
    if unknown_context:
        raise SkillCatalogError(f"context 引用未知 skill: {', '.join(unknown_context)}")
    for name in context_names:
        skill = next(item for item in skills if item["name"] == name)
        if skill["phase"] != "context" or skill["kind"] != "context":
            raise SkillCatalogError(f"context skill 必須是 context phase/kind: {name}")
    by_intent: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        for relation in ("requires", "optional", "forbidden", "closure"):
            unknown = sorted(set(skill[relation]) - known)
            if unknown:
                raise SkillCatalogError(f"{skill['name']}.{relation} 引用未知 skill: {', '.join(unknown)}")
        if skill["name"] in skill["requires"]:
            raise SkillCatalogError(f"{skill['name']} 不可 self-dependency")
        if skill["phase"] == "primary":
            for intent in skill["intents"]:
                by_intent.setdefault(intent, []).append(skill)
    overlaps = {intent: [item["name"] for item in candidates] for intent, candidates in by_intent.items() if len(candidates) > 1}
    if overlaps:
        raise SkillCatalogError(f"primary intent overlap: {overlaps}")
    _validate_dependency_cycles(skills)

    aliases = payload["intent_aliases"]
    if not isinstance(aliases, dict) or any(not isinstance(alias, str) or not alias for alias in aliases) or any(not isinstance(target, str) or not target for target in aliases.values()):
        raise SkillCatalogError("intent_aliases 必須是非空字串到非空字串的 mapping")
    primary_intents = set(by_intent)
    for alias, target in aliases.items():
        if alias in primary_intents:
            raise SkillCatalogError(f"intent alias 不可覆蓋 primary intent: {alias}")
        if target not in primary_intents:
            raise SkillCatalogError(f"intent alias target 不存在: {alias} -> {target}")

    fixtures = _require(payload.get("fixtures"), "fixtures", "catalog")
    if not isinstance(fixtures, list) or not fixtures:
        raise SkillCatalogError("fixtures 必須是非空陣列")
    fixture_ids: set[str] = set()
    for index, fixture in enumerate(fixtures):
        context = f"fixtures[{index}]"
        if not isinstance(fixture, dict):
            raise SkillCatalogError(f"{context} 必須是 object")
        unknown = sorted(set(fixture) - {"id", "intent", "primary", "required_secondary", "optional_secondary", "forbidden"})
        if unknown:
            raise SkillCatalogError(f"{context} 未知欄位: {', '.join(unknown)}")
        if fixture.get("id") in fixture_ids:
            raise SkillCatalogError(f"{context}.id 重複")
        fixture_ids.add(fixture.get("id"))
        for field in ("id", "intent", "primary"):
            if not isinstance(fixture.get(field), str) or not fixture[field]:
                raise SkillCatalogError(f"{context}.{field} 必須是非空字串")
        for field in ("required_secondary", "optional_secondary", "forbidden"):
            if not isinstance(fixture.get(field, []), list) or not all(isinstance(item, str) for item in fixture.get(field, [])):
                raise SkillCatalogError(f"{context}.{field} 必須是字串陣列")
        result = resolve_route(payload, fixture.get("intent"), include_optional=True)
        if result["primary"] != fixture.get("primary"):
            raise SkillCatalogError(f"{context} primary 不符: expected={fixture.get('primary')} actual={result['primary']}")
        required_result = resolve_route(payload, fixture.get("intent"), include_optional=False)
        selected = set(result["skills"])
        required_secondary = set(required_result["dependencies"]["required"])
        declared_required = set(fixture.get("required_secondary", []))
        if declared_required != required_secondary:
            raise SkillCatalogError(f"{context}.required_secondary 不完整或不正確: expected={sorted(required_secondary)} actual={sorted(declared_required)}")
        for field in ("required_secondary", "optional_secondary"):
            if not set(fixture.get(field, [])).issubset(selected):
                raise SkillCatalogError(f"{context}.{field} 未被 route 選入")
        if selected.intersection(fixture.get("forbidden", [])):
            raise SkillCatalogError(f"{context} 載入 forbidden skill")


def _validate_dependency_cycles(skills: list[dict[str, Any]]) -> None:
    graph = {skill["name"]: set(skill["requires"]) for skill in skills}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise SkillCatalogError(f"required dependency cycle: {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)


def resolve_route(payload: dict[str, Any], intent: str, include_optional: bool = False, include_closure: bool = False) -> dict[str, Any]:
    requested_intent = intent
    intent = payload.get("intent_aliases", {}).get(intent, intent)
    skills = {skill["name"]: skill for skill in payload["skills"]}
    candidates = [skill for skill in payload["skills"] if intent in skill["intents"] and skill["phase"] == "primary"]
    if len(candidates) != 1:
        raise SkillCatalogError(f"intent 必須唯一對應 primary: {intent}")
    primary = candidates[0]
    selected: list[str] = []

    def add(name: str) -> None:
        if name not in selected:
            for dependency in skills[name]["requires"]:
                add(dependency)
            selected.append(name)

    for name in payload["bootstrap"]:
        add(name)
    for name in payload.get("context", []):
        add(name)
    add(primary["name"])
    required_selected = list(selected)
    optional_added: list[str] = []
    if include_optional:
        for name in primary["optional"]:
            before = set(selected)
            add(name)
            optional_added.extend(item for item in selected if item not in before)
    closure_added: list[str] = []
    if include_closure:
        for skill in payload["skills"]:
            if skill["phase"] == "closure":
                before = set(selected)
                add(skill["name"])
                closure_added.extend(item for item in selected if item not in before)
    forbidden = set().union(*(set(skills[name]["forbidden"]) for name in selected))
    if forbidden.intersection(selected):
        raise SkillCatalogError(f"route 載入 forbidden skill: {sorted(forbidden.intersection(selected))}")
    bootstrap_set = set(payload["bootstrap"])
    required_secondary = [name for name in required_selected if name not in bootstrap_set and name != primary["name"]]
    return {
        "schema": "kg.skill_route.v1",
        "requested_intent": requested_intent,
        "intent": intent,
        "primary": primary["name"],
        "skills": selected,
        "dependencies": {
            "required": required_secondary,
            "optional": optional_added,
            "closure": closure_added,
        },
        "authorization": {"granted": False, "note": "skill route 不是 capability 或 production 授權"},
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="validate and resolve KG skill routes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "list"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--root", type=Path)
        sub.add_argument("--json", action="store_true")
    route = subparsers.add_parser("route")
    route.add_argument("--intent", required=True)
    route.add_argument("--include-optional", action="store_true")
    route.add_argument("--include-closure", action="store_true")
    route.add_argument("--root", type=Path)
    route.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        payload = load_catalog(getattr(args, "root", None))
        if args.command == "validate":
            result = {"schema": SCHEMA, "status": "ok", "skills": len(payload["skills"]), "fixtures": len(payload["fixtures"])}
        elif args.command == "list":
            result = payload
        else:
            result = resolve_route(payload, args.intent, args.include_optional, args.include_closure)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else json.dumps(result, ensure_ascii=False))
        return 0
    except SkillCatalogError as exc:
        print(f"skill_catalog: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
