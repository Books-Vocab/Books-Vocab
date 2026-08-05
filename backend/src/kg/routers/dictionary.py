from __future__ import annotations

import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, Query, Request, Response

from ..api_models import (
    DictionaryArchiveRequest,
    DictionaryEntryResponse,
    DictionaryMaterializeRequest,
    DictionaryProjectionItem,
    DictionaryPromotionResponse,
    DictionarySearchHit,
    DictionarySearchResponse,
    DictionarySelectionRequest,
    MaterializeLinkResult,
    ReaderVisibilityRequest,
    SavedDictionaryCard,
)
from ..deps import CurrentUser, _card_store, _graph_store, _notebook_store
from ..dictionary_cards import (
    DictionaryCardNode,
    DictionaryCardService,
    completed_materialize_replay,
    has_persisted_materialize_judgement,
)
from ..dictionary_promotion import (
    DictionaryPromotionService,
    promotion_enrichment_from_result,
)
from ..exceptions import BadRequestError, ForbiddenError, KGError
from ..lexical import (
    FreeDictionaryProvider,
    LexicalCache,
    LexicalService,
    dictionary_rate_limiter,
)
from ..notebook import validate_notebook_access
from ..settings import KGSettings

router = APIRouter(tags=["dictionary"])


class DictionaryRateLimitError(KGError):
    status_code = 429


class _DictionaryLookupLeases:
    """One-shot bridge from an admitted search to its immediate detail fetch.

    Add Link submits one explicit search, then opens the returned entry. Counting
    both HTTP requests would charge the same user action twice. A short-lived,
    one-shot lease makes that pair one admission while repeated/direct detail
    calls continue through the normal limiter.
    """

    def __init__(self, ttl_seconds: float = 120.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._expires: dict[tuple[str, str, str], float] = {}

    def grant(self, user_id: str, provider: str, entry_key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._expires[(user_id, provider, entry_key)] = now + self.ttl_seconds

    def consume(self, user_id: str, provider: str, entry_key: str) -> bool:
        now = time.monotonic()
        key = (user_id, provider, entry_key)
        with self._lock:
            self._prune(now)
            expires = self._expires.pop(key, None)
            return expires is not None and expires > now

    def _prune(self, now: float) -> None:
        expired = [key for key, expiry in self._expires.items() if expiry <= now]
        for key in expired:
            self._expires.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._expires.clear()


dictionary_lookup_leases = _DictionaryLookupLeases()


@lru_cache(maxsize=8)
def _build_lexical_service(
    cache_path: str, positive_ttl_days: int, negative_ttl_hours: int
) -> LexicalService:
    from datetime import timedelta

    return LexicalService(
        provider=FreeDictionaryProvider(),
        cache=LexicalCache(
            Path(cache_path),
            positive_ttl=timedelta(days=positive_ttl_days),
            negative_ttl=timedelta(hours=negative_ttl_hours),
        ),
    )


def _lexical_service(settings: KGSettings) -> LexicalService:
    if settings.dictionary_provider_default != "free_dictionary":
        raise ForbiddenError("Configured dictionary provider is not enabled")
    return _build_lexical_service(
        str(settings.data_dir / "lexical_cache.db"),
        settings.dictionary_cache_ttl_days,
        settings.dictionary_negative_cache_ttl_hours,
    )


def _require_enabled(settings: KGSettings) -> None:
    if not settings.dictionary_lookup_enabled:
        raise ForbiddenError("Dictionary lookup is disabled")


def _admit(user_id: str) -> None:
    if not dictionary_rate_limiter.admit(user_id):
        raise DictionaryRateLimitError(
            "Dictionary search rate limit exceeded", headers={"Retry-After": "60"}
        )


def _manual_judge(user: dict, notebook_id: str):
    from ..deps_quota import _is_pro
    from ..judge import ManualLinkJudge
    from ..llm.providers import provider_for
    from ..service_factories import create_client
    from ..tracked_llm import TrackedLLM

    provider = provider_for("judge_manual")
    return ManualLinkJudge(
        TrackedLLM(
            create_client(provider),
            user["id"],
            provider=provider,
            enforce_quota=True,
            is_pro=_is_pro(user),
        ),
        model=provider.chat_model,
        user_id=user["id"],
        notebook_id=notebook_id,
    )


def _dictionary_card_service(
    user: dict,
    settings: KGSettings,
    *,
    notebook_id: str = "default",
    validate_notebook: bool = False,
    require_mutation_dependencies: bool = False,
) -> DictionaryCardService:
    if validate_notebook:
        validate_notebook_access(_notebook_store(user["dir"]), notebook_id)
    return DictionaryCardService(
        cards=_card_store(user["dir"]),
        graph=_graph_store(user["dir"], notebook_id=notebook_id),
        lexical=_lexical_service(settings) if require_mutation_dependencies else None,
        judge=_manual_judge(user, notebook_id) if require_mutation_dependencies else None,
        graph_resolver=lambda resolved_notebook_id: _graph_store(
            user["dir"], notebook_id=resolved_notebook_id
        ),
    )


def _dictionary_promotion_service(user: dict) -> DictionaryPromotionService:
    """Wire the durable promotion worker to existing enrichment/pipeline code."""
    from ..deps import _embedding_store, logger
    from ..deps_quota import _is_pro
    from ..difficulty import get_zipf
    from ..enrich import enrich_cards_stream
    from ..graph import LinkKind
    from ..llm.providers import provider_for
    from ..pipeline_service.steps import _step_embed_and_judge
    from ..service_factories import create_client
    from ..tracked_llm import TrackedLLM
    from ..vocab_shared import _normalize_pos

    cards = _card_store(user["dir"])

    async def enrich_one(target):
        provider = provider_for("enrich")
        llm = TrackedLLM(
            create_client(provider),
            user["id"],
            provider=provider,
            enforce_quota=True,
            is_pro=_is_pro(user),
        )
        result = None
        async for message in enrich_cards_stream(
            llm,
            [target],
            batch_size=1,
            max_workers=1,
            model=provider.chat_model,
        ):
            if message.get("status") == "error":
                raise RuntimeError("Dictionary promotion enrichment failed")
            for item in message.get("results") or []:
                if item.get("word", "").casefold() == target.content.casefold():
                    result = item
        if result is None:
            raise ValueError("Dictionary promotion enrichment returned no matching word")
        return promotion_enrichment_from_result(
            target,
            result,
            normalize_pos=_normalize_pos,
        )

    async def stage_b(promoted):
        await _step_embed_and_judge(
            user["id"],
            user,
            card_store_factory=_card_store,
            graph_store_factory=_graph_store,
            embedding_store_factory=_embedding_store,
            client_factory=create_client,
            logger=logger,
            link_kind_enum=LinkKind,
            notebook_id=promoted.notebook_id,
        )

    return DictionaryPromotionService(
        cards=cards,
        enrich=enrich_one,
        difficulty=lambda word: get_zipf(word),
        stage_b=stage_b,
    )


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequestError("Malformed dictionary since timestamp") from exc


@router.get("/api/dictionary/search", response_model=DictionarySearchResponse)
def search_dictionary(
    request: Request,
    user: CurrentUser,
    q: str = Query(min_length=1, max_length=200),
    source_lang: Literal["en"] = "en",
    target_lang: Literal["zh-Hant"] = "zh-Hant",
):
    settings: KGSettings = request.app.state.kg_settings
    _require_enabled(settings)
    _admit(user["id"])
    result = _lexical_service(settings).search(
        q, source_language=source_lang, target_language=target_lang
    )
    hits: list[DictionarySearchHit] = []
    if result.entry is not None:
        entry = result.entry
        dictionary_lookup_leases.grant(user["id"], entry.provider, entry.entry_key)
        parts = list(dict.fromkeys(s.part_of_speech for s in entry.senses if s.part_of_speech))
        hits.append(
            DictionarySearchHit(
                provider=entry.provider,
                dictionaryId=entry.dictionary_id,
                entryKey=entry.entry_key,
                word=entry.word,
                language=entry.language,
                partsOfSpeech=parts,
                hasExamples=any(s.examples for s in entry.senses),
                attribution=entry.attribution,
            )
        )
    return DictionarySearchResponse(hits=hits, cacheStatus=result.cache_status)


@router.get(
    "/api/dictionary/entries/{provider}/{entry_key}",
    response_model=DictionaryEntryResponse,
)
def get_dictionary_entry(
    provider: str,
    entry_key: str,
    request: Request,
    user: CurrentUser,
    target_lang: Literal["zh-Hant"] = "zh-Hant",
):
    settings: KGSettings = request.app.state.kg_settings
    _require_enabled(settings)
    if not dictionary_lookup_leases.consume(user["id"], provider, entry_key):
        _admit(user["id"])
    result = _lexical_service(settings).get_entry(
        provider, entry_key, target_language=target_lang
    )
    return DictionaryEntryResponse(entry=result.entry, cacheStatus=result.cache_status)


@router.get("/api/dictionary/cards/{card_id}", response_model=SavedDictionaryCard)
def get_saved_dictionary_card(card_id: str, request: Request, user: CurrentUser):
    settings: KGSettings = request.app.state.kg_settings
    return _dictionary_card_service(user, settings).get_saved_card(card_id)


@router.get("/api/dictionary-cards", response_model=list[DictionaryProjectionItem])
def list_dictionary_cards(
    response: Response,
    request: Request,
    user: CurrentUser,
    since: str | None = None,
    notebook_id: str | None = Query(None, pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    cursor: str | None = None,
    limit: int = Query(5000, ge=1, le=10000),
):
    settings: KGSettings = request.app.state.kg_settings
    if notebook_id is not None:
        validate_notebook_access(_notebook_store(user["dir"]), notebook_id)
    projection = _dictionary_card_service(
        user, settings, notebook_id=notebook_id or "default"
    ).list_projection(
        notebook_id=notebook_id,
        limit=limit,
        since=_parse_since(since),
        cursor=cursor,
    )
    if projection.next_cursor:
        response.headers["X-Next-Cursor"] = projection.next_cursor
    return projection.items


@router.patch(
    "/api/dictionary/cards/{card_id}/selection", response_model=SavedDictionaryCard
)
def update_dictionary_selection(
    card_id: str,
    body: DictionarySelectionRequest,
    request: Request,
    user: CurrentUser,
):
    settings: KGSettings = request.app.state.kg_settings
    return _dictionary_card_service(user, settings).update_selection(
        card_id, sense_key=body.sense_key, example_key=body.example_key
    )


@router.patch(
    "/api/dictionary/cards/{card_id}/archive", response_model=DictionaryCardNode
)
def archive_dictionary_card(
    card_id: str,
    body: DictionaryArchiveRequest,
    request: Request,
    user: CurrentUser,
):
    settings: KGSettings = request.app.state.kg_settings
    return _dictionary_card_service(
        user,
        settings,
        notebook_id=body.notebook_id,
        validate_notebook=True,
    ).set_archived(
        card_id,
        notebook_id=body.notebook_id,
        archived=body.archived,
    )


@router.delete("/api/dictionary/cards/{card_id}", response_model=DictionaryCardNode)
def delete_dictionary_card(
    card_id: str,
    request: Request,
    user: CurrentUser,
    notebook_id: str = Query(pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    settings: KGSettings = request.app.state.kg_settings
    return _dictionary_card_service(
        user,
        settings,
        notebook_id=notebook_id,
        validate_notebook=True,
    ).soft_delete(card_id, notebook_id=notebook_id)


@router.patch("/api/cards/{card_id}/reader-visibility", response_model=DictionaryCardNode)
def update_reader_visibility(
    card_id: str,
    body: ReaderVisibilityRequest,
    request: Request,
    user: CurrentUser,
):
    settings: KGSettings = request.app.state.kg_settings
    return _dictionary_card_service(user, settings).set_reader_visibility(
        card_id, reader_hidden=body.reader_hidden
    )


@router.post(
    "/api/dictionary/cards/{card_id}/promote",
    response_model=DictionaryPromotionResponse,
)
async def promote_dictionary_card(
    card_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
):
    service = _dictionary_promotion_service(user)
    result = service.request(card_id)
    if not result.already_promoted:
        background_tasks.add_task(service.run, card_id)
    return DictionaryPromotionResponse(
        cardId=result.card_id,
        cardRole=result.card_role,
        promotionState=result.promotion_state,
        alreadyPromoted=result.already_promoted,
    )


@router.post("/api/graph/links/from-dictionary", response_model=MaterializeLinkResult)
def materialize_dictionary_link(
    body: DictionaryMaterializeRequest,
    response: Response,
    request: Request,
    user: CurrentUser,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
):
    from ..deps_quota import _apply_quota_headers, _check_quota

    settings: KGSettings = request.app.state.kg_settings
    request_values = {
        "source_card_id": body.source_card_id,
        "notebook_id": body.notebook_id,
        "provider": body.provider,
        "entry_key": body.entry_key,
        "sense_key": body.sense_key,
        "example_key": body.example_key,
    }
    replay = completed_materialize_replay(
        cards=_card_store(user["dir"]),
        idempotency_key=idempotency_key,
        request_values=request_values,
    )
    if replay is not None:
        return replay
    _require_enabled(settings)
    resumes_after_judge = has_persisted_materialize_judgement(
        cards=_card_store(user["dir"]),
        idempotency_key=idempotency_key,
        request_values=request_values,
    )
    quota = None if resumes_after_judge else _check_quota(user, "manual_link", response)
    result = _dictionary_card_service(
        user,
        settings,
        notebook_id=body.notebook_id,
        validate_notebook=True,
        require_mutation_dependencies=True,
    ).materialize_and_link(
        idempotency_key=idempotency_key,
        source_card_id=body.source_card_id,
        notebook_id=body.notebook_id,
        provider=body.provider,
        entry_key=body.entry_key,
        sense_key=body.sense_key,
        example_key=body.example_key,
    )
    if quota is not None:
        _apply_quota_headers(response, quota)
    return result
