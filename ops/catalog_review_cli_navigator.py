from __future__ import annotations

import json
from pathlib import Path


def _load_manifest(root: Path) -> dict:
    return json.loads((root / "review_manifest.json").read_text(encoding="utf-8"))


def _find_node(tree: dict, node_path: str) -> dict | None:
    if tree.get("nodePath", "") == node_path:
        return tree
    for child in tree.get("children") or []:
        found = _find_node(child, node_path)
        if found is not None:
            return found
    return None


def _truncate(node: dict, depth: int | None) -> dict:
    pruned = {key: value for key, value in node.items() if key != "children"}
    children = node.get("children") or []
    pruned["childCount"] = len(children)
    if depth is None:
        pruned["children"] = [_truncate(child, None) for child in children]
    elif depth > 0:
        pruned["children"] = [_truncate(child, depth - 1) for child in children]
    return pruned


def _ancestor_paths(node_path: str) -> list[str]:
    if not node_path:
        return []
    parts = node_path.split("/")
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


def _resolve_canvas_base(root: Path, base: str | None) -> str:
    if base:
        return base.rstrip("/")
    canvas = root / "catalog.html"
    if canvas.exists():
        return canvas.resolve().as_uri()
    return (root / "catalog.html").resolve().as_uri()


def cmd_tree(root: Path, *, node: str, depth: int | None) -> int:
    manifest = _load_manifest(root)
    tree = manifest.get("tree")
    if tree is None:
        print(json.dumps({"status": "error", "error": "manifest-missing-tree"}, ensure_ascii=False))
        return 1
    target = _find_node(tree, node)
    if target is None:
        print(json.dumps({"status": "error", "error": "node-not-found", "node": node}, ensure_ascii=False))
        return 1
    payload = {
        "status": "ok",
        "node": node,
        "depth": depth,
        "tree": _truncate(target, depth),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_node(root: Path, node: str) -> int:
    manifest = _load_manifest(root)
    tree = manifest.get("tree")
    if tree is None:
        print(json.dumps({"status": "error", "error": "manifest-missing-tree"}, ensure_ascii=False))
        return 1
    target = _find_node(tree, node)
    if target is None:
        print(json.dumps({"status": "error", "error": "node-not-found", "node": node}, ensure_ascii=False))
        return 1
    children = target.get("children") or []
    payload = {
        "status": "ok",
        "node": {key: value for key, value in target.items() if key != "children"},
        "ancestors": _ancestor_paths(node),
        "childCount": len(children),
        "children": [
            {key: value for key, value in child.items() if key != "children"}
            for child in children
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_node_url(root: Path, node: str, *, base: str | None) -> int:
    manifest = _load_manifest(root)
    tree = manifest.get("tree")
    if tree is None:
        print(json.dumps({"status": "error", "error": "manifest-missing-tree"}, ensure_ascii=False))
        return 1
    if _find_node(tree, node) is None:
        print(json.dumps({"status": "error", "error": "node-not-found", "node": node}, ensure_ascii=False))
        return 1
    canvas_base = _resolve_canvas_base(root, base)
    fragment = f"#node={node}" if node else ""
    payload = {
        "status": "ok",
        "node": node,
        "url": f"{canvas_base}{fragment}",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0
