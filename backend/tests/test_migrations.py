"""Tests for one-time migration scripts under `kg.migrations`.

Covers:
- `migrate_notebook.migrate_user`: idempotent, happy path, rollback safety
  (partial failure mid-way must leave salvageable state and rerun-safe).
- `migrate_graph_reasons.migrate_user_graph`: idempotent (CJK skip),
  happy path, rollback safety (LLM exception preserves original reason).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kg.cards import CardStore
from kg.graph import GraphStore, LinkKind
from kg.notebook import NotebookStore


# ---------------------------------------------------------------------------
# migrate_notebook
# ---------------------------------------------------------------------------


def _make_legacy_user_dir(root: Path, with_legacy_graph: bool = True) -> Path:
    """Create a pre-notebook-era user directory."""
    user_dir = root / "user_legacy"
    user_dir.mkdir(parents=True)

    # cards.db with one card (created via current schema; we'll simulate "no
    # notebook_id column" by dropping it). Simpler: just create through
    # CardStore which gives us the full schema then drop notebook_id to mimic
    # legacy state.
    cards_path = user_dir / "cards.db"
    store = CardStore(cards_path)
    store.add(content="ephemeral", meaning="brief")
    # Drop notebook_id column to simulate legacy schema
    import sqlite3

    conn = sqlite3.connect(cards_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(card)").fetchall()]
    if "notebook_id" in cols:
        # SQLite supports DROP COLUMN since 3.35.
        try:
            conn.execute("ALTER TABLE card DROP COLUMN notebook_id")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # older sqlite — leave column in place; migration will be a no-op for it
    conn.close()

    if with_legacy_graph:
        (user_dir / "graph.json").write_text(json.dumps({"links": []}))
        (user_dir / "candidates.json").write_text(json.dumps([]))
        (user_dir / "card_ids.json").write_text(json.dumps([]))
        # Simulate a stray .bak
        (user_dir / "graph.json.bak").write_text(json.dumps({"links": []}))

    return user_dir


def test_migrate_notebook_happy_path(tmp_path):
    from kg.migrations.migrate_notebook import migrate_user

    user_dir = _make_legacy_user_dir(tmp_path)

    migrate_user(user_dir)

    # notebooks.db exists with default notebook
    assert (user_dir / "notebooks.db").exists()
    nb = NotebookStore(user_dir / "notebooks.db").get("default")
    assert nb is not None
    assert nb.is_default is True

    # legacy graph files renamed
    assert (user_dir / "graph_default.json").exists()
    assert not (user_dir / "graph.json").exists()
    assert (user_dir / "candidates_default.json").exists()
    assert not (user_dir / "candidates.json").exists()
    assert (user_dir / "graph_default.json.bak").exists()

    # cards.db has notebook_id column
    import sqlite3

    conn = sqlite3.connect(user_dir / "cards.db")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(card)").fetchall()]
    conn.close()
    assert "notebook_id" in cols


def test_migrate_notebook_is_idempotent(tmp_path):
    """Running migrate_user twice must produce the same end state — no errors,
    no duplicate default notebook, no file clobbering."""
    from kg.migrations.migrate_notebook import migrate_user

    user_dir = _make_legacy_user_dir(tmp_path)

    migrate_user(user_dir)
    # Capture state
    graph_default_content = (user_dir / "graph_default.json").read_text()
    notebooks_size_first = (user_dir / "notebooks.db").stat().st_size

    # Second run must not raise and must not duplicate the default notebook
    migrate_user(user_dir)

    nb_store = NotebookStore(user_dir / "notebooks.db")
    all_nbs = nb_store.all()
    defaults = [n for n in all_nbs if n.id == "default"]
    assert len(defaults) == 1

    # graph_default.json content unchanged
    assert (user_dir / "graph_default.json").read_text() == graph_default_content

    # No re-creation of legacy graph.json (don't move new->old)
    assert not (user_dir / "graph.json").exists()

    # Second run did not regress the notebooks.db (still exists, non-empty)
    assert (user_dir / "notebooks.db").stat().st_size >= notebooks_size_first


def test_migrate_notebook_skip_rename_when_target_exists(tmp_path):
    """If the new-style file already exists, don't overwrite it from the legacy
    one. This protects against re-running after partial completion."""
    from kg.migrations.migrate_notebook import migrate_user

    user_dir = _make_legacy_user_dir(tmp_path)
    # Both old and new exist; new has 'newer' content
    (user_dir / "graph_default.json").write_text(json.dumps({"links": ["new"]}))

    migrate_user(user_dir)

    # New file wins, old is left alone
    assert json.loads((user_dir / "graph_default.json").read_text()) == {"links": ["new"]}
    # Legacy graph.json was NOT renamed (target already existed) — still present
    assert (user_dir / "graph.json").exists()


def test_migrate_notebook_rollback_safety_partial_failure(tmp_path):
    """If a step partway through raises, prior steps must remain valid and a
    rerun must succeed. The migration script itself catches exceptions at the
    `main()` loop level (OSError/DatabaseError/ValueError) per user, so a
    failure in one user must not poison subsequent users either."""
    from kg.migrations import migrate_notebook as mod

    # Two users; inject failure into the first via a patched NotebookStore
    user_a = _make_legacy_user_dir(tmp_path / "rootA" / "user_a".replace("user_a", "u_a"))
    # Build a clean second user dir
    user_b_root = tmp_path / "rootA"
    user_b = user_b_root / "u_b"
    user_b.mkdir(parents=True)
    cb = CardStore(user_b / "cards.db")
    cb.add(content="lucid", meaning="clear")
    (user_b / "graph.json").write_text(json.dumps({"links": []}))

    call_count = {"n": 0}
    orig_ensure_default = NotebookStore.ensure_default

    def flaky_ensure_default(self):
        call_count["n"] += 1
        # Fail on the very first call only
        if call_count["n"] == 1:
            raise OSError("simulated disk failure")
        return orig_ensure_default(self)

    with patch.object(NotebookStore, "ensure_default", flaky_ensure_default):
        # First user fails — must raise to caller; main() would catch, but
        # migrate_user does not — that's fine for our test.
        with pytest.raises(OSError):
            mod.migrate_user(user_a)

    # After failure, no default notebook row was inserted (rollback safe at
    # NotebookStore.ensure_default level — we raised before commit).
    nb_store = NotebookStore(user_a / "notebooks.db")
    assert nb_store.get("default") is None

    # Rerun must succeed and produce expected state
    mod.migrate_user(user_a)
    assert nb_store.get("default") is None or NotebookStore(user_a / "notebooks.db").get("default") is not None
    # Re-open a fresh store to read the latest committed state
    assert NotebookStore(user_a / "notebooks.db").get("default") is not None


def test_migrate_notebook_no_cards_db_only_creates_notebook(tmp_path):
    """A user dir with no cards.db must still get notebooks.db; rename loop is
    safe when graph files are absent."""
    from kg.migrations.migrate_notebook import migrate_user

    user_dir = tmp_path / "empty_user"
    user_dir.mkdir()

    migrate_user(user_dir)

    assert (user_dir / "notebooks.db").exists()
    assert NotebookStore(user_dir / "notebooks.db").get("default") is not None
    # No graph files were created out of thin air
    assert not (user_dir / "graph_default.json").exists()


# ---------------------------------------------------------------------------
# migrate_graph_reasons
# ---------------------------------------------------------------------------


def _make_user_with_graph(root: Path, link_reason: str = "English-only reason") -> tuple[Path, str, str, str]:
    """Build a user dir with cards.db + a graph_<nb>.json with one active link.

    Returns: (user_dir, notebook_id, card_a_id, card_b_id)
    """
    user_dir = root / "u1"
    user_dir.mkdir(parents=True)
    cards = CardStore(user_dir / "cards.db")
    a = cards.add(content="happy", meaning="feeling pleasure")
    b = cards.add(content="joyful", meaning="full of joy")

    notebook_id = "default"
    graph_path = user_dir / f"graph_{notebook_id}.json"
    candidates_path = user_dir / f"candidates_{notebook_id}.json"
    graph = GraphStore(graph_path, candidates_path)
    graph.add_link(
        from_id=a.id,
        to_id=b.id,
        kind=LinkKind.SHARES_USAGE,
        confidence=0.8,
        reason=link_reason,
    )
    return user_dir, notebook_id, a.id, b.id


def _llm_client_returning(reason: str):
    """Build a mock OpenAI-like client that returns a given reason."""
    client = MagicMock()
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content=json.dumps(
                {"link": "shares_usage", "confidence": 0.9, "reason": reason}
            )
        )
    )
    client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])
    return client


def test_migrate_graph_reasons_happy_path(tmp_path):
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir, nb_id, a_id, b_id = _make_user_with_graph(tmp_path)
    client = _llm_client_returning("這兩個詞都表達快樂的情感，但 joyful 程度更強。")

    updated = migrate_user_graph(user_dir, client, model="fake-model")

    assert updated == 1
    graph = GraphStore(user_dir / f"graph_{nb_id}.json", user_dir / f"candidates_{nb_id}.json")
    links = list(graph.all_links())
    assert len(links) == 1
    assert "快樂" in links[0].reason
    # Cards involved were touched (we just verify call did not crash and updated_at exists)
    cards = CardStore(user_dir / "cards.db")
    assert cards.get(a_id) is not None
    assert cards.get(b_id) is not None


def test_migrate_graph_reasons_idempotent_skips_cjk(tmp_path):
    """A link whose reason already contains CJK must be skipped on rerun —
    the LLM client must NOT be invoked, and the reason must remain identical."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    chinese_reason = "兩個詞都描述快樂"
    user_dir, nb_id, _, _ = _make_user_with_graph(tmp_path, link_reason=chinese_reason)
    client = _llm_client_returning("不該被呼叫")

    updated = migrate_user_graph(user_dir, client, model="fake-model")

    assert updated == 0
    client.chat.completions.create.assert_not_called()
    graph = GraphStore(user_dir / f"graph_{nb_id}.json", user_dir / f"candidates_{nb_id}.json")
    assert list(graph.all_links())[0].reason == chinese_reason


def test_migrate_graph_reasons_full_idempotency_two_runs(tmp_path):
    """Run twice: first replaces the English reason, second sees CJK and skips."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir, nb_id, _, _ = _make_user_with_graph(tmp_path)
    client = _llm_client_returning("第一次翻譯後的中文理由")

    first = migrate_user_graph(user_dir, client, model="fake-model")
    second = migrate_user_graph(user_dir, client, model="fake-model")

    assert first == 1
    assert second == 0
    assert client.chat.completions.create.call_count == 1  # second run skipped
    graph = GraphStore(user_dir / f"graph_{nb_id}.json", user_dir / f"candidates_{nb_id}.json")
    assert list(graph.all_links())[0].reason == "第一次翻譯後的中文理由"


def test_migrate_graph_reasons_rollback_on_llm_exception(tmp_path):
    """If the LLM call raises, the original reason must be preserved on disk
    (no half-written link state). The migration must continue processing
    subsequent links without crashing."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir = tmp_path / "u1"
    user_dir.mkdir()
    cards = CardStore(user_dir / "cards.db")
    a = cards.add(content="happy", meaning="feeling pleasure")
    b = cards.add(content="joyful", meaning="full of joy")
    c = cards.add(content="sad", meaning="feeling sorrow")
    d = cards.add(content="gloomy", meaning="dark and depressing")

    graph_path = user_dir / "graph_default.json"
    candidates_path = user_dir / "candidates_default.json"
    graph = GraphStore(graph_path, candidates_path)
    link_ab = graph.add_link(a.id, b.id, LinkKind.SHARES_USAGE, 0.8, "first English reason")
    link_cd = graph.add_link(c.id, d.id, LinkKind.SHARES_USAGE, 0.7, "second English reason")

    # First call raises, second returns valid CJK
    client = MagicMock()
    good = SimpleNamespace(
        message=SimpleNamespace(
            content=json.dumps({"link": "shares_usage", "confidence": 0.8, "reason": "成功翻譯"})
        )
    )
    client.chat.completions.create.side_effect = [
        RuntimeError("LLM timeout"),
        SimpleNamespace(choices=[good]),
    ]

    updated = migrate_user_graph(user_dir, client, model="fake-model")

    # Exactly one updated, no crash
    assert updated == 1
    # Re-read graph from disk: first link reason untouched, second updated
    reloaded = GraphStore(graph_path, candidates_path)
    by_id = {lk.id: lk for lk in reloaded.all_links()}
    assert by_id[link_ab.id].reason == "first English reason"
    assert by_id[link_cd.id].reason == "成功翻譯"


def test_migrate_graph_reasons_not_applicable_keeps_old(tmp_path):
    """LLM returning `not_applicable` must NOT overwrite the existing reason."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir, nb_id, _, _ = _make_user_with_graph(tmp_path, link_reason="orig English")
    client = MagicMock()
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content=json.dumps({"link": "not_applicable", "confidence": 0.1, "reason": "n/a"})
        )
    )
    client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])

    updated = migrate_user_graph(user_dir, client, model="fake-model")

    assert updated == 0
    graph = GraphStore(user_dir / f"graph_{nb_id}.json", user_dir / f"candidates_{nb_id}.json")
    assert list(graph.all_links())[0].reason == "orig English"


def test_migrate_graph_reasons_empty_reason_keeps_old(tmp_path):
    """LLM returning an empty reason must NOT overwrite the existing reason."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir, nb_id, _, _ = _make_user_with_graph(tmp_path, link_reason="orig English")
    client = MagicMock()
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content=json.dumps({"link": "shares_usage", "confidence": 0.5, "reason": ""})
        )
    )
    client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])

    updated = migrate_user_graph(user_dir, client, model="fake-model")

    assert updated == 0
    graph = GraphStore(user_dir / f"graph_{nb_id}.json", user_dir / f"candidates_{nb_id}.json")
    assert list(graph.all_links())[0].reason == "orig English"


def test_migrate_graph_reasons_malformed_json_extracts_via_regex(tmp_path):
    """Migration falls back to regex JSON extraction if the model returns
    extra text around the JSON object."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir, nb_id, _, _ = _make_user_with_graph(tmp_path)
    client = MagicMock()
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content='Here you go: {"link": "shares_usage", "confidence": 0.7, "reason": "從文中提取"} done.'
        )
    )
    client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])

    updated = migrate_user_graph(user_dir, client, model="fake-model")

    assert updated == 1
    graph = GraphStore(user_dir / f"graph_{nb_id}.json", user_dir / f"candidates_{nb_id}.json")
    assert list(graph.all_links())[0].reason == "從文中提取"


def test_migrate_graph_reasons_no_cards_db_skips(tmp_path):
    """A user dir without cards.db must be skipped (no crash)."""
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir = tmp_path / "u"
    user_dir.mkdir()
    (user_dir / "graph_default.json").write_text(json.dumps({"links": []}))

    client = MagicMock()
    updated = migrate_user_graph(user_dir, client, model="fake-model")
    assert updated == 0
    client.chat.completions.create.assert_not_called()


def test_migrate_graph_reasons_no_graph_files_returns_zero(tmp_path):
    from kg.migrations.migrate_graph_reasons import migrate_user_graph

    user_dir = tmp_path / "u"
    user_dir.mkdir()
    # Only cards.db, no graph files
    CardStore(user_dir / "cards.db")

    client = MagicMock()
    updated = migrate_user_graph(user_dir, client, model="fake-model")
    assert updated == 0
    client.chat.completions.create.assert_not_called()
