"""Retired zero-caller surfaces stay retired (#2063, #2259).

`secret_store` (Fernet `enc:` stored-secret encryption keyed by
`SECRET_ENC_KEY`/`JWT_SECRET`) lost its last reader when Mochi keys were
stripped; `normalize_users_payload` kept accepting an `encrypt_fn` it never
called, so callers wiring it believed users.json secrets were encrypted when
nothing was. `translate_log.count_cache_hits_since` had no production caller
and used a naive string cutoff that diverges from admin observability's
UTC-instant predicate.

#2259 retired helpers that nothing called and whose existence invited the
wrong path: `keyed_lock_registry` (no importer), an unmarked
`SharedDeckStore.increment_download_count` beside `finalize_copy_download`
(the only path that counts a copy exactly once), an unlocked
`LibraryStore.get_by_client_book_id` beside `create()`'s `BEGIN IMMEDIATE`
idempotency lookup, and the dead `_find_persisted_link_for_pair`,
`vocab_add_link_operation._next_sequence` and
`ops_edit_shared._read_json_member` helpers.
"""

from __future__ import annotations

import importlib.util
import inspect


def test_secret_store_module_is_retired():
    assert importlib.util.find_spec("kg.secret_store") is None


def test_normalize_users_payload_has_no_encryption_hook():
    from kg.user_store import normalize_users_payload

    params = inspect.signature(normalize_users_payload).parameters
    assert list(params) == ["users", "default_subscription_payload"]


def test_translate_log_has_no_unused_cache_hit_counter():
    from kg import translate_log

    assert not hasattr(translate_log, "count_cache_hits_since")


def test_keyed_lock_registry_module_is_retired():
    assert importlib.util.find_spec("kg.keyed_lock_registry") is None


def test_shared_deck_store_has_no_unmarked_download_increment():
    from kg.shared_decks.store import SharedDeckStore

    assert not hasattr(SharedDeckStore, "increment_download_count")


def test_library_store_has_no_unlocked_client_book_lookup():
    from kg.library.store import LibraryStore

    assert not hasattr(LibraryStore, "get_by_client_book_id")


def test_graph_links_has_no_dead_pair_finder():
    from kg.graph.links import _LinksMixin

    assert not hasattr(_LinksMixin, "_find_persisted_link_for_pair")


def test_add_link_operation_has_no_dead_sequence_helper():
    from kg import vocab_add_link_operation

    assert not hasattr(vocab_add_link_operation, "_next_sequence")


def test_ops_edit_shared_has_no_dead_tar_json_reader():
    from kg import ops_edit_shared

    assert not hasattr(ops_edit_shared, "_read_json_member")
