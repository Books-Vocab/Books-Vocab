from __future__ import annotations

from threading import Event, Thread

import pytest

from kg.keyed_lock_registry import KeyedLockRegistry, KeyedLockRegistryFull


def test_keyed_lock_registry_reclaims_idle_keys_and_enforces_capacity():
    registry = KeyedLockRegistry(max_keys=1)
    entered = Event()
    release = Event()

    def hold_first_key() -> None:
        with registry.lock("cards-a"):
            entered.set()
            release.wait(timeout=2)

    holder = Thread(target=hold_first_key)
    holder.start()
    assert entered.wait(timeout=2)
    with pytest.raises(KeyedLockRegistryFull):
        with registry.lock("cards-b"):
            pass

    release.set()
    holder.join(timeout=2)
    assert not holder.is_alive()
    assert registry.size == 0

    with registry.lock("cards-b"):
        assert registry.size == 1
    assert registry.size == 0


def test_dictionary_services_share_one_named_registry(tmp_path):
    from kg.dictionary_cards import DictionaryCardService
    from kg.dictionary_promotion import DictionaryPromotionService

    cards = type("Cards", (), {"path": tmp_path / "cards.db"})()
    lifecycle = DictionaryCardService(cards=cards, graph=None, lexical=None, judge=None)
    promotion = DictionaryPromotionService(
        cards=cards,
        enrich=lambda _card: None,
        difficulty=lambda _word: 0.0,
        stage_b=None,
    )

    assert lifecycle._lock_registry is promotion._lock_registry
    assert lifecycle._lock_key == promotion._lock_key
