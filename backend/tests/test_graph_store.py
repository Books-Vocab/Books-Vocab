from __future__ import annotations

import json
import logging
from pathlib import Path

from kg.graph.models import LinkKind
from kg.graph.store import GraphStore


def test_malformed_link_rows_are_skipped_and_valid_rows_survive(
    tmp_path: Path, caplog
) -> None:
    links_path = tmp_path / "links.json"
    candidates_path = tmp_path / "candidates.json"
    valid = {
        "id": "link-1",
        "from_id": "a",
        "to_id": "b",
        "kind": LinkKind.SHARES_USAGE.value,
        "confidence": 0.8,
        "reason": "related",
        "created_at": "2026-01-01T00:00:00Z",
        "status": "active",
    }
    links_path.write_text(json.dumps([None, valid]), encoding="utf-8")
    candidates_path.write_text("[]", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="kg.graph.store"):
        store = GraphStore(links_path, candidates_path)

    assert set(store._links) == {"link-1"}
    assert "malformed" in caplog.text
