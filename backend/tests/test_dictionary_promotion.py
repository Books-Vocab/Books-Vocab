from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from kg.cards import CardStore
from kg.cards.dictionary_models import DictionaryEntry
from kg.exceptions import QuotaExceededError
from kg.graph import GraphStore
from kg.lexical import LexicalAttribution, LexicalEntry, LexicalExample, LexicalSense


def _entry() -> LexicalEntry:
    return LexicalEntry(
        provider="free_dictionary",
        dictionary_id="wiktionary-en",
        schema_version="v1",
        entry_key="en.aW52b2tl",
        word="invoke",
        language="en",
        senses=[
            LexicalSense(
                key="sense-1",
                part_of_speech="verb",
                definition="To call upon for help.",
                translations=["援引"],
                examples=[
                    LexicalExample(
                        key="example-1",
                        text="They invoked an old rule.",
                    )
                ],
            )
        ],
        attribution=LexicalAttribution(
            provider="free_dictionary",
            source_url="https://en.wiktionary.org/wiki/invoke",
            license_name="CC BY-SA 4.0",
            license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            attribution_text="Dictionary data from Wiktionary via FreeDictionaryAPI.com",
        ),
        fetched_at=datetime.now(UTC),
    )


def _dictionary_card(cards: CardStore):
    card = cards.add(
        "invoke",
        "援引",
        pos="verb",
        examples=["They invoked an old rule."],
        notebook_id="default",
        card_role="dictionary",
        review_eligible=False,
    )
    entry = _entry()
    with Session(cards.engine) as session:
        session.add(
            DictionaryEntry(
                card_id=card.id,
                provider=entry.provider,
                dictionary_id=entry.dictionary_id,
                provider_entry_key=entry.entry_key,
                provider_schema_version=entry.schema_version,
                selected_sense_key="sense-1",
                selected_example_key="example-1",
                payload_json=entry.model_dump_json(),
                source_url=entry.attribution.source_url,
                license_name=entry.attribution.license_name,
                license_url=entry.attribution.license_url,
                attribution_text=entry.attribution.attribution_text,
                fetched_at=entry.fetched_at,
                materialization_status="active",
            )
        )
        session.commit()
    return card


def test_promotion_enqueue_is_durable_idempotent_and_learning_is_already_promoted(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    card = _dictionary_card(cards)

    first = cards.enqueue_dictionary_promotion(card.id)
    assert first.card.promotion_state == "queued"
    assert first.already_promoted is False
    first_job = cards.get_dictionary_promotion_job(card.id)
    assert first_job is not None
    assert first_job.status == "queued"
    assert first_job.attempt_count == 0

    replay = cards.enqueue_dictionary_promotion(card.id)
    assert replay.card.promotion_state == "queued"
    assert replay.already_promoted is False
    assert cards.get_dictionary_promotion_job(card.id).queued_at == first_job.queued_at

    claimed = cards.claim_dictionary_promotion(card.id)
    assert claimed is not None
    assert claimed.card.promotion_state == "running"
    assert claimed.job.status == "running"
    assert claimed.job.attempt_count == 1
    assert cards.claim_dictionary_promotion(card.id) is None

    running_replay = cards.enqueue_dictionary_promotion(card.id)
    assert running_replay.card.promotion_state == "running"
    assert running_replay.already_promoted is False

    cards.complete_dictionary_promotion(
        card.id,
        worker_id=claimed.job.worker_id,
        attempt_count=claimed.job.attempt_count,
        meaning="援引；喚起",
        pos="v.",
        note="常用於援引規則或權威。",
        collocations=["invoke a rule"],
        difficulty=3.25,
    )
    already = cards.enqueue_dictionary_promotion(card.id)
    assert already.already_promoted is True
    assert already.card.card_role == "learning"
    assert already.card.promotion_state == "idle"


def test_promotion_success_atomically_preserves_identity_and_resets_srs(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    original = _dictionary_card(cards)
    old_created_at = original.created_at
    old_updated_at = original.updated_at
    cards.update(
        original.id,
        review_interval_hours=96,
        next_review_at=datetime.now(UTC) + timedelta(days=4),
        last_reviewed_at=datetime.now(UTC) - timedelta(days=1),
        review_count=8,
        lapse_count=3,
        review_streak=4,
        last_review_feedback=1,
    )
    cards.enqueue_dictionary_promotion(original.id)
    claim = cards.claim_dictionary_promotion(original.id)

    promoted = cards.complete_dictionary_promotion(
        original.id,
        worker_id=claim.job.worker_id,
        attempt_count=claim.job.attempt_count,
        meaning="援引；喚起",
        pos="v.",
        note="常用於援引規則或權威。",
        collocations=["invoke a rule", "invoke authority"],
        difficulty=3.25,
    )

    assert promoted.id == original.id
    assert promoted.created_at == old_created_at
    assert promoted.updated_at > old_updated_at
    assert promoted.card_role == "learning"
    assert promoted.review_eligible is True
    assert promoted.promotion_state == "idle"
    assert promoted.promoted_at is not None
    assert promoted.meaning == "援引；喚起"
    assert promoted.pos == "v."
    assert promoted.note == "常用於援引規則或權威。"
    assert promoted.collocations == ["invoke a rule", "invoke authority"]
    assert promoted.difficulty == 3.25
    assert promoted.review_interval_hours == 12
    assert promoted.next_review_at is None
    assert promoted.last_reviewed_at is None
    assert promoted.review_count == 0
    assert promoted.lapse_count == 0
    assert promoted.review_streak == 0
    assert promoted.last_review_feedback == -1
    assert cards.get_dictionary_entry(original.id) is not None
    job = cards.get_dictionary_promotion_job(original.id)
    assert job.status == "completed"
    assert job.finished_at is not None


def test_promotion_failure_retains_dictionary_content_and_can_be_requeued(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    original = _dictionary_card(cards)
    cards.enqueue_dictionary_promotion(original.id)
    claim = cards.claim_dictionary_promotion(original.id)

    failed = cards.fail_dictionary_promotion(
        original.id,
        worker_id=claim.job.worker_id,
        attempt_count=claim.job.attempt_count,
        error_code="quota_exhausted",
        retryable=True,
    )

    assert failed.card_role == "dictionary"
    assert failed.review_eligible is False
    assert failed.promotion_state == "failed"
    assert failed.meaning == original.meaning
    assert failed.examples == original.examples
    job = cards.get_dictionary_promotion_job(original.id)
    assert job.status == "failed"
    assert job.error_code == "quota_exhausted"
    assert job.retryable is True
    from kg.dictionary_cards import DictionaryCardService

    detail = DictionaryCardService(
        cards=cards,
        graph=GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json"),
        lexical=None,
        judge=None,
    ).get_saved_card(original.id)
    assert detail.promotion_error_code == "quota_exhausted"
    assert detail.promotion_retryable is True

    retried = cards.enqueue_dictionary_promotion(original.id)
    assert retried.card.promotion_state == "queued"
    assert retried.already_promoted is False
    retry_job = cards.get_dictionary_promotion_job(original.id)
    assert retry_job.status == "queued"
    assert retry_job.error_code is None
    assert retry_job.attempt_count == 1


@pytest.mark.asyncio
async def test_promotion_service_uses_pinned_example_and_stage_b_cannot_roll_back(tmp_path):
    from kg.dictionary_promotion import DictionaryPromotionService, PromotionEnrichment

    cards = CardStore(tmp_path / "cards.db")
    card = _dictionary_card(cards)
    seen = []

    async def enrich(target):
        seen.append(target)
        return PromotionEnrichment(
            meaning="援引；喚起",
            pos="v.",
            note="常用於援引規則或權威。",
            collocations=["invoke a rule"],
        )

    async def broken_stage_b(_card):
        raise RuntimeError("embedding unavailable")

    service = DictionaryPromotionService(
        cards=cards,
        enrich=enrich,
        difficulty=lambda word: 3.25 if word == "invoke" else 0.0,
        stage_b=broken_stage_b,
    )
    queued = service.request(card.id)
    assert queued.promotion_state == "queued"
    assert queued.already_promoted is False

    result = await service.run(card.id)

    assert len(seen) == 1
    assert seen[0].id == card.id
    assert seen[0].examples == ["They invoked an old rule."]
    assert result.card.card_role == "learning"
    assert result.card.difficulty == 3.25
    assert result.stage_b_succeeded is False
    assert cards.get(card.id).card_role == "learning"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        (QuotaExceededError(60), "quota_exhausted"),
        (RuntimeError("provider failed"), "enrichment_failed"),
    ],
)
async def test_promotion_service_classifies_failure_and_retry_succeeds(
    tmp_path, failure, error_code
):
    from kg.dictionary_promotion import DictionaryPromotionService, PromotionEnrichment

    cards = CardStore(tmp_path / "cards.db")
    card = _dictionary_card(cards)
    attempts = 0

    async def enrich(_target):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise failure
        return PromotionEnrichment(
            meaning="援引；喚起",
            pos="v.",
            note=None,
            collocations=[],
        )

    service = DictionaryPromotionService(
        cards=cards,
        enrich=enrich,
        difficulty=lambda _word: 3.25,
        stage_b=None,
    )
    service.request(card.id)
    failed = await service.run(card.id)
    assert failed.card.card_role == "dictionary"
    assert failed.card.promotion_state == "failed"
    assert failed.error_code == error_code
    assert cards.get_dictionary_promotion_job(card.id).retryable is True

    service.request(card.id)
    succeeded = await service.run(card.id)
    assert succeeded.card.card_role == "learning"
    assert succeeded.error_code is None
    assert attempts == 2


@pytest.mark.asyncio
async def test_concurrent_promotion_workers_only_enrich_once(tmp_path):
    from kg.dictionary_promotion import DictionaryPromotionService, PromotionEnrichment

    cards = CardStore(tmp_path / "cards.db")
    card = _dictionary_card(cards)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def enrich(_target):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return PromotionEnrichment(
            meaning="援引；喚起",
            pos="v.",
            note=None,
            collocations=[],
        )

    service = DictionaryPromotionService(
        cards=cards,
        enrich=enrich,
        difficulty=lambda _word: 3.25,
        stage_b=None,
    )
    service.request(card.id)
    first = asyncio.create_task(service.run(card.id))
    await started.wait()
    second = asyncio.create_task(service.run(card.id))
    await asyncio.sleep(0)
    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert calls == 1
    assert first_result.card.id == second_result.card.id == card.id
    assert cards.get(card.id).card_role == "learning"


def test_new_worker_generation_requeues_a_crash_orphaned_running_job(tmp_path):
    from kg.dictionary_promotion import DictionaryPromotionService, PromotionEnrichment

    cards = CardStore(tmp_path / "cards.db")
    card = _dictionary_card(cards)
    cards.enqueue_dictionary_promotion(card.id)
    cards.claim_dictionary_promotion(card.id, worker_id="dead-process")

    recovered = DictionaryPromotionService(
        cards=cards,
        enrich=lambda _target: PromotionEnrichment(
            meaning="援引；喚起",
            pos="v.",
            note=None,
            collocations=[],
        ),
        difficulty=lambda _word: 3.25,
        stage_b=None,
        worker_id="new-process",
    ).request(card.id)

    assert recovered.promotion_state == "queued"
    job = cards.get_dictionary_promotion_job(card.id)
    assert job.status == "queued"
    assert job.worker_id is None


@pytest.mark.parametrize("old_finishes_first", [True, False])
def test_recovered_promotion_claim_is_fenced_from_old_worker_completion(
    tmp_path, old_finishes_first
):
    from kg.cards.dictionary_store import PromotionLeaseLost

    cards = CardStore(tmp_path / "cards.db")
    card = _dictionary_card(cards)
    cards.enqueue_dictionary_promotion(card.id)
    old = cards.claim_dictionary_promotion(card.id, worker_id="old-process")
    assert old is not None
    assert cards.recover_orphaned_dictionary_promotion(
        card.id, current_worker_id="new-process"
    )
    new = cards.claim_dictionary_promotion(card.id, worker_id="new-process")
    assert new is not None

    def old_complete():
        return cards.complete_dictionary_promotion(
            card.id,
            worker_id=old.job.worker_id,
            attempt_count=old.job.attempt_count,
            meaning="OLD",
            pos="v.",
            note=None,
            collocations=[],
            difficulty=1.0,
        )

    def new_complete():
        return cards.complete_dictionary_promotion(
            card.id,
            worker_id=new.job.worker_id,
            attempt_count=new.job.attempt_count,
            meaning="NEW",
            pos="v.",
            note=None,
            collocations=[],
            difficulty=4.0,
        )

    if old_finishes_first:
        with pytest.raises(PromotionLeaseLost):
            old_complete()
        new_complete()
    else:
        new_complete()
        with pytest.raises(PromotionLeaseLost):
            old_complete()

    final = cards.get(card.id)
    assert final.meaning == "NEW"
    assert final.difficulty == 4.0
    assert final.card_role == "learning"


def test_production_enrichment_mapping_keeps_valid_meaning_when_meaning_fix_is_null():
    from kg.cards import Card
    from kg.dictionary_promotion import promotion_enrichment_from_result

    card = Card(content="invoke", meaning="援引", examples=["They invoked a rule."])
    result = promotion_enrichment_from_result(
        card,
        {
            "word": "invoke",
            "pos": "v.",
            "note": "常用於援引規則。",
            "collocations": ["invoke a rule"],
            "meaning_fix": None,
        },
        normalize_pos=lambda value: value,
    )

    assert result.meaning == "援引"
    assert result.pos == "v."


@pytest.mark.asyncio
async def test_stage_a_commit_transfers_same_card_between_sync_projections_and_keeps_links(
    tmp_path,
):
    from types import SimpleNamespace

    from kg.dictionary_cards import DictionaryCardService
    from kg.dictionary_promotion import DictionaryPromotionService, PromotionEnrichment
    from kg.graph import LinkKind
    from kg.vocab_crud import list_vocab_cards

    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    source = cards.add("source", "來源", notebook_id="default")
    target = _dictionary_card(cards)
    link = graph.add_link(
        source.id,
        target.id,
        LinkKind.SHARES_USAGE,
        1.0,
        "dictionary context",
    )
    dictionary = DictionaryCardService(
        cards=cards,
        graph=graph,
        lexical=None,
        judge=None,
    )

    def projection(card, _graph, _cards_by_id):
        return SimpleNamespace(id=card.id)

    before_legacy, _ = list_vocab_cards(
        since=None,
        cards_store=cards,
        graph=graph,
        card_response_builder=projection,
        notebook_id="default",
        limit=100,
    )
    assert {item.id for item in before_legacy} == {source.id}
    assert dictionary.get_saved_card(target.id).card.card_role == "dictionary"

    service = DictionaryPromotionService(
        cards=cards,
        enrich=lambda _target: PromotionEnrichment(
            meaning="援引；喚起",
            pos="v.",
            note=None,
            collocations=[],
        ),
        difficulty=lambda _word: 3.25,
        stage_b=None,
    )
    service.request(target.id)
    result = await service.run(target.id)

    after_legacy, _ = list_vocab_cards(
        since=None,
        cards_store=cards,
        graph=graph,
        card_response_builder=projection,
        notebook_id="default",
        limit=100,
    )
    after_dictionary = dictionary.get_saved_card(target.id)
    assert result.card.id == target.id
    assert {item.id for item in after_legacy} == {source.id, target.id}
    assert after_dictionary.card.id == target.id
    assert after_dictionary.card.card_role == "learning"
    assert graph.get_link(link.id).id == link.id


def test_promotion_endpoint_queues_durable_work_and_is_idempotent(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router
    from kg.dictionary_promotion import PromotionRequestResult

    calls: list[str] = []

    class FakePromotionService:
        def request(self, card_id):
            return PromotionRequestResult(
                card_id=card_id,
                card_role="dictionary",
                promotion_state="queued",
                already_promoted=False,
            )

        async def run(self, card_id):
            calls.append(card_id)

    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_promotion_service",
        lambda _user: FakePromotionService(),
    )
    response = isolated_api.client.post(
        "/api/dictionary/cards/card-1/promote",
        headers=isolated_api.headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "cardId": "card-1",
        "cardRole": "dictionary",
        "promotionState": "queued",
        "alreadyPromoted": False,
    }
    assert calls == ["card-1"]


def test_promotion_endpoint_does_not_schedule_an_already_promoted_card(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router
    from kg.dictionary_promotion import PromotionRequestResult

    class FakePromotionService:
        def request(self, card_id):
            return PromotionRequestResult(
                card_id=card_id,
                card_role="learning",
                promotion_state="idle",
                already_promoted=True,
            )

        async def run(self, _card_id):
            pytest.fail("already-promoted card scheduled background work")

    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_promotion_service",
        lambda _user: FakePromotionService(),
    )
    response = isolated_api.client.post(
        "/api/dictionary/cards/card-1/promote",
        headers=isolated_api.headers,
    )

    assert response.status_code == 200
    assert response.json()["alreadyPromoted"] is True
    assert response.json()["cardRole"] == "learning"
