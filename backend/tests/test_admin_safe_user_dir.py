"""Defense-in-depth: ``_safe_user_dir`` path-traversal guard (Track-5).

The guard previously used a bare ``startswith(str(users_root))`` prefix
check with no trailing-separator boundary. With ``users_root=<data>/users``
a uid of ``../users-x`` resolves to ``<data>/users-x``, whose string *does*
start with ``<data>/users`` — so the sibling directory passed the guard and
the admin endpoint could read a neighbour of the users root.

These tests pin the boundary: traversal uids are rejected (HTTPException
400) while well-formed uids still resolve to a path under the users root.
The guard is exercised through the public ``admin_graph_density`` handler,
since ``_safe_user_dir`` is a private closure inside ``create_admin_handlers``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from kg.admin_wiring import create_admin_handlers


def _noop(*_a, **_k):  # pragma: no cover - tripwire for unexpected deps
    raise AssertionError("unexpected dependency call")


@pytest.fixture()
def handlers(tmp_path: Path):
    settings = SimpleNamespace(data_dir=tmp_path)
    return create_admin_handlers(
        runtime_settings_fn=lambda: settings,
        runtime_users_lock_file_fn=_noop,
        load_users_fn=_noop,
        save_users_fn=_noop,
        mem_log_getter=_noop,
        card_store_factory=_noop,
        build_entitlements_response_fn=_noop,
        current_admin_grant_record_fn=_noop,
    )


@pytest.mark.parametrize(
    "bad_uid",
    [
        "../users-x",       # sibling of users_root via prefix collision
        "../../etc",        # escape entirely
        "..",               # the parent itself
        "a/b",              # nested path separator
        "foo/../../bar",    # mixed traversal
    ],
)
def test_traversal_uid_rejected(handlers, bad_uid):
    with pytest.raises(HTTPException) as exc:
        handlers["admin_graph_density"](bad_uid)
    assert exc.value.status_code == 400


def test_legit_uid_resolves(handlers, tmp_path: Path):
    # Well-formed uid (Apple-sub style, dots/dashes/underscores allowed):
    # the guard must pass; with no cards.db the handler returns an empty result.
    out = handlers["admin_graph_density"]("001234.abcDEF-_.99")
    assert out["points"] == []
