"""Regression tests for resumable notebook deletion cleanup."""

from __future__ import annotations

from pathlib import Path

from kg.cards import CardStore
from kg.ops_shared import notebook_files


def _create_card_and_artifact(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers
    notebook_id = client.post(
        "/api/notebooks", json={"name": "Recovery"}, headers=headers
    ).json()["id"]
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    CardStore(user_dir / "cards.db").add(
        content="retry", meaning="重試", notebook_id=notebook_id
    )
    artifact = notebook_files(user_dir, notebook_id)["graph"]
    artifact.write_text("{}")
    return notebook_id, artifact


def _assert_delete_retry_converges(client, headers, notebook_id):
    first = client.delete(f"/api/notebooks/{notebook_id}", headers=headers)
    assert first.status_code == 500, first.text

    second = client.delete(f"/api/notebooks/{notebook_id}", headers=headers)
    assert second.status_code == 200, second.text

    third = client.delete(f"/api/notebooks/{notebook_id}", headers=headers)
    assert third.status_code == 200, third.text
    assert third.json()["cardsDeleted"] == 0


def _assert_no_active_cards(isolated_api, notebook_id):
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    assert CardStore(user_dir / "cards.db").count(notebook_id=notebook_id) == 0


def test_delete_retry_resumes_after_cards_cleanup_failure(isolated_api, monkeypatch):
    notebook_id, artifact = _create_card_and_artifact(isolated_api)
    client = isolated_api.client
    headers = isolated_api.headers

    original = CardStore.soft_delete_by_notebook
    calls = 0

    def fail_once(self, card_notebook_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected cards cleanup failure")
        return original(self, card_notebook_id)

    monkeypatch.setattr(CardStore, "soft_delete_by_notebook", fail_once)

    _assert_delete_retry_converges(client, headers, notebook_id)

    assert calls == 3
    assert not artifact.exists()
    _assert_no_active_cards(isolated_api, notebook_id)


def test_delete_retry_resumes_after_artifact_cleanup_failure(isolated_api, monkeypatch):
    notebook_id, artifact = _create_card_and_artifact(isolated_api)
    client = isolated_api.client
    headers = isolated_api.headers

    original = Path.unlink
    calls = 0

    def fail_once(path, *args, **kwargs):
        nonlocal calls
        if path == artifact and calls == 0:
            calls += 1
            raise OSError("injected artifact cleanup failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)

    _assert_delete_retry_converges(client, headers, notebook_id)

    assert calls == 1
    assert not artifact.exists()
    _assert_no_active_cards(isolated_api, notebook_id)
