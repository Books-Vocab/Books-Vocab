"""Retired zero-caller surfaces stay retired (#2063).

`secret_store` (Fernet `enc:` stored-secret encryption keyed by
`SECRET_ENC_KEY`/`JWT_SECRET`) lost its last reader when Mochi keys were
stripped; `normalize_users_payload` kept accepting an `encrypt_fn` it never
called, so callers wiring it believed users.json secrets were encrypted when
nothing was. `translate_log.count_cache_hits_since` had no production caller
and used a naive string cutoff that diverges from admin observability's
UTC-instant predicate.
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
