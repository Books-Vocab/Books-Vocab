from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import make_jwt
from kg.cards import CardStore
from kg.exceptions import ConflictError, NotFoundError
from kg.graph import GraphStore, LinkKind
from test_dictionary_phase2a import _entry, _save_sidecar


def _service(cards: CardStore, graph: GraphStore, *, crash_hook=None):
    from kg.dictionary_cards import DictionaryCardService

    return DictionaryCardService(
        cards=cards,
        graph=graph,
        lexical=None,
        judge=None,
        crash_hook=crash_hook,
    )


def _dictionary_card(
    cards: CardStore,
    *,
    notebook_id: str = "default",
    word: str = "invoke",
    source: str | None = None,
):
    card = cards.add(
        word,
        "援引",
        notebook_id=notebook_id,
        source=source,
        card_role="dictionary",
        review_eligible=False,
    )
    _save_sidecar(cards, card.id, _entry(word))
    return card


def test_dictionary_archive_round_trip_is_idempotent_and_projects_graph_state(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    source_json = '{"bookId":"book-1","context":"chapter"}'
    source = cards.add("summon", "召喚", notebook_id="default")
    target = _dictionary_card(cards, source=source_json)
    link = graph.add_link(
        source.id, target.id, LinkKind.SHARES_USAGE, 1.0, "dictionary link"
    )
    watermark = target.updated_at

    archived = service.set_archived(
        target.id, notebook_id="default", archived=True
    )

    assert archived.id == target.id
    assert archived.is_archived is True
    assert archived.updated_at > watermark
    assert cards.get_dictionary_entry(target.id) is not None
    assert cards.get(target.id).source == source_json
    assert graph.get_link(link.id).status == "deprecated"
    delta = service.list_projection(
        notebook_id="default", limit=10, since=watermark
    )
    projected = next(item for item in delta.items if item.card.id == target.id)
    assert projected.card.is_archived is True
    assert projected.links == []

    first_updated_at = archived.updated_at
    replay = service.set_archived(target.id, notebook_id="default", archived=True)
    assert replay.is_archived is True
    assert replay.updated_at == first_updated_at

    restored = service.set_archived(
        target.id, notebook_id="default", archived=False
    )
    assert restored.is_archived is False
    assert restored.updated_at > first_updated_at
    assert graph.find_link_between(source.id, target.id).status == "active"
    restored_projection = service.list_projection(
        notebook_id="default", limit=10, since=first_updated_at
    )
    restored_item = next(
        item for item in restored_projection.items if item.card.id == target.id
    )
    assert [item.id for item in restored_item.links] == [link.id]


def test_dictionary_soft_delete_is_idempotent_tombstone_and_keeps_sidecar_source(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        tmp_path / "blocked.json",
    )
    service = _service(cards, graph)
    source_json = '{"bookId":"book-2"}'
    source = cards.add("summon", "召喚", notebook_id="default")
    target = _dictionary_card(cards, source=source_json)
    link = graph.add_link(
        source.id, target.id, LinkKind.SHARES_USAGE, 1.0, "dictionary link"
    )
    blocked_link = graph.add_link(
        target.id, "blocked-card", LinkKind.CONTRASTS_WITH, 1.0, "blocked"
    )
    graph.hard_delete_link(blocked_link.id)
    watermark = target.updated_at

    deleted = service.soft_delete(target.id, notebook_id="default")

    assert deleted.is_deleted is True
    assert deleted.updated_at > watermark
    assert cards.get_dictionary_entry(target.id) is not None
    assert cards.get(target.id).source == source_json
    assert graph.get_link(link.id).status == "deprecated"
    assert graph.is_blocked(target.id, "blocked-card") is False
    delta = service.list_projection(
        notebook_id="default", limit=10, since=watermark
    )
    projected = next(item for item in delta.items if item.card.id == target.id)
    assert projected.card.is_deleted is True
    assert projected.links == []

    first_updated_at = deleted.updated_at
    replay = service.soft_delete(target.id, notebook_id="default")
    assert replay.is_deleted is True
    assert replay.updated_at == first_updated_at


def test_dictionary_lifecycle_rejects_cross_notebook_learning_role_and_active_promotion(
    tmp_path,
):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    target = _dictionary_card(cards)

    with pytest.raises(NotFoundError):
        service.set_archived(target.id, notebook_id="other", archived=True)
    with pytest.raises(NotFoundError):
        service.soft_delete(target.id, notebook_id="other")

    cards.update(target.id, promotion_state="running")
    with pytest.raises(ConflictError, match="promotion"):
        service.set_archived(target.id, notebook_id="default", archived=True)
    with pytest.raises(ConflictError, match="promotion"):
        service.soft_delete(target.id, notebook_id="default")

    cards.update(target.id, promotion_state="idle", card_role="learning")
    with pytest.raises(ConflictError, match="learning"):
        service.set_archived(target.id, notebook_id="default", archived=True)
    with pytest.raises(ConflictError, match="learning"):
        service.soft_delete(target.id, notebook_id="default")


def test_archived_dictionary_card_cannot_start_promotion(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    target = _dictionary_card(cards)
    service.set_archived(target.id, notebook_id="default", archived=True)

    with pytest.raises(ConflictError, match="Archived"):
        cards.enqueue_dictionary_promotion(target.id)


@pytest.mark.parametrize("operation", ["archive", "delete"])
def test_dictionary_lifecycle_rolls_back_card_when_graph_cleanup_fails(
    tmp_path, monkeypatch, operation
):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    target = _dictionary_card(cards)

    def fail_cleanup(*_args, **_kwargs):
        raise OSError("graph write failed")

    monkeypatch.setattr(graph, "apply_card_lifecycle", fail_cleanup)
    with pytest.raises(OSError, match="graph write failed"):
        if operation == "archive":
            service.set_archived(target.id, notebook_id="default", archived=True)
        else:
            service.soft_delete(target.id, notebook_id="default")

    current = cards.get(target.id)
    assert current.is_archived is False
    assert current.is_deleted is False
    assert cards.dictionary_archive_link_ids(target.id) == set()


@pytest.mark.parametrize(
    ("operation", "failing_flush"),
    [("archive", "_flush_candidates"), ("delete", "_flush_pending_judge")],
)
def test_graph_partial_write_failure_restores_exact_lifecycle_snapshot(
    tmp_path, monkeypatch, operation, failing_flush
):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        tmp_path / "blocked.json",
        tmp_path / "pending.json",
    )
    service = _service(cards, graph)
    target = _dictionary_card(cards)
    active_peer = cards.add("active-peer", "作用中", notebook_id="default")
    old_peer = cards.add("old-peer", "歷史", notebook_id="default")
    active = graph.add_link(
        target.id, active_peer.id, LinkKind.SHARES_USAGE, 1.0, "active"
    )
    pre_deprecated = graph.add_link(
        target.id, old_peer.id, LinkKind.CONTRASTS_WITH, 1.0, "old"
    )
    graph.deprecate_links_for(old_peer.id)
    graph.add_candidate(target.id, "candidate-peer", 0.8)
    graph.add_pending_judge(target.id)
    blocked = graph.add_link(
        target.id, "blocked-peer", LinkKind.CONTRASTS_WITH, 1.0, "blocked"
    )
    graph.hard_delete_link(blocked.id)

    original_flush = getattr(graph, failing_flush)
    calls = 0

    def fail_once(snapshot):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected graph flush failure")
        return original_flush(snapshot)

    monkeypatch.setattr(graph, failing_flush, fail_once)
    with pytest.raises(OSError, match="injected graph flush failure"):
        if operation == "archive":
            service.set_archived(target.id, notebook_id="default", archived=True)
        else:
            service.soft_delete(target.id, notebook_id="default")

    current = cards.get(target.id)
    assert current.is_archived is False
    assert current.is_deleted is False
    assert graph.get_link(active.id).status == "active"
    assert graph.get_link(pre_deprecated.id).status == "deprecated"
    assert graph.candidate_count() == 2  # one candidate + one pending judge
    assert graph.is_blocked(target.id, "blocked-peer") is True

    assert len(json.loads((tmp_path / "candidates.json").read_text())) == 1
    assert target.id in json.loads((tmp_path / "pending.json").read_text())
    reloaded = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        tmp_path / "blocked.json",
        tmp_path / "pending.json",
    )
    assert reloaded.get_link(active.id).status == "active"
    assert reloaded.get_link(pre_deprecated.id).status == "deprecated"
    # GraphStore's legacy-load migration folds candidate rows into pending on restart.
    assert reloaded.candidate_count() == 1
    assert reloaded.is_blocked(target.id, "blocked-peer") is True


def test_unarchive_restores_only_links_deprecated_by_that_archive(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    target = _dictionary_card(cards)
    active_peer = cards.add("active-peer", "作用中", notebook_id="default")
    old_peer = cards.add("old-peer", "歷史", notebook_id="default")
    lifecycle_link = graph.add_link(
        target.id, active_peer.id, LinkKind.SHARES_USAGE, 1.0, "active"
    )
    historical_link = graph.add_link(
        target.id, old_peer.id, LinkKind.CONTRASTS_WITH, 1.0, "historical"
    )
    graph.deprecate_links_for(old_peer.id)

    service.set_archived(target.id, notebook_id="default", archived=True)
    service.set_archived(target.id, notebook_id="default", archived=False)

    assert graph.get_link(lifecycle_link.id).status == "active"
    assert graph.get_link(historical_link.id).status == "deprecated"


@pytest.mark.parametrize("unarchive_order", [("a", "b"), ("b", "a")])
def test_link_restores_only_after_final_archived_endpoint_clears(
    tmp_path, unarchive_order
):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    a = _dictionary_card(cards, word="invoke")
    b = _dictionary_card(cards, word="trigger")
    lifecycle_link = graph.add_link(
        a.id, b.id, LinkKind.SHARES_USAGE, 1.0, "both dictionary endpoints"
    )

    service.set_archived(a.id, notebook_id="default", archived=True)
    service.set_archived(b.id, notebook_id="default", archived=True)
    assert graph.get_link(lifecycle_link.id).status == "deprecated"

    by_name = {"a": a, "b": b}
    first, final = (by_name[name] for name in unarchive_order)
    service.set_archived(first.id, notebook_id="default", archived=False)
    assert graph.get_link(lifecycle_link.id).status == "deprecated"

    service.set_archived(final.id, notebook_id="default", archived=False)
    assert graph.get_link(lifecycle_link.id).status == "active"


def test_failed_unarchive_restores_archive_cause_before_retry(tmp_path, monkeypatch):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = _service(cards, graph)
    target = _dictionary_card(cards)
    peer = cards.add("peer", "同伴", notebook_id="default")
    link = graph.add_link(target.id, peer.id, LinkKind.SHARES_USAGE, 1.0, "active")
    service.set_archived(target.id, notebook_id="default", archived=True)

    original_apply = graph.apply_card_lifecycle

    def fail_once(*_args, **_kwargs):
        monkeypatch.setattr(graph, "apply_card_lifecycle", original_apply)
        raise OSError("unarchive graph failed")

    monkeypatch.setattr(graph, "apply_card_lifecycle", fail_once)
    with pytest.raises(OSError, match="unarchive graph failed"):
        service.set_archived(target.id, notebook_id="default", archived=False)

    assert cards.get(target.id).is_archived is True
    assert cards.dictionary_archive_link_ids(target.id) == {link.id}
    service.set_archived(target.id, notebook_id="default", archived=False)
    assert graph.get_link(link.id).status == "active"


class _SimulatedCrash(BaseException):
    pass


def test_same_state_retry_reconciles_crash_after_card_commit(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    target = _dictionary_card(cards)
    peer = cards.add("peer", "同伴", notebook_id="default")
    link = graph.add_link(target.id, peer.id, LinkKind.SHARES_USAGE, 1.0, "active")

    def crash(step):
        if step == "after_lifecycle_card_commit":
            raise _SimulatedCrash

    crashing = _service(cards, graph, crash_hook=crash)
    with pytest.raises(_SimulatedCrash):
        crashing.set_archived(target.id, notebook_id="default", archived=True)

    committed_at = cards.get(target.id).updated_at
    assert cards.get(target.id).is_archived is True
    assert graph.get_link(link.id).status == "active"

    reconciled = _service(cards, graph).set_archived(
        target.id, notebook_id="default", archived=True
    )
    assert reconciled.updated_at == committed_at
    assert graph.get_link(link.id).status == "deprecated"


def test_same_state_retry_repairs_partial_graph_write_after_crash(tmp_path, monkeypatch):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        pending_judge_path=tmp_path / "pending.json",
    )
    target = _dictionary_card(cards)
    peer = cards.add("peer", "同伴", notebook_id="default")
    link = graph.add_link(target.id, peer.id, LinkKind.SHARES_USAGE, 1.0, "active")
    graph.add_candidate(target.id, "candidate-peer", 0.8)
    graph.add_pending_judge(target.id)
    original_flush = graph._flush_candidates

    def crash_during_candidates(_snapshot):
        monkeypatch.setattr(graph, "_flush_candidates", original_flush)
        raise _SimulatedCrash

    monkeypatch.setattr(graph, "_flush_candidates", crash_during_candidates)
    with pytest.raises(_SimulatedCrash):
        _service(cards, graph).set_archived(
            target.id, notebook_id="default", archived=True
        )

    assert cards.get(target.id).is_archived is True
    assert graph.get_link(link.id).status == "deprecated"

    reloaded_graph = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        pending_judge_path=tmp_path / "pending.json",
    )
    _service(cards, reloaded_graph).set_archived(
        target.id, notebook_id="default", archived=True
    )
    assert reloaded_graph.get_link(link.id).status == "deprecated"
    assert reloaded_graph.candidate_count() == 0


@pytest.mark.parametrize("operation", ["archive", "delete"])
def test_lifecycle_and_promotion_enqueue_are_atomic_competitors(tmp_path, operation):
    seed = CardStore(tmp_path / "cards.db")
    target = _dictionary_card(seed)
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    lifecycle_cards = CardStore(tmp_path / "cards.db")
    promotion_cards = CardStore(tmp_path / "cards.db")
    service = _service(lifecycle_cards, graph)
    barrier = threading.Barrier(2)

    def lifecycle():
        barrier.wait()
        if operation == "archive":
            service.set_archived(target.id, notebook_id="default", archived=True)
        else:
            service.soft_delete(target.id, notebook_id="default")
        return "lifecycle"

    def promotion():
        barrier.wait()
        promotion_cards.enqueue_dictionary_promotion(target.id)
        return "promotion"

    def outcome(callable_):
        try:
            return callable_()
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(outcome, [lifecycle, promotion]))

    assert sorted(results) in (["conflict", "lifecycle"], ["conflict", "promotion"])
    current = seed.get(target.id)
    if results[0] == "lifecycle":
        assert current.promotion_state == "idle"
        assert current.is_archived is (operation == "archive")
        assert current.is_deleted is (operation == "delete")
    else:
        assert current.promotion_state == "queued"
        assert current.is_archived is False
        assert current.is_deleted is False


def test_dictionary_lifecycle_api_contract_auth_ownership_and_notebook_scope(isolated_api):
    import kg.routers.dictionary as dictionary_router

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    cards = dictionary_router._card_store(user_dir)
    target = _dictionary_card(cards)
    archive_url = f"/api/dictionary/cards/{target.id}/archive"
    delete_url = f"/api/dictionary/cards/{target.id}"

    unauthenticated = isolated_api.client.patch(
        archive_url, json={"archived": True, "notebookId": "default"}
    )
    assert unauthenticated.status_code == 401

    cross_notebook = isolated_api.client.patch(
        archive_url,
        headers=isolated_api.headers,
        json={"archived": True, "notebookId": "other"},
    )
    assert cross_notebook.status_code in {403, 404}

    other_user = isolated_api.client.delete(
        delete_url,
        headers={"Authorization": f"Bearer {make_jwt('other_user')}"},
        params={"notebook_id": "default"},
    )
    assert other_user.status_code == 404

    archived = isolated_api.client.patch(
        archive_url,
        headers=isolated_api.headers,
        json={"archived": True, "notebookId": "default"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["id"] == target.id
    assert archived.json()["notebookId"] == "default"
    assert archived.json()["cardRole"] == "dictionary"
    assert archived.json()["isArchived"] is True
    assert "updatedAt" in archived.json()
    assert "notebook_id" not in archived.json()

    deleted = isolated_api.client.delete(
        delete_url,
        headers=isolated_api.headers,
        params={"notebook_id": "default"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["isDeleted"] is True
    replay = isolated_api.client.delete(
        delete_url,
        headers=isolated_api.headers,
        params={"notebook_id": "default"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == deleted.json()


def test_dictionary_lifecycle_api_rejects_promoted_learning_card(isolated_api):
    import kg.routers.dictionary as dictionary_router

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    cards = dictionary_router._card_store(user_dir)
    target = _dictionary_card(cards)
    cards.update(target.id, card_role="learning", review_eligible=True)

    archived = isolated_api.client.patch(
        f"/api/dictionary/cards/{target.id}/archive",
        headers=isolated_api.headers,
        json={"archived": True, "notebookId": "default"},
    )
    deleted = isolated_api.client.delete(
        f"/api/dictionary/cards/{target.id}",
        headers=isolated_api.headers,
        params={"notebook_id": "default"},
    )

    assert archived.status_code == 409
    assert "learning" in archived.json()["detail"]
    assert deleted.status_code == 409
    assert "learning" in deleted.json()["detail"]
