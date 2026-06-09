"""Declarative expected-vs-actual diff for ops world-state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SPEC_SCHEMA = "kg.ops_world_expectation.v1"
DIFF_SCHEMA = "kg.ops_world_diff.v1"


def load_expectation(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expectation spec 必須是 object")
    if data.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"expectation spec schema 必須是 {SPEC_SCHEMA}")
    return data


def _compare_subset(
    actual: Any,
    expected: Any,
    *,
    path: str,
    mismatches: list[dict[str, Any]],
) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            mismatches.append({
                "kind": "type-mismatch",
                "path": path,
                "expected": "object",
                "actual": type(actual).__name__,
            })
            return
        for key, value in expected.items():
            child_path = f"{path}.{key}" if path else key
            if key not in actual:
                mismatches.append({
                    "kind": "missing-key",
                    "path": child_path,
                    "expected": value,
                    "actual": None,
                })
                continue
            _compare_subset(actual[key], value, path=child_path, mismatches=mismatches)
        return
    if actual != expected:
        mismatches.append({
            "kind": "value-mismatch",
            "path": path,
            "expected": expected,
            "actual": actual,
        })


def _card_key(card: dict[str, Any]) -> str | None:
    content = card.get("content")
    return str(content) if isinstance(content, str) and content else None


def _notebook_key(notebook: dict[str, Any]) -> str | None:
    for field in ("id", "name"):
        value = notebook.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _notebook_aliases(notebook: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for field in ("id", "name"):
        value = notebook.get(field)
        if isinstance(value, str) and value and value not in aliases:
            aliases.append(value)
    return aliases


def _graph_link_key(link: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        link.get("from") if isinstance(link.get("from"), str) else link.get("from_content"),
        link.get("to") if isinstance(link.get("to"), str) else link.get("to_content"),
        str(link.get("kind")) if link.get("kind") is not None else None,
    )


def diff_world_state(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []

    if "config" in expected:
        _compare_subset(actual.get("config", {}), expected["config"], path="config", mismatches=mismatches)

    if "notebooks" in expected:
        actual_notebooks: dict[str, dict[str, Any]] = {}
        for notebook in actual.get("notebooks", []):
            if not isinstance(notebook, dict):
                continue
            for key in _notebook_aliases(notebook):
                actual_notebooks[key] = notebook
        for notebook in expected["notebooks"]:
            if not isinstance(notebook, dict):
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": "notebooks",
                    "expected": "object entries",
                    "actual": notebook,
                })
                continue
            key = _notebook_key(notebook)
            label = key or "<unknown>"
            if key is None or key not in actual_notebooks:
                mismatches.append({
                    "kind": "missing-notebook",
                    "path": f"notebooks[{label}]",
                    "expected": notebook,
                    "actual": None,
                })
                continue
            _compare_subset(actual_notebooks[key], notebook, path=f"notebooks[{label}]", mismatches=mismatches)

    if "cards" in expected:
        actual_cards = {
            key: card for card in actual.get("cards", [])
            if isinstance(card, dict) and (key := _card_key(card)) is not None
        }
        for card in expected["cards"]:
            if not isinstance(card, dict):
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": "cards",
                    "expected": "object entries",
                    "actual": card,
                })
                continue
            key = _card_key(card)
            label = key or "<unknown>"
            if key is None or key not in actual_cards:
                mismatches.append({
                    "kind": "missing-card",
                    "path": f"cards[{label}]",
                    "expected": card,
                    "actual": None,
                })
                continue
            normalized = dict(card)
            if "notebook" in normalized and "notebook_name" not in normalized:
                normalized["notebook_name"] = normalized.pop("notebook")
            _compare_subset(actual_cards[key], normalized, path=f"cards[{label}]", mismatches=mismatches)

    if "graphs" in expected:
        actual_graphs: dict[str, dict[str, Any]] = {}
        for graph in actual.get("graphs", []):
            if not isinstance(graph, dict):
                continue
            for key in (graph.get("notebook_name"), graph.get("notebook_id")):
                if isinstance(key, str) and key:
                    actual_graphs[key] = graph
        for graph in expected["graphs"]:
            if not isinstance(graph, dict):
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": "graphs",
                    "expected": "object entries",
                    "actual": graph,
                })
                continue
            key = graph.get("notebook") or graph.get("notebook_name") or graph.get("notebook_id")
            label = str(key) if key else "<unknown>"
            if not isinstance(key, str) or key not in actual_graphs:
                mismatches.append({
                    "kind": "missing-graph",
                    "path": f"graphs[{label}]",
                    "expected": graph,
                    "actual": None,
                })
                continue
            actual_graph = actual_graphs[key]
            actual_links = {
                _graph_link_key(link): link
                for link in actual_graph.get("links", [])
                if isinstance(link, dict)
            }
            for idx, link in enumerate(graph.get("links", [])):
                if not isinstance(link, dict):
                    mismatches.append({
                        "kind": "invalid-spec",
                        "path": f"graphs[{label}].links[{idx}]",
                        "expected": "object",
                        "actual": link,
                    })
                    continue
                link_key = _graph_link_key(link)
                link_label = f"{link_key[0]}->{link_key[1]}:{link_key[2]}"
                if link_key not in actual_links:
                    mismatches.append({
                        "kind": "missing-link",
                        "path": f"graphs[{label}].links[{link_label}]",
                        "expected": link,
                        "actual": None,
                    })
                    continue
                normalized = dict(link)
                if "from" in normalized and "from_content" not in normalized:
                    normalized["from_content"] = normalized.pop("from")
                if "to" in normalized and "to_content" not in normalized:
                    normalized["to_content"] = normalized.pop("to")
                _compare_subset(
                    actual_links[link_key],
                    normalized,
                    path=f"graphs[{label}].links[{link_label}]",
                    mismatches=mismatches,
                )

    return {
        "schema": DIFF_SCHEMA,
        "expectedSchema": expected.get("schema"),
        "actualSchema": actual.get("schema"),
        "ok": not mismatches,
        "mismatchCount": len(mismatches),
        "mismatches": mismatches,
    }
