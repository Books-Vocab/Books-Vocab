"""Phase 1a-ii: the global shared-decks store is wired into deps / settings /
router composition — the "three-point wiring" of the plan §3.2.

The store is *global* (one file at ``data_dir/shared_decks.db``), so its cache
key is user-independent — unlike the per-user card/notebook/library stores.
"""
from __future__ import annotations

from kg.app_router_composition import build_domain_routers
from kg.deps import _shared_deck_store
from kg.routers import shared_decks_router
from kg.service_factories import clear_store_cache, create_shared_deck_store
from kg.settings import KGSettings
from kg.shared_decks.store import SharedDeckStore

_SECRET = "x" * 16


def _settings(tmp_path) -> KGSettings:
    return KGSettings(data_dir=tmp_path, jwt_secret=_SECRET)


def test_shared_decks_path_defaults_under_data_dir(tmp_path):
    settings = _settings(tmp_path)
    assert settings.shared_decks_path == tmp_path / "shared_decks.db"


def test_create_shared_deck_store_is_cached_singleton(tmp_path):
    clear_store_cache()
    path = tmp_path / "shared_decks.db"
    a = create_shared_deck_store(path)
    b = create_shared_deck_store(path)
    try:
        assert isinstance(a, SharedDeckStore)
        assert a is b, "global store must be a cached singleton per path"
    finally:
        clear_store_cache()


def test_deps_shared_deck_store_uses_settings_path(tmp_path):
    clear_store_cache()
    settings = _settings(tmp_path)
    store = _shared_deck_store(settings)
    try:
        assert isinstance(store, SharedDeckStore)
        assert store.path == settings.shared_decks_path
    finally:
        clear_store_cache()


def test_shared_decks_router_is_mounted():
    assert shared_decks_router in build_domain_routers()


def test_shared_decks_caps_have_forward_compat_defaults(tmp_path):
    settings = _settings(tmp_path)
    # Publish is Phase 3 (community UGC) — gated off day one.
    assert settings.shared_decks_publish_enabled is False
    assert settings.max_cards_per_deck == 2000
    assert settings.shared_decks_publish_rate_limit_per_day == 20
    assert settings.shared_decks_report_auto_hide_threshold == 5
    assert settings.shared_decks_rating_min_count_for_sort == 3
