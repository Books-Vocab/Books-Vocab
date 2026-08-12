# ruff: noqa: F401, F403, F405, I001
"""test dictionary materialize.py test ownership shard."""



from _dictionary_v1_support import *  # noqa: F403



def test_dictionary_materialize_link_fresh_replay_and_reuse_pinned_selection(tmp_path):
    service, cards, graph, lexical, judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)

    fresh = service.materialize_and_link(idempotency_key="op-1", **request)
    replay = service.materialize_and_link(idempotency_key="op-1", **request)
    reused = service.materialize_and_link(
        idempotency_key="op-2",
        **{**request, "sense_key": "stale-client-sense", "example_key": "stale-client-example"},
    )

    target = cards.get(fresh.target_card.id)
    assert target is not None
    assert (target.card_role, target.review_eligible, target.reader_hidden) == (
        "dictionary", False, False
    )
    assert fresh.created_card is True and fresh.created_link is True and fresh.replayed is False
    assert replay.target_card.id == fresh.target_card.id and replay.replayed is True
    assert reused.target_card.id == fresh.target_card.id
    assert reused.created_card is False and reused.created_link is False
    assert graph.find_link_between(source.id, target.id).id == fresh.link.id
    assert len(list(cards.all())) == 2
    assert judge.calls == 2
    assert lexical.calls == 2

    detail = service.get_saved_card(target.id)
    assert detail.selected_sense_key == lexical.entry.senses[0].key
    assert detail.selected_example_key == lexical.entry.senses[0].examples[0].key
    assert detail.entry.attribution.license_name == "CC BY-SA 4.0"
    assert detail.materialization_status == "active"

def test_dictionary_materialize_reuses_learning_card_without_sidecar_or_demotion(tmp_path):
    service, cards, graph, lexical, _judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    learning = cards.add("invoke", "援引（已學習）", notebook_id="default")

    result = service.materialize_and_link(
        idempotency_key="learning-reuse",
        **_materialize_request(source.id, lexical.entry),
    )

    assert result.target_card.id == learning.id
    assert result.created_card is False and result.created_link is True
    assert cards.get(learning.id).card_role == "learning"
    assert cards.get_dictionary_entry(learning.id) is None
    assert graph.find_link_between(source.id, learning.id) is not None

def test_dictionary_materialize_rejects_idempotency_mismatch_self_and_cross_notebook(tmp_path):
    from kg.exceptions import ConflictError, NotFoundError

    service, cards, _graph, lexical, _judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)
    service.materialize_and_link(idempotency_key="same-key", **request)

    with pytest.raises(ConflictError):
        service.materialize_and_link(
            idempotency_key="same-key", **{**request, "example_key": "different"}
        )
    self_service, _, _, self_lexical, _ = _dictionary_service(
        tmp_path, entry=_lexical_entry("summon")
    )
    with pytest.raises(ConflictError):
        self_service.materialize_and_link(
            idempotency_key="self-link",
            **_materialize_request(source.id, self_lexical.entry),
        )

    foreign = cards.add("foreign", "外部", notebook_id="other")
    with pytest.raises(NotFoundError):
        service.materialize_and_link(
            idempotency_key="cross-notebook",
            **_materialize_request(foreign.id, lexical.entry),
        )

@pytest.mark.parametrize("crash_step", ["after_card_stage", "after_graph_write", "after_touch"])
def test_dictionary_materialize_crash_recovery_converges(tmp_path, crash_step):
    crashed = False

    def crash_hook(step):
        nonlocal crashed
        if step == crash_step and not crashed:
            crashed = True
            raise RuntimeError("injected crash")

    service, cards, graph, lexical, _judge = _dictionary_service(
        tmp_path, crash_hook=crash_hook
    )
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)
    with pytest.raises(RuntimeError, match="injected crash"):
        service.materialize_and_link(idempotency_key="recover", **request)

    assert service.list_projection(notebook_id="default", limit=100).items == []
    from kg.vocab_graph import graph_links_payload
    assert graph_links_payload(
        graph=graph, cards_store=cards, include_dictionary=True
    ) == []

    result = service.materialize_and_link(idempotency_key="recover", **request)
    assert result.replayed is False
    assert len([c for c in cards.all() if c.content.casefold() == "invoke"]) == 1
    assert len(graph.all_links()) == 1
    assert service.get_saved_card(result.target_card.id).materialization_status == "active"
    assert service.get_operation("recover").status == "completed"

def test_dictionary_selection_visibility_and_incremental_projection(tmp_path):
    from kg.exceptions import ConflictError
    from kg.lexical import LexicalExample, LexicalSense

    entry = _lexical_entry()
    second = LexicalSense(
        key="sense_second",
        part_of_speech="verb",
        definition="To cite as authority.",
        examples=[LexicalExample(key="example_second", text="Counsel invoked precedent.")],
        translations=["援引"],
    )
    entry.senses.append(second)
    service, cards, _graph, lexical, _judge = _dictionary_service(tmp_path, entry=entry)
    source = cards.add("summon", "召喚", notebook_id="default")
    result = service.materialize_and_link(
        idempotency_key="select", **_materialize_request(source.id, lexical.entry)
    )
    before = cards.get(result.target_card.id).updated_at

    selected = service.update_selection(
        result.target_card.id,
        sense_key=second.key,
        example_key=second.examples[0].key,
    )
    hidden = service.set_reader_visibility(result.target_card.id, reader_hidden=True)

    assert selected.selected_sense_key == second.key
    assert selected.selected_example_key == second.examples[0].key
    assert hidden.reader_hidden is True
    updated = cards.get(result.target_card.id)
    assert updated.meaning == "援引"
    assert updated.examples == ["Counsel invoked precedent."]
    assert updated.updated_at > before

    projection = service.list_projection(notebook_id="default", limit=100)
    assert [item.card.id for item in projection.items] == [result.target_card.id]
    assert projection.items[0].reader_hidden is True
    assert projection.items[0].dictionary.selected_example_key == "example_second"

    cards.update(result.target_card.id, card_role="learning")
    with pytest.raises(ConflictError):
        service.update_selection(
            result.target_card.id,
            sense_key=entry.senses[0].key,
            example_key=entry.senses[0].examples[0].key,
        )

def test_dictionary_materialize_concurrent_same_request_converges(tmp_path):
    service, cards, graph, lexical, _judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)
    results = []
    errors = []

    def worker():
        try:
            results.append(
                service.materialize_and_link(idempotency_key="concurrent", **request)
            )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    target_ids = {result.target_card.id for result in results}
    assert len(target_ids) == 1
    assert sum(result.replayed for result in results) == 1
    assert len(graph.all_links()) == 1

def test_dictionary_saved_card_api_contract_and_rollout_read_availability(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router

    entry = _lexical_entry()
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, _judge = _dictionary_service(user_dir, entry=entry)
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    created = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json=payload,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["createdCard"] is True
    assert body["targetCard"]["cardRole"] == "dictionary"
    assert body["dictionaryCard"]["dictionary"]["selectedExampleKey"] == sense.examples[0].key
    card_id = body["targetCard"]["id"]

    # Rollback flag only stops new materialization/search; saved reads and edits remain.
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=False,
    )
    detail = isolated_api.client.get(
        f"/api/dictionary/cards/{card_id}", headers=isolated_api.headers
    )
    projection = isolated_api.client.get(
        "/api/dictionary-cards?notebook_id=default", headers=isolated_api.headers
    )
    visibility = isolated_api.client.patch(
        f"/api/cards/{card_id}/reader-visibility",
        headers=isolated_api.headers,
        json={"readerHidden": True},
    )
    selection = isolated_api.client.patch(
        f"/api/dictionary/cards/{card_id}/selection",
        headers=isolated_api.headers,
        json={"senseKey": sense.key, "exampleKey": sense.examples[0].key},
    )

    assert detail.status_code == 200
    assert detail.json()["selectedExampleKey"] == sense.examples[0].key
    assert detail.json()["entry"]["attribution"]["license_name"] == "CC BY-SA 4.0"
    assert projection.status_code == 200 and projection.json()[0]["card"]["id"] == card_id
    assert visibility.status_code == 200 and visibility.json()["readerHidden"] is True
    assert selection.status_code == 200

    replay_while_disabled = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json=payload,
    )
    mismatch_while_disabled = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json={**payload, "exampleKey": "different-request"},
    )
    assert replay_while_disabled.status_code == 200
    assert replay_while_disabled.json()["replayed"] is True
    assert mismatch_while_disabled.status_code == 409

    disabled_create = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op-2"},
        json=payload,
    )
    assert disabled_create.status_code == 403

    import kg.deps_quota as deps_quota
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    monkeypatch.setattr(
        deps_quota,
        "_check_quota",
        lambda *_args, **_kwargs: pytest.fail("completed replay reached quota admission"),
    )
    replay_without_quota = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json=payload,
    )
    assert replay_without_quota.status_code == 200

def test_dictionary_materialize_api_requires_idempotency_key_and_rejects_hash_mismatch(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, _judge = _dictionary_service(user_dir)
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    missing = isolated_api.client.post(
        "/api/graph/links/from-dictionary", headers=isolated_api.headers, json=payload
    )
    first = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "same-api-key"},
        json=payload,
    )
    mismatch = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "same-api-key"},
        json={**payload, "exampleKey": "not-the-same-request"},
    )
    replay = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "same-api-key"},
        json=payload,
    )

    assert missing.status_code == 422
    assert first.status_code == 200
    assert mismatch.status_code == 409
    assert replay.status_code == 200 and replay.json()["replayed"] is True

def test_dictionary_projection_cursor_tombstone_role_transfer_and_notebook_isolation(tmp_path):
    from kg.dictionary_cards import DictionaryCardService
    from kg.exceptions import BadRequestError
    from kg.graph import GraphStore

    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = DictionaryCardService(
        cards=cards,
        graph=graph,
        lexical=_CanonicalLexical(_lexical_entry()),
        judge=_Judge(),
    )

    created = []
    for index, (word, notebook_id) in enumerate(
        [("invoke", "default"), ("evoke", "default"), ("cite", "other")]
    ):
        entry = _lexical_entry(word)
        sense = entry.senses[0]
        card, was_created = cards.stage_dictionary_card(
            entry=entry,
            notebook_id=notebook_id,
            sense_key=sense.key,
            example_key=sense.examples[0].key,
        )
        assert was_created is True
        key = f"projection-{index}"
        cards.begin_lexical_operation(key, f"hash-{index}")
        cards.activate_dictionary_entry_and_complete_operation(
            card_id=card.id,
            idempotency_key=key,
            response_json="{}",
        )
        created.append(card)

    first = service.list_projection(notebook_id="default", limit=1)
    second = service.list_projection(
        notebook_id="default", limit=1, cursor=first.next_cursor
    )
    assert len(first.items) == len(second.items) == 1
    assert first.items[0].card.id != second.items[0].card.id
    assert second.next_cursor is None

    watermark = max(cards.get(created[0].id).updated_at, cards.get(created[1].id).updated_at)
    cards.update(created[0].id, card_role="learning", review_eligible=True)
    cards.delete(created[1].id)
    delta = service.list_projection(
        notebook_id="default", limit=10, since=watermark
    )
    assert {item.card.id for item in delta.items} == {created[0].id, created[1].id}
    assert any(item.card.card_role == "learning" for item in delta.items)
    assert any(item.card.is_deleted for item in delta.items)
    assert created[2].id not in {item.card.id for item in delta.items}

    with pytest.raises(BadRequestError):
        service.list_projection(notebook_id="default", limit=10, cursor="not-a-cursor")

def test_dictionary_materialize_api_rejects_foreign_notebook_before_provider_call(isolated_api):
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    response = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "foreign-notebook"},
        json={
            "sourceCardId": "missing",
            "notebookId": "not-owned",
            "provider": "free_dictionary",
            "entryKey": "en.aW52b2tl",
            "senseKey": "sense",
            "exampleKey": "example",
        },
    )
    assert response.status_code == 403

def test_dictionary_saga_retry_with_persisted_judgement_skips_quota_readmission(
    isolated_api, monkeypatch
):
    import kg.deps_quota as deps_quota
    import kg.routers.dictionary as dictionary_router

    crashed = False

    def crash_once(step):
        nonlocal crashed
        if step == "after_card_stage" and not crashed:
            crashed = True
            raise RuntimeError("injected crash")

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, judge = _dictionary_service(
        user_dir, crash_hook=crash_once
    )
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    first = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-after-judge"},
        json=payload,
    )
    assert first.status_code == 500
    assert judge.calls == 1

    monkeypatch.setattr(
        deps_quota,
        "_check_quota",
        lambda *_args, **_kwargs: pytest.fail("resumable saga reached quota admission"),
    )
    resumed = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-after-judge"},
        json=payload,
    )
    assert resumed.status_code == 200, resumed.text
    assert judge.calls == 1
    assert service.get_operation("resume-after-judge").status == "completed"

def test_saved_dictionary_routes_are_db_only_when_lookup_rollout_is_disabled(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    cards = dictionary_router._card_store(user_dir)
    entry = _lexical_entry()
    sense = entry.senses[0]
    card, _ = cards.stage_dictionary_card(
        entry=entry,
        notebook_id="default",
        sense_key=sense.key,
        example_key=sense.examples[0].key,
    )
    cards.begin_lexical_operation("db-only-fixture", "fixture")
    cards.activate_dictionary_entry_and_complete_operation(
        card_id=card.id,
        idempotency_key="db-only-fixture",
        response_json="{}",
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=False,
        dictionary_provider_default="unavailable-provider",
    )
    monkeypatch.setattr(
        dictionary_router,
        "_lexical_service",
        lambda _settings: pytest.fail("saved route constructed lexical provider"),
    )
    monkeypatch.setattr(
        dictionary_router,
        "_manual_judge",
        lambda *_args, **_kwargs: pytest.fail("saved route constructed manual judge"),
    )

    detail = isolated_api.client.get(
        f"/api/dictionary/cards/{card.id}", headers=isolated_api.headers
    )
    projection = isolated_api.client.get(
        "/api/dictionary-cards?notebook_id=default", headers=isolated_api.headers
    )
    selected = isolated_api.client.patch(
        f"/api/dictionary/cards/{card.id}/selection",
        headers=isolated_api.headers,
        json={"senseKey": sense.key, "exampleKey": sense.examples[0].key},
    )
    visibility = isolated_api.client.patch(
        f"/api/cards/{card.id}/reader-visibility",
        headers=isolated_api.headers,
        json={"readerHidden": True},
    )

    # `promote` resolves through `_dictionary_promotion_service`, a *different*
    # constructor from the three routes above — nothing else in this suite
    # exercises it with the flag off, so a guard added there would ship unseen.
    # Stub the service so the assertion is about admission, not about enrich.
    from kg.dictionary_promotion import PromotionRequestResult

    class _StubPromotionService:
        def request(self, card_id):
            return PromotionRequestResult(
                card_id=card_id,
                card_role="dictionary",
                promotion_state="queued",
                already_promoted=False,
            )

        async def run(self, _card_id):
            return None

    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_promotion_service",
        lambda _user: _StubPromotionService(),
    )
    promoted = isolated_api.client.post(
        f"/api/dictionary/cards/{card.id}/promote", headers=isolated_api.headers
    )

    # archive → delete on the same card, in that order: deploy.md promises a
    # rolled-back deployment can still unwind an existing card, and delete is
    # the terminal step of that unwind.
    archived = isolated_api.client.patch(
        f"/api/dictionary/cards/{card.id}/archive",
        headers=isolated_api.headers,
        json={"archived": True, "notebookId": "default"},
    )
    deleted = isolated_api.client.delete(
        f"/api/dictionary/cards/{card.id}",
        headers=isolated_api.headers,
        params={"notebook_id": "default"},
    )

    assert detail.status_code == 200, detail.text
    assert projection.status_code == 200, projection.text
    assert selected.status_code == 200, selected.text
    assert visibility.status_code == 200, visibility.text
    assert promoted.status_code == 200, promoted.text
    assert archived.status_code == 200, archived.text
    assert deleted.status_code == 200, deleted.text

def test_disabled_rollout_finishes_an_interrupted_saga_but_still_blocks_new_ones(
    isolated_api, monkeypatch
):
    """Rolling back mid-flight must not wedge a staged card.

    The judge already ran and the card already holds the notebook's unique
    content slot, so the flag has no new work left to stop — only a staged row
    that ``get_saved_card`` refuses to return. Finishing it is the rollback
    contract; admitting a *new* materialization is not.
    """
    import kg.routers.dictionary as dictionary_router

    crashed = False

    def crash_once(step):
        nonlocal crashed
        if step == "after_card_stage" and not crashed:
            crashed = True
            raise RuntimeError("injected crash")

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, judge = _dictionary_service(
        user_dir, crash_hook=crash_once
    )
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    first = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-while-disabled"},
        json=payload,
    )
    assert first.status_code == 500
    assert judge.calls == 1
    staged = cards.find_by_content(lexical.entry.word, notebook_id="default")
    assert staged is not None
    assert cards.get_dictionary_entry(staged.id).materialization_status == "staged"

    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=False,
    )
    resumed = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-while-disabled"},
        json=payload,
    )
    assert resumed.status_code == 200, resumed.text
    assert judge.calls == 1
    assert cards.get_dictionary_entry(staged.id).materialization_status == "active"

    fresh_start = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "new-while-disabled"},
        json=payload,
    )
    assert fresh_start.status_code == 403

def test_disabled_rollout_resume_serves_the_entry_from_cache_without_the_provider(
    tmp_path,
):
    """Cache-only mode is what makes the resume above safe to admit.

    Without it a rolled-back deployment could still reach the provider through
    a resumed saga whose cached entry had expired.
    """
    from kg.exceptions import ForbiddenError
    from kg.lexical import LexicalCache, LexicalService

    entry = _lexical_entry()

    class _ExplodingProvider:
        provider_id = entry.provider
        dictionary_id = entry.dictionary_id
        schema_version = entry.schema_version
        capabilities = __import__(
            "kg.lexical", fromlist=["LexicalProviderCapabilities"]
        ).LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=True,
            pronunciation=True,
            cache_policy="persistent",
        )

        def search(self, *_args, **_kwargs):
            raise AssertionError("cache-only lookup reached the provider")

        def get_entry(self, *_args, **_kwargs):
            raise AssertionError("cache-only lookup reached the provider")

    cache = LexicalCache(tmp_path / "lexical_cache.db")
    service = LexicalService(provider=_ExplodingProvider(), cache=cache)

    with pytest.raises(ForbiddenError):
        service.get_entry(
            entry.provider,
            entry.entry_key,
            target_language="zh-Hant",
            allow_provider=False,
        )

    cache.put(entry.provider, entry.word, entry.language, "zh-Hant", entry)
    fresh = service.get_entry(
        entry.provider, entry.entry_key, target_language="zh-Hant", allow_provider=False
    )
    assert fresh.cache_status == "fresh"
    assert fresh.entry is not None and fresh.entry.entry_key == entry.entry_key

    expired = LexicalCache(
        tmp_path / "lexical_cache.db", positive_ttl=timedelta(seconds=-1)
    )
    expired.put(entry.provider, entry.word, entry.language, "zh-Hant", entry)
    stale_service = LexicalService(provider=_ExplodingProvider(), cache=expired)
    stale = stale_service.get_entry(
        entry.provider, entry.entry_key, target_language="zh-Hant", allow_provider=False
    )
    assert stale.cache_status == "stale"
    assert stale.entry is not None
