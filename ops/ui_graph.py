#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""iOS UI type→type dependency graph, built from neutral kgindex records.

Pipeline (shared with ui_deadcode):
  ios_ops.sh build (isolated DerivedData) -> Xcode IndexStore
    -> kgindex (neutral extraction; each ref carries its enclosing-type container)
    -> build_graph (this file) -> queries / JSON / DOT

An edge A -> B means "type A references type B" (A depends on B): some reference
to B occurs inside A's body. kgindex resolves each reference site to its enclosing
nominal type (collapsing extensions onto the extended type), so these are真正的
type-level edges, not file-proximity guesses.

Nodes are the scanned kinds (default struct,class — the UI view set). An edge is
kept only when BOTH endpoints are nodes; references whose container is outside the
scanned set (an enum/protocol, or a stdlib type) are counted as external and not
drawn. Widen --kinds to bring more types into the graph.

Inputs (mutually exclusive): --build (default, isolated clean build) / --store-path
/ --records-json (test & fast-iterate seam). Outputs: human (--type focus), --json
(schema kg.ui.graph.v1), --dot (Graphviz).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import kgindex_records  # noqa: E402  (ops/lib shared module)

SCHEMA = "kg.ui.graph.v1"
DEFAULT_KINDS = ("struct", "class")
DEFAULT_SOURCE_ROOT = "ios/BooksBrowser/"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Graph construction (pure)
# --------------------------------------------------------------------------- #
def build_graph(records: dict, *, kinds: tuple[str, ...] = DEFAULT_KINDS) -> dict:
    """Build a type→type dependency graph from kgindex records.

    Returns:
        {
          "nodes": {usr: {"usr","name","kind","def"}},
          "deps":  {usr: set(usr)},   # A -> {B}: A references B (A depends on B)
          "users": {usr: set(usr)},   # B -> {A}: A references B (reverse)
          "externalIn": {usr: int},   # B -> count of refs from non-node containers
        }
    """
    kind_set = set(kinds)
    nodes: dict[str, dict] = {}
    for sym in records.get("symbols", []):
        if sym.get("kind") in kind_set:
            nodes[sym["usr"]] = {
                "usr": sym["usr"], "name": sym["name"],
                "kind": sym["kind"], "def": sym.get("def"),
            }

    deps: dict[str, set] = {u: set() for u in nodes}
    users: dict[str, set] = {u: set() for u in nodes}
    external_in: dict[str, int] = {u: 0 for u in nodes}

    for sym in records.get("symbols", []):
        b = sym["usr"]
        if b not in nodes:
            continue
        for ref in sym.get("refs", []):
            container = ref.get("container")
            if not container:
                continue
            a = container.get("usr")
            if a == b:
                continue  # drop self-references
            if a in nodes:
                deps[a].add(b)
                users[b].add(a)
            else:
                external_in[b] += 1

    return {"nodes": nodes, "deps": deps, "users": users, "externalIn": external_in}


def resolve_name(graph: dict, name: str) -> list[str]:
    """USRs of nodes whose name matches (exact). Multiple = same name, distinct types."""
    return sorted(u for u, n in graph["nodes"].items() if n["name"] == name)


def attach_catalog_surfaces(graph: dict, catalog_index: dict, *, stderr=sys.stderr) -> None:
    """Annotate graph nodes with catalog surfaces linked by backing type name."""
    surfaces = catalog_index.get("surfaces", {}) if isinstance(catalog_index, dict) else {}
    surface_nodes: dict[str, list[str]] = {}
    surface_meta: dict[str, dict] = {}
    for node in graph["nodes"].values():
        node["surface"] = []

    if not isinstance(surfaces, dict):
        graph["surfaceNodes"] = surface_nodes
        return

    for surface_name, entry in sorted(surfaces.items()):
        if not isinstance(entry, dict):
            continue
        backing = entry.get("backing")
        surface_meta[surface_name] = {
            "backing": backing,
            "kind": entry.get("kind"),
            "feature": entry.get("feature"),
            "screen": entry.get("screen"),
        }
        if not backing:
            surface_nodes[surface_name] = []
            continue
        matches = resolve_name(graph, backing)
        surface_nodes[surface_name] = matches
        if not matches:
            print(f"[ui_graph] catalog surface {surface_name!r} backing {backing!r} did not resolve to any scanned node", file=stderr)
            continue
        if len(matches) > 1:
            print(f"[ui_graph] catalog surface {surface_name!r} backing {backing!r} resolved ambiguously to {len(matches)} nodes", file=stderr)
        for usr in matches:
            graph["nodes"][usr]["surface"].append(surface_name)

    for node in graph["nodes"].values():
        node["surface"].sort()
    graph["surfaceNodes"] = surface_nodes
    graph["surfaceMeta"] = surface_meta


def discover_catalog_index(*, records_json: str | None = None) -> Path | None:
    if records_json:
        sibling = Path(records_json).with_name("catalog_index.json")
        if sibling.is_file():
            return sibling
    snapshots = sorted(
        PROJECT_ROOT.glob("build/snapshots/*/catalog_index.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return snapshots[0] if snapshots else None


def load_catalog_index(
    *,
    catalog_index_path: str | None = None,
    records_json: str | None = None,
    stderr=sys.stderr,
) -> tuple[dict, Path | None]:
    candidate = Path(catalog_index_path) if catalog_index_path else discover_catalog_index(records_json=records_json)
    if candidate is None:
        return {}, None
    if not candidate.is_file():
        raise SystemExit(f"[ui_graph] catalog index not found: {candidate}")
    try:
        data = json.loads(candidate.read_text())
    except ValueError as exc:
        raise SystemExit(f"[ui_graph] catalog index is not valid JSON: {candidate}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"[ui_graph] catalog index root must be an object: {candidate}")
    surfaces = data.get("surfaces", {})
    if not isinstance(surfaces, dict):
        raise SystemExit(f"[ui_graph] catalog index surfaces must be an object: {candidate}")
    print(f"[ui_graph] catalog surfaces <- {candidate}", file=stderr)
    return data, candidate


def _names(graph: dict, usrs) -> list[str]:
    return sorted(graph["nodes"][u]["name"] for u in usrs)


def resolve_surface(graph: dict, surface_name: str) -> list[str]:
    return list(graph.get("surfaceNodes", {}).get(surface_name, ()))


def forward_deps(graph: dict, usr: str) -> list[str]:
    """Names of nodes that `usr` depends on (uses)."""
    return _names(graph, graph["deps"].get(usr, ()))


def reverse_users(graph: dict, usr: str) -> list[str]:
    """Names of nodes that depend on `usr` (impact set if `usr` changes)."""
    return _names(graph, graph["users"].get(usr, ()))


def reverse_user_surfaces(graph: dict, usr: str) -> list[str]:
    names = set()
    for user_usr in graph["users"].get(usr, ()):
        names.update(graph["nodes"][user_usr].get("surface", ()))
    return sorted(names)


def graph_orphans(graph: dict) -> list[str]:
    """Node names with no in-edges from any node AND no external in-refs — nothing
    references them at all. (Distinct from ui_deadcode: this is graph-level, over
    the scanned node set only.)"""
    out = []
    for u, n in graph["nodes"].items():
        if not graph["users"].get(u) and graph["externalIn"].get(u, 0) == 0:
            out.append(n["name"])
    return sorted(out)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def build_payload(graph: dict, source_root: str) -> dict:
    edges = []
    for a, bs in graph["deps"].items():
        for b in bs:
            edges.append({"from": a, "to": b})
    edges.sort(key=lambda e: (e["from"], e["to"]))
    nodes = [graph["nodes"][u] for u in sorted(graph["nodes"])]
    return {
        "schema": SCHEMA,
        "generated_at": kgindex_records.utc_now(),
        "sourceRoot": source_root,
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def to_dot(graph: dict) -> str:
    lines = ["digraph kg_ui {", "  rankdir=LR;", '  node [shape=box, fontsize=10];']
    for u in sorted(graph["nodes"]):
        n = graph["nodes"][u]
        lines.append(f'  "{n["name"]}" [label="{n["name"]}"];')
    seen = set()
    for a, bs in graph["deps"].items():
        an = graph["nodes"][a]["name"]
        for b in sorted(bs):
            bn = graph["nodes"][b]["name"]
            key = (an, bn)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f'  "{an}" -> "{bn}";')
    lines.append("}")
    return "\n".join(lines)


def print_focus(graph: dict, name: str) -> None:
    usrs = resolve_name(graph, name)
    if not usrs:
        print(f"no node named {name!r} (is it in the scanned kinds?)")
        return
    for u in usrs:
        n = graph["nodes"][u]
        deps = forward_deps(graph, u)
        users = reverse_users(graph, u)
        loc = (n.get("def") or {})
        print(f"{n['kind']} {n['name']}  ({loc.get('path','?')}:{loc.get('line','?')})")
        print(f"  depends on ({len(deps)}): {', '.join(deps) or '—'}")
        print(f"  used by ({len(users)}): {', '.join(users) or '—'}")
        ext = graph["externalIn"].get(u, 0)
        if ext:
            print(f"  + {ext} reference(s) from non-node containers (enum/protocol/stdlib)")


def print_surface_focus(graph: dict, surface_name: str) -> None:
    surface_meta = graph.get("surfaceMeta", {}).get(surface_name)
    if surface_meta is None:
        print(f"no surface named {surface_name!r}")
        return
    usrs = resolve_surface(graph, surface_name)
    backing = surface_meta.get("backing")
    if not usrs:
        if backing:
            print(f"surface {surface_name!r} has backing {backing!r}, but it did not resolve to any scanned node")
        else:
            print(f"surface {surface_name!r} has no declared backing type")
        return
    for usr in usrs:
        node = graph["nodes"][usr]
        loc = node.get("def") or {}
        deps = forward_deps(graph, usr)
        dependent_surfaces = reverse_user_surfaces(graph, usr)
        print(f"surface {surface_name} -> {node['kind']} {node['name']}  ({loc.get('path','?')}:{loc.get('line','?')})")
        print(f"  depends on ({len(deps)}): {', '.join(deps) or '—'}")
        print(f"  depended on by surface(s) ({len(dependent_surfaces)}): {', '.join(dependent_surfaces) or '—'}")


def print_human(payload: dict, graph: dict) -> None:
    print(f"UI dependency graph — {payload['nodeCount']} nodes, {payload['edgeCount']} edges "
          f"under {payload['sourceRoot']}")
    orphans = graph_orphans(graph)
    if orphans:
        print(f"  {len(orphans)} node(s) with zero inbound references: {', '.join(orphans[:20])}"
              + (" …" if len(orphans) > 20 else ""))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--build", action="store_true", help="run an isolated clean build, then scan (default)")
    src.add_argument("--store-path", help="scan an existing IndexStore DataStore, skip build")
    src.add_argument("--records-json", help="read pre-captured kgindex records JSON, skip build+scan")
    p.add_argument("--catalog-index", help="catalog_index.json path (default: sibling of --records-json, else latest build/snapshots/*/catalog_index.json)")
    p.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help=f"source-root substring (default: {DEFAULT_SOURCE_ROOT})")
    p.add_argument("--kinds", default=",".join(DEFAULT_KINDS), help=f"node kinds (default: {','.join(DEFAULT_KINDS)})")
    p.add_argument("--type", dest="type_name", help="focus a single type: show its deps + users")
    p.add_argument("--surface", help="focus a single catalog surface: show its backing type deps + dependent surfaces")
    p.add_argument("--json", action="store_true", help="emit the full graph as JSON (schema kg.ui.graph.v1)")
    p.add_argument("--dot", action="store_true", help="emit Graphviz DOT")
    args = p.parse_args(argv)

    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())
    records, source_root = kgindex_records.acquire(
        args.source_root, kinds,
        records_json=args.records_json, store_path=args.store_path, label="ui_graph",
    )
    graph = build_graph(records, kinds=kinds)
    catalog_index, _ = load_catalog_index(
        catalog_index_path=args.catalog_index,
        records_json=args.records_json,
    )
    attach_catalog_surfaces(graph, catalog_index)

    if args.json:
        print(json.dumps(build_payload(graph, source_root), indent=2, ensure_ascii=False))
    elif args.dot:
        print(to_dot(graph))
    elif args.surface:
        print_surface_focus(graph, args.surface)
    elif args.type_name:
        print_focus(graph, args.type_name)
    else:
        print_human(build_payload(graph, source_root), graph)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
