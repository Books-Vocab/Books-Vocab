"""Phase 5 — manual link creation routes through the LLM provider registry."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kg.api_models import ManualLinkRequest
from kg.vocab_handlers.graph import create_manual_link_response

_JUDGE_JSON = '{"link": "shares_usage", "confidence": 0.9, "reason": "相關"}'
_USER = {"id": "u_ml", "dir": "/tmp/u_ml"}


@pytest.fixture(autouse=True)
def _clean_env(clean_routing_env):
    yield


def _mock_client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = None
    client.chat.completions.create.return_value = resp
    return client


def _recorder(content):
    seen: list[str] = []
    clients: list = []

    def factory(provider):
        seen.append(provider.name)
        c = _mock_client(content)
        clients.append(c)
        return c

    return factory, seen, clients


def _card(cid, content):
    return SimpleNamespace(id=cid, content=content, meaning=f"m-{content}",
                           is_deleted=False, is_archived=False, notebook_id="default")


class _Cards:
    def __init__(self):
        self._c = {"a": _card("a", "alpha"), "b": _card("b", "beta")}

    def get(self, cid):
        return self._c.get(cid)

    def touch(self, cid):
        pass


class _Link:
    def __init__(self, kind, reason):
        self.id, self.from_id, self.to_id = "L1", "a", "b"
        self.kind, self.confidence, self.reason = kind, 1.0, reason


class _Graph:
    def find_link_between(self, a, b):
        return None

    def is_blocked(self, a, b):
        return False

    def add_link(self, fr, to, kind, confidence, reason, *, source="auto"):
        return _Link(kind, reason)


def _run(client_factory):
    return create_manual_link_response(
        ManualLinkRequest(from_id="a", to_id="b"),
        _USER,
        card_store_factory=lambda d: _Cards(),
        graph_store_factory=lambda d, notebook_id="default": _Graph(),
        client_factory=client_factory,
        notebook_id="default",
    )


def test_manual_link_routes_to_gemini_by_default():
    factory, seen, clients = _recorder(_JUDGE_JSON)
    _run(factory)
    assert seen == ["gemini"]
    call = clients[0].chat.completions.create.call_args.kwargs
    assert call["model"] == "gemini-2.5-flash-lite"
    assert "extra_body" not in call


def test_manual_link_routes_to_deepseek_via_judge_group_env(monkeypatch):
    """LLM_PROVIDER_JUDGE covers manual link judging (call_type group JUDGE),
    so the one knob flips both auto and manual judge together."""
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    factory, seen, clients = _recorder(_JUDGE_JSON)
    _run(factory)
    assert seen == ["deepseek"]
    call = clients[0].chat.completions.create.call_args.kwargs
    assert call["model"] == "deepseek-v4-flash"
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}


def test_manual_link_exact_call_type_env_override(monkeypatch):
    """The exact call_type env (LLM_PROVIDER_JUDGE_MANUAL) still wins for
    operators who want manual judge on a different provider than auto."""
    monkeypatch.setenv("LLM_PROVIDER_JUDGE_MANUAL", "deepseek")
    factory, seen, _ = _recorder(_JUDGE_JSON)
    _run(factory)
    assert seen == ["deepseek"]


# ---------------------------------------------------------------------------
# E3 — GET /api/vocab cursor pagination wiring (limit param + X-Next-Cursor)
#
# Body stays response_model=list[CardResponse] (iOS parsing unchanged); the
# opaque next-page cursor rides the X-Next-Cursor response header. Default limit
# is large enough to drain a normal account in one page (no header). A malformed
# cursor token -> 400 BadRequestError.
# ---------------------------------------------------------------------------

import json
import uuid

from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.settings import KGSettings


@pytest.fixture()
def vocab_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    (data_dir / "users.json").write_text(json.dumps({user_id: {"config": {}}}))

    headers = {"Authorization": f"Bearer {make_jwt(user_id)}"}
    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users

    _swap_settings(KGSettings(data_dir=data_dir, jwt_secret=TEST_JWT_SECRET))
    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        yield SimpleNamespace(
            client=TestClient(app, raise_server_exceptions=False),
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def _seed_cards(api, n: int) -> None:
    from kg.cards import CardStore

    store = CardStore(api.data_dir / "users" / api.user_id / "cards.db")
    try:
        for i in range(n):
            store.add(content=f"word{i:03d}", meaning=f"m{i}", notebook_id="default")
    finally:
        store.close()


def _get_vocab(api, **params):
    return api.client.get("/api/vocab", params=params, headers=api.headers)


def test_limit_param(vocab_api):
    """?limit=2 returns exactly 2 cards and a next-page cursor header when
    more rows remain."""
    _seed_cards(vocab_api, 5)
    r = _get_vocab(vocab_api, limit=2)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert r.headers.get("X-Next-Cursor")  # present + non-empty -> more pages


def test_cursor_follow(vocab_api):
    """Following X-Next-Cursor yields the next page with no overlap; the union
    across pages covers every card exactly once."""
    _seed_cards(vocab_api, 5)

    seen_ids: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        r = _get_vocab(vocab_api, **params)
        assert r.status_code == 200, r.text
        ids = [c["id"] for c in r.json()]
        # no overlap with anything seen so far
        assert not (set(ids) & set(seen_ids)), f"page {pages} overlaps prior pages"
        seen_ids.extend(ids)
        cursor = r.headers.get("X-Next-Cursor")
        pages += 1
        if cursor is None:
            break
        assert pages < 10  # guard against an unterminated loop

    assert len(seen_ids) == 5
    assert len(set(seen_ids)) == 5  # gap-free + dup-free


def test_last_page_no_header(vocab_api):
    """The final (drained) page carries no X-Next-Cursor header."""
    _seed_cards(vocab_api, 3)
    # limit >= total -> single drained page
    r = _get_vocab(vocab_api, limit=10)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    assert "X-Next-Cursor" not in r.headers


def test_default_limit(vocab_api):
    """Without an explicit limit the default page is large enough to drain a
    normal account in one shot (no cursor header)."""
    _seed_cards(vocab_api, 4)
    r = _get_vocab(vocab_api)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 4
    assert "X-Next-Cursor" not in r.headers


def test_malformed_cursor_returns_400(vocab_api):
    """A cursor token that does not decode to (updated_at, id) is rejected with
    400 rather than silently restarting pagination from the top."""
    _seed_cards(vocab_api, 2)
    r = _get_vocab(vocab_api, cursor="not-a-valid-cursor")
    assert r.status_code == 400, r.text
