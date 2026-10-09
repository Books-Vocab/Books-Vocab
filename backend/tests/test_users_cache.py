from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from kg.user_store import CachedUserStore


def _normalize_fn(users):
    return users, False


def _write_users(path: Path, users: dict) -> None:
    path.write_text(json.dumps(users, indent=2))


class TestCachedUserStoreCacheHit:
    def test_repeated_loads_read_file_once(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=10.0)

        read_count = 0
        original_read_text = Path.read_text

        def counted_read_text(self, *args, **kwargs):
            nonlocal read_count
            if self == users_file:
                read_count += 1
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", counted_read_text):
            for _ in range(100):
                store.load()

        assert read_count == 1

    def test_cache_returns_copy_not_reference(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=10.0)

        result1 = store.load()
        result1["u1"]["config"]["mutated"] = True
        result2 = store.load()
        assert "mutated" not in result2["u1"]["config"]


class TestCachedUserStoreWriteThrough:
    def test_save_then_load_reflects_new_data(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=10.0)

        store.load()
        new_users = {"u1": {"config": {"lang": "en"}}, "u2": {"config": {}}}
        store.save(new_users)

        result = store.load()
        assert "u2" in result
        assert result["u1"]["config"]["lang"] == "en"

    def test_save_updates_cache_without_file_read(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=10.0)

        store.load()
        store.save({"u1": {"config": {"updated": True}}})

        read_count = 0
        original_read_text = Path.read_text

        def counted_read_text(self, *args, **kwargs):
            nonlocal read_count
            if self == users_file:
                read_count += 1
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", counted_read_text):
            result = store.load()

        assert read_count == 0
        assert result["u1"]["config"]["updated"] is True


class TestCachedUserStoreTTLExpiry:
    def test_expired_cache_triggers_file_read(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=2.0)

        store.load()

        read_count = 0
        original_read_text = Path.read_text

        def counted_read_text(self, *args, **kwargs):
            nonlocal read_count
            if self == users_file:
                read_count += 1
            return original_read_text(self, *args, **kwargs)

        future_time = time.monotonic() + 10.0
        with patch("kg.user_store.time") as mock_time, patch.object(Path, "read_text", counted_read_text):
            mock_time.monotonic.return_value = future_time
            store.load()

        assert read_count == 1

    def test_within_ttl_no_extra_read(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=2.0)

        store.load()

        read_count = 0
        original_read_text = Path.read_text

        def counted_read_text(self, *args, **kwargs):
            nonlocal read_count
            if self == users_file:
                read_count += 1
            return original_read_text(self, *args, **kwargs)

        slightly_later = time.monotonic() + 1.0
        with patch("kg.user_store.time") as mock_time, patch.object(Path, "read_text", counted_read_text):
            mock_time.monotonic.return_value = slightly_later
            store.load()

        assert read_count == 0


class TestCachedUserStoreInvalidate:
    def test_invalidate_forces_next_load_to_read_file(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=10.0)

        store.load()

        _write_users(users_file, {"u1": {"config": {}}, "u2": {"config": {}}})
        store.invalidate()

        result = store.load()
        assert "u2" in result

    def test_invalidate_clears_cache(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=10.0)

        store.load()
        store.invalidate()

        assert store._cache is None
        assert store._cache_time == 0.0


class TestCachedUserStoreExternalWrite:
    """#2799: a file replaced behind the cache must not be served within the TTL."""

    def test_external_write_within_ttl_is_seen(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=60.0)
        store.load()

        _write_users(users_file, {"u1": {"config": {}}, "u2": {"config": {"revoked": True}}})

        assert "u2" in store.load()

    def test_external_atomic_replace_with_same_size_is_seen(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {"k": "a"}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=60.0)
        store.load()

        tmp = tmp_path / "other.json"
        _write_users(tmp, {"u1": {"config": {"k": "b"}}})
        tmp.replace(users_file)

        assert store.load()["u1"]["config"]["k"] == "b"

    def test_external_delete_within_ttl_is_seen(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=60.0)
        store.load()

        users_file.unlink()

        assert store.load() == {}

    def test_own_save_does_not_force_reread(self, tmp_path):
        users_file = tmp_path / "users.json"
        _write_users(users_file, {"u1": {"config": {}}})
        store = CachedUserStore(users_file, _normalize_fn, ttl=60.0)
        store.load()
        store.save({"u1": {"config": {"lang": "en"}}})

        original_read_text = Path.read_text
        reads = 0

        def counted(self, *args, **kwargs):
            nonlocal reads
            if self == users_file:
                reads += 1
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", counted):
            assert store.load()["u1"]["config"] == {"lang": "en"}
        assert reads == 0
