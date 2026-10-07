"""ops-edit vs. the API's cached GraphStore (#2086).

``devops.sh ops-edit`` runs ``ops_edit.py`` as its own process next to the
API. Here the in-process ``create_graph_store`` instance stands in for the API
cache and the real CLI subprocess is the foreign writer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _ops_edit_support import _card_by_content, _edit, _graph_links, _mk_user, _user_dir
from kg.graph.models import LinkKind
from kg.service_factories import clear_store_cache, create_graph_store


@pytest.fixture(autouse=True)
def _fresh_store_cache():
    clear_store_cache()
    yield
    clear_store_cache()


def _seed(tmp_path: Path) -> tuple[str, str]:
    uid = _mk_user(tmp_path)
    for word in ("a", "b", "c", "d"):
        assert _edit(str(tmp_path), "card-add", uid, word, "--meaning", "m", "--commit").returncode == 0
    r = _edit(
        str(tmp_path),
        "link-add",
        uid,
        "a",
        "b",
        "--kind",
        "shares_usage",
        "--confidence",
        "0.3",
        "--reason",
        "orig",
        "--commit",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    return uid, json.loads(r.stdout)["result"]["link"]["id"]


def _card_id(tmp_path: Path, uid: str, content: str) -> str:
    return _card_by_content(tmp_path, uid, content)["id"]


def test_link_delete_stays_deleted_after_api_flush(tmp_path):
    uid, lid = _seed(tmp_path)
    user_dir = _user_dir(tmp_path, uid)
    assert create_graph_store(user_dir).get_link(lid) is not None  # API caches L

    rd = _edit(str(tmp_path), "link-delete", uid, lid, "--commit", "--json")
    assert rd.returncode == 0, rd.stderr

    api = create_graph_store(user_dir)
    assert api.get_link(lid) is None, "API cache still serves a link ops-edit deleted"
    assert api.is_blocked(_card_id(tmp_path, uid, "a"), _card_id(tmp_path, uid, "b"))

    api.add_link(_card_id(tmp_path, uid, "c"), _card_id(tmp_path, uid, "d"), LinkKind.CONTRASTS_WITH, 0.8, "x")
    assert lid not in {lk["id"] for lk in _graph_links(tmp_path, uid)}


def test_link_update_not_reverted_by_api_flush(tmp_path):
    uid, lid = _seed(tmp_path)
    user_dir = _user_dir(tmp_path, uid)
    assert create_graph_store(user_dir).get_link(lid).reason == "orig"

    ru = _edit(
        str(tmp_path), "link-update", uid, lid, "--confidence", "0.95", "--reason", "revised", "--commit", "--json"
    )
    assert ru.returncode == 0, ru.stderr

    api = create_graph_store(user_dir)
    assert api.get_link(lid).reason == "revised", "API cache still serves the pre-update link"

    api.add_link(_card_id(tmp_path, uid, "c"), _card_id(tmp_path, uid, "d"), LinkKind.CONTRASTS_WITH, 0.8, "x")
    lk = next(lk for lk in _graph_links(tmp_path, uid) if lk["id"] == lid)
    assert lk["confidence"] == pytest.approx(0.95)
    assert lk["reason"] == "revised"
