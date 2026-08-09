"""Declarative expected-vs-actual diff for ops world-state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ops_world_export import SEED_SPEC_SCHEMA, WorldExportError, _norm_dt

SPEC_SCHEMA = "kg.ops_world_expectation.v1"
DIFF_SCHEMA = "kg.ops_world_diff.v1"

# seed 可重放、且由 world-export 輸出的 verbatim 欄位。content/notebook 是
# entity key；review 另走 _diff_seed_review 的 counter transform。
_SEED_CARD_FIELDS = (
    "meaning", "pos", "note", "difficulty", "mode", "root_form",
    "inflections", "examples", "collocations", "is_archived", "source",
    "source_shared_card_guid",
)
_SEED_NOTEBOOK_FIELDS = (
    "color", "cover_pattern", "sort_order", "is_default",
    "source_shared_deck_id", "source_version",
)
_SEED_LINK_FIELDS = ("confidence", "reason")
_REVIEW_DT_KEYS = frozenset({"next_review_at", "last_reviewed_at"})
_REVIEW_COUNTER_KEYS = frozenset({
    "review_count", "review_streak", "lapse_count", "review_interval_hours",
    "next_review_at", "last_reviewed_at", "last_review_feedback",
})


def load_expectation(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expectation spec 必須是 object")
    schema = data.get("schema")
    if schema not in (SPEC_SCHEMA, SEED_SPEC_SCHEMA):
        raise ValueError(
            f"spec schema 必須是 {SPEC_SCHEMA} 或 {SEED_SPEC_SCHEMA}，得到 {schema!r}"
        )
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


def _compare_graphs(
    actual: dict[str, Any],
    expected_graphs: Any,
    *,
    mismatches: list[dict[str, Any]],
) -> None:
    """Append graph/link mismatches (read-only over ``actual``/``expected``)."""
    actual_graphs: dict[str, dict[str, Any]] = {}
    for graph in actual.get("graphs", []):
        if not isinstance(graph, dict):
            continue
        for key in (graph.get("notebook_name"), graph.get("notebook_id")):
            if isinstance(key, str) and key:
                actual_graphs[key] = graph
    for graph in expected_graphs:
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
        _compare_graphs(actual, expected["graphs"], mismatches=mismatches)

    return {
        "schema": DIFF_SCHEMA,
        "expectedSchema": expected.get("schema"),
        "actualSchema": actual.get("schema"),
        "ok": not mismatches,
        "mismatchCount": len(mismatches),
        "mismatches": mismatches,
    }


def _default_notebook_name(actual: dict[str, Any]) -> str | None:
    for notebook in actual.get("notebooks", []):
        if (
            isinstance(notebook, dict)
            and notebook.get("is_default")
            and isinstance(notebook.get("name"), str)
        ):
            return notebook["name"]
    return None


def _seed_card_key(
    card: dict[str, Any], default_nb: str | None
) -> tuple[str, str] | None:
    """Return the seed card identity ``(notebook name, content)``."""
    content = card.get("content")
    notebook = card.get("notebook") or default_nb
    if (
        not isinstance(content, str)
        or not content
        or not isinstance(notebook, str)
        or not notebook
    ):
        return None
    return notebook, content


def _seed_link_key(
    link: dict[str, Any], default_nb: str | None
) -> tuple[str, str, str, str] | None:
    notebook = link.get("notebook") or default_nb
    from_content = link.get("from")
    to_content = link.get("to")
    kind = link.get("kind")
    if not all(isinstance(value, str) and value for value in (
        notebook, from_content, to_content, kind,
    )):
        return None
    return notebook, from_content, to_content, kind


def _diff_seed_fields(
    actual_obj: dict[str, Any],
    expected_obj: dict[str, Any],
    fields: tuple[str, ...],
    *,
    path: str,
    mismatches: list[dict[str, Any]],
) -> None:
    """Compare only fields explicitly declared by the seed spec."""
    for key in fields:
        if key not in expected_obj:
            continue
        child_path = f"{path}.{key}"
        expected_value = expected_obj[key]
        if key not in actual_obj:
            mismatches.append({
                "kind": "missing-key",
                "path": child_path,
                "expected": expected_value,
                "actual": None,
            })
        elif actual_obj[key] != expected_value:
            mismatches.append({
                "kind": "value-mismatch",
                "path": child_path,
                "expected": expected_value,
                "actual": actual_obj[key],
            })


def _diff_seed_review(
    actual_card: dict[str, Any],
    expected_card: dict[str, Any],
    *,
    path: str,
    mismatches: list[dict[str, Any]],
    unverified: list[dict[str, Any]],
) -> None:
    review = expected_card.get("review")
    if not isinstance(review, dict) or not review:
        return
    if review.get("state") not in (None, ""):
        unverified.append({
            "path": f"{path}.review",
            "reason": "legacy state 形式由 seed 執行時鐘推導；要斷言請改用計數器形式 spec",
        })
        return

    unknown = sorted(set(review) - _REVIEW_COUNTER_KEYS)
    if unknown:
        mismatches.append({
            "kind": "invalid-spec",
            "path": f"{path}.review",
            "expected": sorted(_REVIEW_COUNTER_KEYS),
            "actual": unknown,
        })
        return
    actual_review = actual_card.get("review")
    if not isinstance(actual_review, dict):
        mismatches.append({
            "kind": "type-mismatch",
            "path": f"{path}.review",
            "expected": "object",
            "actual": type(actual_review).__name__,
        })
        return

    for key in sorted(review):
        expected_value = review[key]
        if key in _REVIEW_DT_KEYS:
            try:
                expected_value = _norm_dt(expected_value)
            except WorldExportError as exc:
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"{path}.review.{key}",
                    "expected": "ISO datetime",
                    "actual": str(exc),
                })
                continue
        elif (
            key == "review_interval_hours"
            and isinstance(expected_value, (int, float))
            and not isinstance(expected_value, bool)
        ):
            expected_value = float(expected_value)

        child_path = f"{path}.review.{key}"
        if key not in actual_review:
            mismatches.append({
                "kind": "missing-key",
                "path": child_path,
                "expected": expected_value,
                "actual": None,
            })
        elif actual_review[key] != expected_value:
            mismatches.append({
                "kind": "value-mismatch",
                "path": child_path,
                "expected": expected_value,
                "actual": actual_review[key],
            })


def _seed_entries(
    value: Any, *, path: str, mismatches: list[dict[str, Any]]
) -> list[Any]:
    if isinstance(value, list):
        return value
    mismatches.append({
        "kind": "invalid-spec",
        "path": path,
        "expected": "array",
        "actual": type(value).__name__,
    })
    return []


def diff_seed_spec(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Strictly compare exported account vocab with a ``kg.seed_spec.v1`` spec.

    A missing top-level entity array means that plane is intentionally not
    asserted. When an array is present, both directions are checked: declared
    entities must exist and actual entities absent from the declaration produce
    ``unexpected-*`` mismatches. This keeps hand-written partial specs useful
    without making an explicitly declared empty array silently pass.
    """
    mismatches: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    default_nb = _default_notebook_name(actual)

    if "notebooks" in expected:
        expected_notebooks = _seed_entries(
            expected["notebooks"], path="notebooks", mismatches=mismatches
        )
        actual_notebooks = {
            notebook["name"]: notebook
            for notebook in actual.get("notebooks", [])
            if isinstance(notebook, dict)
            and isinstance(notebook.get("name"), str)
            and notebook["name"]
        }
        expected_notebook_index: dict[str, dict[str, Any]] = {}
        expected_has_default = False
        for index, notebook in enumerate(expected_notebooks):
            if not isinstance(notebook, dict):
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"notebooks[{index}]",
                    "expected": "object",
                    "actual": notebook,
                })
                continue
            name = notebook.get("name")
            if not isinstance(name, str) or not name:
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"notebooks[{index}]",
                    "expected": "object with non-empty name",
                    "actual": notebook,
                })
                continue
            expected_notebook_index[name] = notebook
            expected_has_default = expected_has_default or bool(notebook.get("is_default"))

        for name, notebook in expected_notebook_index.items():
            path = f"notebooks[{name}]"
            if name not in actual_notebooks:
                mismatches.append({
                    "kind": "missing-notebook",
                    "path": path,
                    "expected": notebook,
                    "actual": None,
                })
                continue
            _diff_seed_fields(
                actual_notebooks[name], notebook, _SEED_NOTEBOOK_FIELDS,
                path=path, mismatches=mismatches,
            )

        if default_nb and not expected_has_default:
            unverified.append({
                "path": f"notebooks[{default_nb}]",
                "reason": "預設本由 NotebookStore.ensure_default 恆存在；spec 未宣告故不視為多餘",
            })
        for name in sorted(set(actual_notebooks) - set(expected_notebook_index)):
            if name == default_nb and not expected_has_default:
                continue
            mismatches.append({
                "kind": "unexpected-notebook",
                "path": f"notebooks[{name}]",
                "expected": None,
                "actual": actual_notebooks[name],
            })

    if "cards" in expected:
        expected_cards = _seed_entries(
            expected["cards"], path="cards", mismatches=mismatches
        )
        actual_cards = {
            key: card
            for card in actual.get("cards", [])
            if isinstance(card, dict)
            and (key := _seed_card_key(card, default_nb)) is not None
        }
        expected_card_index: dict[tuple[str, str], dict[str, Any]] = {}
        for index, card in enumerate(expected_cards):
            if not isinstance(card, dict):
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"cards[{index}]",
                    "expected": "object",
                    "actual": card,
                })
                continue
            key = _seed_card_key(card, default_nb)
            if key is None:
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"cards[{index}]",
                    "expected": "object with content and notebook identity",
                    "actual": card,
                })
                continue
            expected_card_index[key] = card

        for key, card in expected_card_index.items():
            path = f"cards[{key[0]}/{key[1]}]"
            actual_card = actual_cards.get(key)
            if actual_card is None:
                mismatches.append({
                    "kind": "missing-card",
                    "path": path,
                    "expected": card,
                    "actual": None,
                })
                continue
            _diff_seed_fields(
                actual_card, card, _SEED_CARD_FIELDS,
                path=path, mismatches=mismatches,
            )
            _diff_seed_review(
                actual_card, card, path=path,
                mismatches=mismatches, unverified=unverified,
            )

        for key in sorted(set(actual_cards) - set(expected_card_index)):
            mismatches.append({
                "kind": "unexpected-card",
                "path": f"cards[{key[0]}/{key[1]}]",
                "expected": None,
                "actual": actual_cards[key],
            })

    if "links" in expected:
        expected_links = _seed_entries(
            expected["links"], path="links", mismatches=mismatches
        )
        actual_links = {
            key: link
            for link in actual.get("links", [])
            if isinstance(link, dict)
            and (key := _seed_link_key(link, default_nb)) is not None
        }
        expected_link_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for index, link in enumerate(expected_links):
            if not isinstance(link, dict):
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"links[{index}]",
                    "expected": "object",
                    "actual": link,
                })
                continue
            key = _seed_link_key(link, default_nb)
            if key is None:
                mismatches.append({
                    "kind": "invalid-spec",
                    "path": f"links[{index}]",
                    "expected": "object with notebook/from/to/kind identity",
                    "actual": link,
                })
                continue
            expected_link_index[key] = link

        for key, link in expected_link_index.items():
            path = f"links[{key[0]}/{key[1]}->{key[2]}:{key[3]}]"
            actual_link = actual_links.get(key)
            if actual_link is None:
                mismatches.append({
                    "kind": "missing-link",
                    "path": path,
                    "expected": link,
                    "actual": None,
                })
                continue
            _diff_seed_fields(
                actual_link, link, _SEED_LINK_FIELDS,
                path=path, mismatches=mismatches,
            )

        for key in sorted(set(actual_links) - set(expected_link_index)):
            mismatches.append({
                "kind": "unexpected-link",
                "path": f"links[{key[0]}/{key[1]}->{key[2]}:{key[3]}]",
                "expected": None,
                "actual": actual_links[key],
            })

    return {
        "schema": DIFF_SCHEMA,
        "mode": "seed-spec",
        "expectedSchema": expected.get("schema"),
        "actualSchema": actual.get("schema"),
        "ok": not mismatches,
        "mismatchCount": len(mismatches),
        "mismatches": mismatches,
        "unverified": unverified,
    }
