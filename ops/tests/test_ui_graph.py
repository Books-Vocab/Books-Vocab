"""Graph-construction unit tests for ops/ui_graph.py (pure, no build needed)."""
import importlib.util
import json
from pathlib import Path

OPS = Path(__file__).resolve().parent.parent
FIXTURES = OPS / "fixtures" / "ui_deadcode"

_spec = importlib.util.spec_from_file_location("ui_graph", OPS / "ui_graph.py")
ui_graph = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui_graph)


def _records():
    return json.loads((FIXTURES / "records_graph.json").read_text())


def _catalog_index():
    return json.loads((FIXTURES / "catalog_index.json").read_text())


def _graph():
    return ui_graph.build_graph(_records())  # default kinds struct,class


def test_nodes_are_only_scanned_kinds():
    g = _graph()
    # EnumX is an enum → not a node under default struct,class
    assert sorted(n["name"] for n in g["nodes"].values()) == ["Card", "Lonely", "Pill", "Screen"]


def test_forward_deps():
    g = _graph()
    screen = ui_graph.resolve_name(g, "Screen")[0]
    card = ui_graph.resolve_name(g, "Card")[0]
    assert ui_graph.forward_deps(g, screen) == ["Card"]
    assert ui_graph.forward_deps(g, card) == ["Pill"]


def test_reverse_users_is_impact_set():
    g = _graph()
    card = ui_graph.resolve_name(g, "Card")[0]
    pill = ui_graph.resolve_name(g, "Pill")[0]
    assert ui_graph.reverse_users(g, card) == ["Screen"]
    assert ui_graph.reverse_users(g, pill) == ["Card"]


def test_self_reference_is_dropped():
    g = _graph()
    card = ui_graph.resolve_name(g, "Card")[0]
    assert card not in g["deps"][card]
    assert "Card" not in ui_graph.forward_deps(g, card)


def test_external_container_counted_not_edged():
    g = _graph()
    card = ui_graph.resolve_name(g, "Card")[0]
    # the EnumX-contained ref to Card is external (EnumX not a node)
    assert g["externalIn"][card] == 1
    # and EnumX is not a node, so no edge from it
    assert "EnumX" not in [g["nodes"][u]["name"] for u in g["users"][card]]


def test_graph_orphans_are_zero_inbound_nodes():
    g = _graph()
    # Screen: root (no inbound). Lonely: no refs at all. Card/Pill have inbound.
    assert ui_graph.graph_orphans(g) == ["Lonely", "Screen"]


def test_catalog_surfaces_attach_to_nodes_by_backing_name():
    g = _graph()
    ui_graph.attach_catalog_surfaces(g, _catalog_index())
    card = ui_graph.resolve_name(g, "Card")[0]
    screen = ui_graph.resolve_name(g, "Screen")[0]
    lonely = ui_graph.resolve_name(g, "Lonely")[0]
    assert g["nodes"][card]["surface"] == ["Card Detail Surface", "Card Surface"]
    assert g["nodes"][screen]["surface"] == ["Screen Surface"]
    assert g["nodes"][lonely]["surface"] == []


def test_catalog_surface_index_tracks_backing_nodes():
    g = _graph()
    ui_graph.attach_catalog_surfaces(g, _catalog_index())
    card = ui_graph.resolve_name(g, "Card")[0]
    assert g["surfaceNodes"]["Card Surface"] == [card]
    assert g["surfaceNodes"]["Card Detail Surface"] == [card]
    assert g["surfaceNodes"]["Inline Surface"] == []
    assert g["surfaceNodes"]["Unknown Backing Surface"] == []


def test_resolve_surface_uses_catalog_surface_index():
    g = _graph()
    ui_graph.attach_catalog_surfaces(g, _catalog_index())
    card = ui_graph.resolve_name(g, "Card")[0]
    assert ui_graph.resolve_surface(g, "Card Surface") == [card]
    assert ui_graph.resolve_surface(g, "Inline Surface") == []
    assert ui_graph.resolve_surface(g, "DoesNotExist") == []


def test_reverse_user_surfaces_collect_surface_names_from_user_nodes():
    g = _graph()
    ui_graph.attach_catalog_surfaces(g, _catalog_index())
    card = ui_graph.resolve_name(g, "Card")[0]
    pill = ui_graph.resolve_name(g, "Pill")[0]
    assert ui_graph.reverse_user_surfaces(g, card) == ["Screen Surface"]
    assert ui_graph.reverse_user_surfaces(g, pill) == ["Card Detail Surface", "Card Surface"]


def test_payload_schema_and_counts():
    g = _graph()
    ui_graph.attach_catalog_surfaces(g, _catalog_index())
    payload = ui_graph.build_payload(g, "ios/BooksBrowser/")
    assert payload["schema"] == "kg.ui.graph.v1"
    assert payload["nodeCount"] == 4
    assert payload["edgeCount"] == 2  # Screen->Card, Card->Pill
    assert "generated_at" in payload
    froms = {e["from"] for e in payload["edges"]}
    assert "s:Screen" in froms and "s:Card" in froms
    nodes = {node["name"]: node for node in payload["nodes"]}
    assert nodes["Card"]["surface"] == ["Card Detail Surface", "Card Surface"]
    assert nodes["Lonely"]["surface"] == []


def test_dot_export_contains_edges():
    g = _graph()
    dot = ui_graph.to_dot(g)
    assert "digraph kg_ui" in dot
    assert '"Screen" -> "Card";' in dot
    assert '"Card" -> "Pill";' in dot
    assert '"Card" -> "Card";' not in dot  # no self-loop


def test_resolve_name_unknown_returns_empty():
    g = _graph()
    assert ui_graph.resolve_name(g, "DoesNotExist") == []


def test_widening_kinds_adds_enum_nodes():
    g = ui_graph.build_graph(_records(), kinds=("struct", "class", "enum"))
    assert "EnumX" in [n["name"] for n in g["nodes"].values()]
    # now the EnumX->Card ref becomes a real edge
    card = ui_graph.resolve_name(g, "Card")[0]
    assert "EnumX" in ui_graph.reverse_users(g, card)
