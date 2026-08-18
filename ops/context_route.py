#!/usr/bin/env -S uv run --python 3.13
"""Resolve and render the minimum KG agent context for a typed route.

The manifest is deliberately separate from docs/registry.yml: the latter is
the document impact/ownership registry, while this file is the context loading
plan. A route emits slices, never an implicit whole-file read.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docs_impact import parse_registry


SCHEMA = "kg.context_plane.v1"
MANIFEST_NAME = "context_plane.json"
ROLE_ALIASES = {
    "Manager": "delivery-manager",
    "manager": "delivery-manager",
    "Ticket Factory": "ticket-factory",
    "platform-steward": "ticket-factory",
    "Delivery Team Integrator": "delivery-integrator",
    "delivery-coordinator": "delivery-integrator",
    "Delivery Child": "delivery-child",
    "backend-engineer": "delivery-child",
    "ios-engineer": "delivery-child",
    "ops-engineer": "delivery-child",
    "Docs Steward": "docs-steward",
    "docs-steward": "docs-steward",
    "Review service": "review-service",
    "review-service": "review-service",
    "code-reviewer": "review-service",
}
KNOWN_ROLES = {"delivery-manager", "ticket-factory", "delivery-integrator", "delivery-child", "docs-steward", "review-service"}
KNOWN_SURFACES = {"docs", "backend", "ios", "release"}
KNOWN_TASKS = {"review", "handback", "backend-routing", "feature-existence", "tool-friction", "docs-registry"}
KNOWN_SKILLS = {
    "app-debug", "billing", "data-analysis", "devops", "ios-simulator-verification",
    "ios-visual-report-workflow", "kg-agent-context", "kg-docs-control-plane", "kg-receipt",
    "kg-router", "podcast", "source-command-release", "worktree-flow",
}


class ContextPlaneError(ValueError):
    """A fail-closed manifest or route error."""


@dataclass(frozen=True)
class Unit:
    id: str
    path: str
    start: str
    end: str | None
    kind: str
    max_tokens: int
    purpose: str
    anchor_mode: str
    registry_id: str


def repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return root.resolve()
    return Path(__file__).resolve().parents[1]


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    root = repo_root(root)
    path = root / "ops" / MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContextPlaneError(f"manifest 不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContextPlaneError(f"manifest JSON 無效: line={exc.lineno} col={exc.colno}") from exc
    validate_manifest(payload, root)
    return payload


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ContextPlaneError(f"{context} 缺少欄位: {key}")
    return mapping[key]


def validate_manifest(payload: dict[str, Any], root: Path) -> None:
    if payload.get("schema") != SCHEMA:
        raise ContextPlaneError(f"schema 必須是 {SCHEMA}")
    if payload.get("version") != 1:
        raise ContextPlaneError("只支援 context plane version=1")
    estimator = _require(payload, "token_estimator", "manifest")
    if estimator.get("name") != "chars_div4_ceil":
        raise ContextPlaneError("不支援的 token estimator")
    registry_rel = _require(payload, "registry", "manifest")
    if not isinstance(registry_rel, str):
        raise ContextPlaneError("manifest.registry 必須是字串")
    registry_path = root / registry_rel
    if not registry_path.is_file():
        raise ContextPlaneError(f"registry 不存在: {registry_rel}")
    try:
        registry = {document.id: document for document in parse_registry(registry_path)}
    except (OSError, ValueError) as exc:
        raise ContextPlaneError(f"registry 無法解析: {exc}") from exc
    defaults = _require(payload, "defaults", "manifest")
    for budget_name in ("max_route_tokens", "max_unit_tokens"):
        if not isinstance(defaults.get(budget_name), int) or defaults[budget_name] <= 0:
            raise ContextPlaneError(f"defaults.{budget_name} 必須是正整數")

    units = _require(payload, "units", "manifest")
    if not isinstance(units, list) or not units:
        raise ContextPlaneError("units 必須是非空陣列")
    ids: set[str] = set()
    for index, raw in enumerate(units):
        context = f"units[{index}]"
        if not isinstance(raw, dict):
            raise ContextPlaneError(f"{context} 必須是 object")
        unknown = sorted(set(raw) - {"id", "path", "registry_id", "start", "end", "anchor_mode", "kind", "max_tokens", "purpose"})
        if unknown:
            raise ContextPlaneError(f"{context} 未知欄位: {', '.join(unknown)}")
        unit_id = _require(raw, "id", context)
        if not isinstance(unit_id, str) or not unit_id or unit_id in ids:
            raise ContextPlaneError(f"{context}.id 必須唯一且非空")
        ids.add(unit_id)
        path = _require(raw, "path", context)
        registry_id = _require(raw, "registry_id", context)
        start = _require(raw, "start", context)
        end = raw.get("end")
        if not isinstance(path, str) or not isinstance(start, str) or not start:
            raise ContextPlaneError(f"{context} 的 path/start 無效")
        if not isinstance(registry_id, str) or registry_id not in registry:
            raise ContextPlaneError(f"{context}.registry_id 不存在: {registry_id}")
        if not _registry_owns_path(registry[registry_id], path):
            raise ContextPlaneError(f"{context}.path 不在 registry sources: {registry_id} -> {path}")
        if end is not None and not isinstance(end, str):
            raise ContextPlaneError(f"{context}.end 必須是字串或 null")
        if raw.get("anchor_mode", "exact") not in {"exact", "prefix"}:
            raise ContextPlaneError(f"{context}.anchor_mode 必須是 exact 或 prefix")
        max_tokens = _require(raw, "max_tokens", context)
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ContextPlaneError(f"{context}.max_tokens 必須是正整數")
        if max_tokens > defaults["max_unit_tokens"]:
            raise ContextPlaneError(
                f"{context}.max_tokens 超過全域上限: "
                f"declared={max_tokens} max={defaults['max_unit_tokens']}"
            )
        if not isinstance(raw.get("kind"), str) or not raw["kind"]:
            raise ContextPlaneError(f"{context}.kind 必須是非空字串")
        if not isinstance(raw.get("purpose"), str) or not raw["purpose"]:
            raise ContextPlaneError(f"{context}.purpose 必須是非空字串")
        source = root / path
        if not source.is_file():
            raise ContextPlaneError(f"{context}.path 不存在: {path}")
        _slice_text(source.read_text(encoding="utf-8"), start, end, unit_id, raw.get("anchor_mode", "exact"))

    routes = _require(payload, "routes", "manifest")
    route_ids: set[str] = set()
    for index, route in enumerate(routes):
        context = f"routes[{index}]"
        if not isinstance(route, dict):
            raise ContextPlaneError(f"{context} 必須是 object")
        unknown = sorted(set(route) - {"id", "match", "units"})
        if unknown:
            raise ContextPlaneError(f"{context} 未知欄位: {', '.join(unknown)}")
        route_id = _require(route, "id", context)
        if not isinstance(route_id, str) or not route_id or route_id in route_ids:
            raise ContextPlaneError(f"{context}.id 必須唯一且非空")
        route_ids.add(route_id)
        match = _require(route, "match", context)
        if not isinstance(match, dict) or not isinstance(match.get("roles"), list) or not match["roles"]:
            raise ContextPlaneError(f"{context}.match.roles 必須是非空陣列")
        if not all(isinstance(role, str) and (role == "*" or role in KNOWN_ROLES) for role in match["roles"]):
            raise ContextPlaneError(f"{context}.match.roles 含未知 role")
        unknown_match = sorted(set(match) - {"roles", "surfaces", "tasks", "skills"})
        if unknown_match:
            raise ContextPlaneError(f"{context}.match 未知欄位: {', '.join(unknown_match)}")
        for field, allowed in (("surfaces", KNOWN_SURFACES), ("tasks", KNOWN_TASKS), ("skills", KNOWN_SKILLS)):
            if field in match and (not isinstance(match[field], list) or not set(match[field]) <= allowed):
                raise ContextPlaneError(f"{context}.match.{field} 含未知值")
        route_units = _require(route, "units", context)
        if not isinstance(route_units, list) or not route_units:
            raise ContextPlaneError(f"{context}.units 必須是非空陣列")
        unknown = sorted(set(route_units) - ids)
        if unknown:
            raise ContextPlaneError(f"{context}.units 引用未知 unit: {', '.join(unknown)}")


def _anchor_indexes(lines: list[str], anchor: str, mode: str) -> list[int]:
    if mode == "exact":
        return [i for i, line in enumerate(lines) if line.rstrip("\r\n") == anchor]
    if mode == "prefix":
        return [i for i, line in enumerate(lines) if line.startswith(anchor)]
    raise ContextPlaneError(f"不支援的 anchor_mode: {mode}")


def _registry_owns_path(document: Any, path: str) -> bool:
    normalized = path.removeprefix("./")
    positive = normalized == document.path.removeprefix("./")
    for raw_source in document.sources:
        source = raw_source.removeprefix("./")
        if source.startswith("!"):
            excluded = source[1:]
            if _source_matches(normalized, excluded):
                return False
            continue
        if _source_matches(normalized, source):
            positive = True
    return positive


def _source_matches(normalized: str, source: str) -> bool:
    if source.endswith("/") and normalized.startswith(source):
        return True
    if any(char in source for char in "*?[") and fnmatch.fnmatch(normalized, source):
        return True
    return normalized == source


def _slice_text(text: str, start: str, end: str | None, unit_id: str, anchor_mode: str = "exact") -> str:
    lines = text.splitlines(keepends=True)
    start_indexes = _anchor_indexes(lines, start, anchor_mode)
    if len(start_indexes) != 1:
        raise ContextPlaneError(f"unit {unit_id} 的 start anchor 次數={len(start_indexes)}，必須恰為 1")
    start_index = start_indexes[0]
    if end is None:
        end_index = len(lines)
    else:
        end_indexes = _anchor_indexes(lines, end, anchor_mode)
        if len(end_indexes) != 1:
            raise ContextPlaneError(f"unit {unit_id} 的 end anchor 次數={len(end_indexes)}，必須恰為 1")
        end_index = end_indexes[0]
    if end_index <= start_index:
        raise ContextPlaneError(f"unit {unit_id} 的 anchors 順序無效")
    return "".join(lines[start_index:end_index])


def _units(payload: dict[str, Any]) -> dict[str, Unit]:
    return {
        raw["id"]: Unit(
            id=raw["id"],
            path=raw["path"],
            start=raw["start"],
            end=raw.get("end"),
            kind=raw["kind"],
            max_tokens=raw["max_tokens"],
            purpose=raw["purpose"],
            anchor_mode=raw.get("anchor_mode", "exact"),
            registry_id=raw["registry_id"],
        )
        for raw in payload["units"]
    }


def _matches(match: dict[str, Any], role: str, surface: str | None, task: str | None, skill: str | None) -> bool:
    roles = match.get("roles", [])
    if role not in roles and "*" not in roles:
        return False
    if "surfaces" in match and (surface is None or surface not in match["surfaces"]):
        return False
    if "tasks" in match and (task is None or task not in match["tasks"]):
        return False
    if "skills" in match and (skill is None or skill not in match["skills"]):
        return False
    return True


def _git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise ContextPlaneError(f"git metadata 讀取失敗: {' '.join(args)}")
    return result.stdout.strip()


def _read_source(path: Path) -> tuple[str, str]:
    try:
        data = path.read_bytes()
        return data.decode("utf-8"), hashlib.sha256(data).hexdigest()
    except OSError as exc:
        raise ContextPlaneError(f"source 無法讀取: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ContextPlaneError(f"source 不是 UTF-8: {path}") from exc


def _sha256(path: Path) -> str:
    return _read_source(path)[1]


def _provenance(root: Path, manifest_path: Path, registry_path: Path) -> dict[str, Any]:
    return {
        "worktree": str(root.resolve()),
        "head": _git_value(root, "rev-parse", "HEAD"),
        "branch": _git_value(root, "symbolic-ref", "--quiet", "--short", "HEAD") or "(detached)",
        "registryPath": str(registry_path.resolve()),
        "registrySha256": _sha256(registry_path),
        "manifestPath": str(manifest_path.resolve()),
        "manifestSha256": _sha256(manifest_path),
        "loader": "kg.context_route.v1",
    }


def resolve_route(
    payload: dict[str, Any],
    role: str,
    surface: str | None = None,
    task: str | None = None,
    skill: str | None = None,
    root: Path | None = None,
    capability_tier: str = "observer",
) -> dict[str, Any]:
    role = ROLE_ALIASES.get(role, role)
    if role not in KNOWN_ROLES:
        raise ContextPlaneError(f"找不到可用 role: {role or '-'}")
    if surface is not None and surface not in KNOWN_SURFACES:
        raise ContextPlaneError(f"找不到可用 surface: {surface}")
    if task is not None and task not in KNOWN_TASKS:
        raise ContextPlaneError(f"找不到可用 task: {task}")
    if skill is not None and skill not in KNOWN_SKILLS:
        raise ContextPlaneError(f"找不到可用 skill: {skill}")
    units = _units(payload)
    selected_routes: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for route in payload["routes"]:
        if not _matches(route["match"], role, surface, task, skill):
            continue
        selected_routes.append(route)
        for unit_id in route["units"]:
            if unit_id not in selected_ids:
                selected_ids.append(unit_id)
    if not selected_routes or "kernel.startup" not in selected_ids:
        raise ContextPlaneError(f"找不到可用 route: role={role} surface={surface or '-'} task={task or '-'}")

    root = repo_root(root)
    manifest_path = root / "ops" / MANIFEST_NAME
    registry_path = root / payload["registry"]
    before = _provenance(root, manifest_path, registry_path)
    selected_paths = {root / units[unit_id].path for unit_id in selected_ids}
    source_before = {path: _read_source(path)[1] for path in selected_paths}
    rendered: list[dict[str, Any]] = []
    total = 0
    for unit_id in selected_ids:
        unit = units[unit_id]
        source_path = root / unit.path
        source_text, source_sha256 = _read_source(source_path)
        text = _slice_text(
            source_text,
            unit.start,
            unit.end,
            unit.id,
            unit.anchor_mode,
        )
        estimated = math.ceil(len(text) / 4)
        if estimated > unit.max_tokens:
            raise ContextPlaneError(
                f"unit {unit.id} 超過宣告 budget: estimated={estimated} max={unit.max_tokens}"
            )
        total += estimated
        rendered.append(
            {
                "id": unit.id,
                "path": unit.path,
                "absolutePath": str((root / unit.path).resolve()),
                "kind": unit.kind,
                "purpose": unit.purpose,
                "contentType": "untrusted-document-data",
                "registryId": unit.registry_id,
                "sourceSha256": source_sha256,
                "estimatedTokens": estimated,
                "maxTokens": unit.max_tokens,
                "start": unit.start,
                "end": unit.end,
                "content": text,
            }
        )
    max_route_tokens = payload["defaults"]["max_route_tokens"]
    if total > max_route_tokens:
        raise ContextPlaneError(f"route 超過 budget: estimated={total} max={max_route_tokens}")
    after = _provenance(root, manifest_path, registry_path)
    source_after = {path: _sha256(path) for path in selected_paths}
    if before != after or source_before != source_after:
        raise ContextPlaneError("context 讀取期間 HEAD、registry、manifest 或 branch 發生變動")
    return {
        "schema": SCHEMA,
        "role": role,
        "surface": surface,
        "task": task,
        "skill": skill,
        "roleAttestation": {"value": role, "source": "explicit-cli", "status": "untrusted-input"},
        "authorization": {"capabilityTier": capability_tier, "granted": False},
        "provenance": before,
        "routes": [route["id"] for route in selected_routes],
        "units": rendered,
        "summary": {
            "unitCount": len(rendered),
            "estimatedTokens": total,
            "maxTokens": max_route_tokens,
            "sourceFiles": sorted({unit["path"] for unit in rendered}),
            "fullFileFallback": False,
        },
    }


def format_text(payload: dict[str, Any]) -> str:
    lines = [
        f"[context][route] role={payload['role']} surface={payload['surface'] or '-'} task={payload['task'] or '-'}",
        f"[context][budget] estimated={payload['summary']['estimatedTokens']} max={payload['summary']['maxTokens']}",
    ]
    for unit in payload["units"]:
        lines.append(
            f"[context][unit] {unit['id']} path={unit['path']} "
            f"estimated={unit['estimatedTokens']} max={unit['maxTokens']}"
        )
        lines.append(f"[context][purpose] {unit['purpose']}")
        lines.append(unit["content"].rstrip())
    return "\n".join(lines) + "\n"


def format_index(payload: dict[str, Any]) -> str:
    lines = [
        f"[context][route] role={payload['role']} skill={payload.get('skill') or '-'} "
        f"surface={payload['surface'] or '-'} task={payload['task'] or '-'}",
        f"[context][budget] estimated={payload['summary']['estimatedTokens']} max={payload['summary']['maxTokens']}",
    ]
    for unit in payload["units"]:
        lines.append(
            f"[context][unit] {unit['id']} path={unit['path']} "
            f"estimated={unit['estimatedTokens']} max={unit['maxTokens']}"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="resolve and render minimum KG agent context")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate manifest paths, anchors and route references")
    validate.add_argument("--json", action="store_true")
    validate.add_argument("--root", type=Path)
    list_parser = subparsers.add_parser("list", help="list context units and routes")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--root", type=Path)
    route = subparsers.add_parser("route", help="resolve a route without emitting source content")
    route.add_argument("--role", required=True)
    route.add_argument("--surface")
    route.add_argument("--task")
    route.add_argument("--skill")
    route.add_argument("--tier", choices=["observer", "operator", "editor", "production-capable"], default="observer")
    route.add_argument("--json", action="store_true")
    route.add_argument("--root", type=Path)
    render = subparsers.add_parser("render", help="resolve and emit only selected source slices")
    render.add_argument("--role", required=True)
    render.add_argument("--surface")
    render.add_argument("--task")
    render.add_argument("--skill")
    render.add_argument("--tier", choices=["observer", "operator", "editor", "production-capable"], default="observer")
    render.add_argument("--json", action="store_true")
    render.add_argument("--root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        payload = load_manifest(getattr(args, "root", None))
        if args.command == "validate":
            result = {"schema": SCHEMA, "status": "ok", "units": len(payload["units"]), "routes": len(payload["routes"])}
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "context_plane: OK\n")
            return 0
        if args.command == "list":
            result = {
                "schema": SCHEMA,
                "units": payload["units"],
                "routes": payload["routes"],
            }
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("context_plane: catalog\n")
                for unit in payload["units"]:
                    print(f"[context][catalog] {unit['id']} path={unit['path']} max={unit['max_tokens']}")
                for route in payload["routes"]:
                    print(f"[context][route-definition] {route['id']} units={','.join(route['units'])}")
            return 0
        resolved = resolve_route(
            payload,
            args.role,
            args.surface,
            args.task,
            args.skill,
            getattr(args, "root", None),
            args.tier,
        )
        if args.command == "route":
            if args.json:
                for unit in resolved["units"]:
                    unit.pop("content", None)
                print(json.dumps(resolved, ensure_ascii=False, indent=2))
            else:
                print(format_index(resolved), end="")
        else:
            print(json.dumps(resolved, ensure_ascii=False, indent=2) if args.json else format_text(resolved))
        return 0
    except ContextPlaneError as exc:
        print(f"context_plane: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
