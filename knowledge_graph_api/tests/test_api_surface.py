from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
from kg.api import app
from kg.graph import LinkKind

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=timezone.utc),
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture()
def isolated_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    lock_file = data_dir / "users.json.lock"
    users_file.write_text(
        json.dumps(
            {
                user_id: {"config": {}},
                "other_user": {
                    "config": {"mochi_api_key": "mk_live"},
                    "provider": "google",
                    "email": "other@example.com",
                },
            }
        )
    )

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch.object(api_mod, "DATA_DIR", data_dir),
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
    ):
        api_mod._USER_LOCKS.clear()
        api_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
            users_file=users_file,
        )


class _DummyEmbeddingStore:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    def has(self, card_id: str) -> bool:
        return card_id in self._ids

    def add(self, card_id: str, text: str) -> None:
        self._ids.add(card_id)

    def find_similar(self, card_id: str, k: int = 3):
        return []


def test_vocab_lifecycle_and_since_sync(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers
    emb = _DummyEmbeddingStore()

    entries = [
        {"word": "evoke", "translation": "喚起", "context": "The story can evoke deep memories."},
        {"word": "lucid", "translation": "清晰的", "context": "Her explanation was lucid and direct."},
    ]
    with patch.object(api_mod, "_embedding_store", return_value=emb):
        r = client.post("/api/vocab", json=entries, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        assert body["skipped"] == 0
        assert set(body["cardIds"].keys()) == {"evoke", "lucid"}

        r_dup = client.post("/api/vocab", json=[entries[0]], headers=headers)
        assert r_dup.status_code == 200, r_dup.text
        assert r_dup.json()["created"] == 0
        assert r_dup.json()["skipped"] == 1
        assert "evoke" in r_dup.json()["duplicates"]

    r_all = client.get("/api/vocab", headers=headers)
    assert r_all.status_code == 200, r_all.text
    words = {c["content"] for c in r_all.json()}
    assert words == {"evoke", "lucid"}

    r_bad_since = client.get("/api/vocab", params={"since": "not-a-timestamp"}, headers=headers)
    assert r_bad_since.status_code == 400

    since = (datetime.now(tz=timezone.utc) - timedelta(seconds=1)).isoformat()
    r_delete = client.delete("/api/vocab/evoke", headers=headers)
    assert r_delete.status_code == 200, r_delete.text

    r_since = client.get("/api/vocab", params={"since": since}, headers=headers)
    assert r_since.status_code == 200, r_since.text
    changed = r_since.json()
    assert any(c["content"] == "evoke" and c["isDeleted"] for c in changed)

    r_lookup_deleted = client.get("/api/vocab/evoke", headers=headers)
    assert r_lookup_deleted.status_code == 404


def test_graph_links_returns_active_only(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    graph = api_mod._graph_store(user_dir)

    active = graph.add_link("c1", "c2", LinkKind.CONFUSABLE, 0.91, "similar spelling")
    deprecated = graph.add_link("c2", "c3", LinkKind.SHARES_USAGE, 0.80, "same pattern")
    deprecated.status = "deprecated"
    graph._save_links()

    r = client.get("/api/graph/links", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert [x["id"] for x in data] == [active.id]
    assert data[0]["kind"] == LinkKind.CONFUSABLE.value


def test_vocab_lookup_includes_mode_and_grouped_link_summaries(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    cards = api_mod._card_store(user_dir)
    graph = api_mod._graph_store(user_dir)

    evoke = cards.add(
        content="evoke",
        meaning="喚起",
        examples=["The story can **evoke** old memories."],
        mode="production",
    )
    invoke = cards.add(content="invoke", meaning="援引")
    suppress = cards.add(content="suppress", meaning="壓制")
    obsolete = cards.add(content="obsolete", meaning="過時")
    cards.delete(obsolete.id)

    graph.add_link(evoke.id, invoke.id, LinkKind.CONFUSABLE, 0.92, "similar spelling")
    graph.add_link(evoke.id, suppress.id, LinkKind.CONTRASTS_WITH, 0.74, "opposite direction")
    graph.add_link(evoke.id, obsolete.id, LinkKind.SHARES_USAGE, 0.50, "should be hidden")

    r = client.get("/api/vocab/evoke", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["mode"] == "production"
    assert body["examples"] == ["The story can **evoke** old memories."]
    assert body["linksByKind"]["confusable"] == [
        {
            "id": body["linksByKind"]["confusable"][0]["id"],
            "cardId": invoke.id,
            "word": "invoke",
            "kind": "confusable",
            "label": "易混",
            "confidence": 0.92,
            "reason": "similar spelling",
        }
    ]
    assert body["linksByKind"]["contrasts_with"] == [
        {
            "id": body["linksByKind"]["contrasts_with"][0]["id"],
            "cardId": suppress.id,
            "word": "suppress",
            "kind": "contrasts_with",
            "label": "對比",
            "confidence": 0.74,
            "reason": "opposite direction",
        }
    ]
    assert "shares_usage" not in body["linksByKind"]


def test_translate_endpoints_success_and_error(isolated_api):
    client = isolated_api.client
    headers = isolated_api.headers

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"t":"喚起","p":"v.","r":"evoke"}'))],
        usage=None,
    )
    with patch.object(api_mod, "_gemini_client", return_value=fake_client):
        r = client.post(
            "/api/translate/quick",
            json={"word": "evoke", "context": "The story can evoke deep memories."},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"t": "喚起", "p": "v.", "r": "evoke"}

    fake_client_phrase = MagicMock()
    fake_client_phrase.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"t":"試探性地"}'))],
        usage=None,
    )
    with patch.object(api_mod, "_gemini_client", return_value=fake_client_phrase):
        r = client.post(
            "/api/translate/phrase",
            json={"word": "on trial", "context": "He was on trial for fraud."},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["t"] == "試探性地"

    fake_client_explain = MagicMock()
    fake_client_explain.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"e":"在此語境表示引發回憶。"}'))],
        usage=None,
    )
    with patch.object(api_mod, "_gemini_client", return_value=fake_client_explain):
        r = client.post(
            "/api/translate/explain",
            json={"word": "evoke", "context": "The story can evoke deep memories."},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["e"] == "在此語境表示引發回憶。"

    failing_client = MagicMock()
    failing_client.chat.completions.create.side_effect = RuntimeError("LLM down")
    with patch.object(api_mod, "_gemini_client", return_value=failing_client):
        r = client.post(
            "/api/translate/quick",
            json={"word": "evoke", "context": "The story can evoke deep memories."},
            headers=headers,
        )
        assert r.status_code == 500
        assert "Quick translation failed" in r.text


def test_auth_verify_links_google_and_apple_by_email(isolated_api):
    client = isolated_api.client

    with (
        patch.object(api_mod, "GOOGLE_CLIENT_ID", "fake-google-client"),
        patch.object(api_mod, "verify_google_token", new=AsyncMock(return_value="google-sub")),
        patch.object(api_mod, "verify_apple_token", return_value="apple-sub"),
    ):
        r_google = client.post(
            "/auth/verify",
            json={"provider": "google", "token": "g-token", "email": "same@example.com"},
        )
        assert r_google.status_code == 200, r_google.text
        assert r_google.json()["user_id"] == "google-sub"
        assert r_google.json()["access_token"]

        r_apple = client.post(
            "/auth/verify",
            json={"provider": "apple", "token": "a-token", "email": "same@example.com"},
        )
        assert r_apple.status_code == 200, r_apple.text
        assert r_apple.json()["user_id"] == "google-sub"

    users_data = json.loads(isolated_api.users_file.read_text())
    assert users_data["_email_index"]["same@example.com"] == "google-sub"
    assert users_data["google-sub"]["linked_ids"] == ["apple-sub"]
    assert users_data["apple-sub"]["_linked_to"] == "google-sub"

    r_unknown = client.post("/auth/verify", json={"provider": "line", "token": "x"})
    assert r_unknown.status_code == 400


def test_load_users_normalizes_legacy_top_level_mochi_key(tmp_path):
    users_file = tmp_path / "users.json"
    lock_file = tmp_path / "users.json.lock"
    users_file.write_text(
        json.dumps(
            {
                "legacy_user": {
                    "mochi_api_key": "mk_legacy",
                    "provider": "google",
                }
            }
        )
    )

    with (
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
    ):
        users = api_mod.load_users()

    assert users["legacy_user"]["config"]["mochi_api_key"] == "mk_legacy"
    assert "mochi_api_key" not in users["legacy_user"]


def test_save_users_rewrites_legacy_top_level_mochi_key(tmp_path):
    users_file = tmp_path / "users.json"
    lock_file = tmp_path / "users.json.lock"

    with (
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
    ):
        api_mod.save_users(
            {
                "legacy_user": {
                    "mochi_api_key": "mk_legacy",
                    "provider": "google",
                }
            }
        )

    stored = json.loads(users_file.read_text())
    assert stored["legacy_user"]["config"]["mochi_api_key"] == "mk_legacy"
    assert "mochi_api_key" not in stored["legacy_user"]


def test_admin_endpoints_enforce_token_and_return_stats(isolated_api):
    client = isolated_api.client

    other_dir = isolated_api.data_dir / "users" / "other_user"
    cards = api_mod._card_store(other_dir)
    cards.add("apple", "蘋果")
    cards.add("banana", "香蕉")

    usage = {
        "other_user": {
            "translate_quick": {"input_tokens": 1000, "output_tokens": 500, "calls": 2},
            "embed": {"input_tokens": 2000, "output_tokens": 0, "calls": 1},
        }
    }

    with (
        patch.object(api_mod, "ADMIN_TOKEN", "adm-secret"),
        patch("kg.token_tracker.get_all_stats", return_value=usage),
    ):
        assert client.get("/admin").status_code == 403
        assert client.get("/api/admin/stats").status_code == 403
        assert client.get("/api/admin/logs").status_code == 403

        r_stats = client.get("/api/admin/stats", params={"token": "adm-secret"})
        assert r_stats.status_code == 200, r_stats.text
        body = r_stats.json()
        assert "users" in body

        other = next(u for u in body["users"] if u["user_id"] == "other_user")
        assert other["vocab_count"] == 2
        assert other["has_mochi"] is True
        assert other["total_input"] == 3000
        assert other["total_output"] == 500
        assert other["est_cost_usd"] == pytest.approx(0.000301, rel=1e-4)

        r_logs = client.get("/api/admin/logs", params={"token": "adm-secret", "n": 20})
        assert r_logs.status_code == 200
        assert isinstance(r_logs.json().get("logs"), list)


def test_admin_test_matrix_endpoints(isolated_api):
    client = isolated_api.client
    fake_result = {
        "runId": "20260305010101",
        "startedAt": "2026-03-05T01:01:01+00:00",
        "finishedAt": "2026-03-05T01:01:03+00:00",
        "durationSeconds": 2.0,
        "returnCode": 0,
        "outcome": "passed",
        "totals": {"passed": 4, "failed": 0, "errors": 0, "skipped": 1, "total": 5},
        "selectedItems": ["renderer_truncation"],
        "matrix": [{
            "module": "tests/test_api_surface.py",
            "passed": 4,
            "failed": 0,
            "errors": 0,
            "skipped": 1,
            "total": 5,
        }],
        "cases": [{
            "id": "tests/test_api_surface.py::test_sample",
            "module": "tests/test_api_surface.py",
            "status": "PASSED",
            "bucket": "passed",
        }],
        "itemResults": [{
            "id": "renderer_truncation",
            "status": "passed",
            "counts": {"passed": 1, "failed": 0, "errors": 0, "skipped": 0},
            "total": 1,
        }],
        "stdoutTail": [],
        "stderrTail": [],
    }

    run_mock = MagicMock(return_value=fake_result)
    with (
        patch.object(api_mod, "ADMIN_TOKEN", "adm-secret"),
        patch.object(api_mod, "_run_pytest_matrix", run_mock),
    ):
        assert client.get("/admin/tests").status_code == 403
        r_ui = client.get("/admin/tests", params={"token": "adm-secret"})
        assert r_ui.status_code == 200
        assert "KG Test Matrix" in r_ui.text

        r_catalog = client.get("/api/admin/tests/catalog", params={"token": "adm-secret"})
        assert r_catalog.status_code == 200
        assert "columns" in r_catalog.json()
        assert "rows" in r_catalog.json()

        r_run = client.post(
            "/api/admin/tests/run",
            params={"token": "adm-secret"},
            json={"itemIds": ["renderer_truncation"]},
        )
        assert r_run.status_code == 200
        assert r_run.json()["runId"] == fake_result["runId"]
        run_mock.assert_called_once_with(selected_items=["renderer_truncation"])

        r_last = client.get("/api/admin/tests/last", params={"token": "adm-secret"})
        assert r_last.status_code == 200
        assert r_last.json()["totals"]["total"] == 5


def test_auth_verify_response_contract(isolated_api):
    """POST /auth/verify must return access_token, user_id, expires_in with correct types and a decodable JWT."""
    client = isolated_api.client

    with (
        patch.object(api_mod, "GOOGLE_CLIENT_ID", "fake-google-client"),
        patch.object(api_mod, "verify_google_token", new=AsyncMock(return_value="contract-user-id")),
    ):
        r = client.post(
            "/auth/verify",
            json={"provider": "google", "token": "g-tok", "email": "contract@test.com"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("access_token"), str), f"access_token must be str: {body}"
    assert isinstance(body.get("user_id"), str), f"user_id must be str: {body}"
    assert isinstance(body.get("expires_in"), int), f"expires_in must be int: {body}"
    assert body["expires_in"] > 0

    decoded = pyjwt.decode(body["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert decoded["sub"] == body["user_id"]


def test_revoked_token_rejected(isolated_api):
    """After DELETE /api/user/account, the original JWT must be rejected with 401."""
    client = isolated_api.client
    headers = isolated_api.headers

    r = client.get("/api/vocab", headers=headers)
    assert r.status_code == 200, "Pre-condition: token must be valid before deletion"

    r_del = client.delete("/api/user/account", headers=headers)
    assert r_del.status_code == 200, r_del.text

    r_after = client.get("/api/vocab", headers=headers)
    assert r_after.status_code == 401, f"Expected 401 after revocation, got {r_after.status_code}"
