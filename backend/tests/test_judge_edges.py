"""Edge cases for batch judge.

Covers:
1. Partial LLM failure within a single batch — well-formed items succeed,
   malformed/missing items are recorded as rejections (no silent loss).
2. Pipeline degree cap — when a card has only K available slots but the
   judge returns > K accepted candidates, the extras are recorded in
   judge_log as auto-rejected with reject_reason='degree_cap'.
3. One-shot batch token savings vs N individual calls — characterization
   test that locks in the prompt-token reduction claim.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kg.judge import (
    BATCH_SYSTEM_PROMPT,
    BATCH_USER_TEMPLATE,
    Judge,
    Judgement,
)


# ── shared helpers ──────────────────────────────────────────────


def _mock_client_returning(content: str) -> MagicMock:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    mock_resp.usage = None
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


def _fresh_judge_log(tmp_path, monkeypatch):
    """Point judge_log at a fresh sqlite DB under tmp_path and reload."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()
    return judge_log


# ── Test 1: partial LLM failure ─────────────────────────────────


def test_batch_judge_partial_llm_failure_does_not_lose_pending_items(
    tmp_path, monkeypatch
):
    """Mixed batch response: 5 well-formed accepted items + 3 malformed
    items (missing required keys) + 2 truncated (missing from array).
    Every candidate must appear in judge_log so the caller can audit /
    re-queue. Well-formed accepted entries land with accepted=1; malformed
    and truncated entries land with accepted=0 and a non-null verdict
    indicating why.
    """
    judge_log = _fresh_judge_log(tmp_path, monkeypatch)

    candidates = [(f"c{i}", f"word_{i}", f"meaning_{i}") for i in range(10)]
    # 5 well-formed accepted, 3 malformed (no link / no confidence),
    # 2 truncated (array length only 8 → c8, c9 absent).
    items = []
    for i in range(5):
        items.append({
            "word": f"word_{i}",
            "link": "shares_usage",
            "confidence": 0.85,
            "reason": "ok",
        })
    # Malformed: keep `word` so positional/word-fallback still finds the slot
    # but drop `link` and `confidence` → parser falls back to defaults and
    # rejects as not_applicable / low_confidence.
    items.append({"word": "word_5", "reason": "missing fields"})
    items.append({"word": "word_6", "link": "shares_usage"})  # no confidence
    items.append({"word": "word_7", "confidence": 0.9})  # no link
    # c8, c9 missing entirely (truncated response).

    content = json.dumps(items)
    from kg.tracked_llm import TrackedLLM
    judge = Judge(
        llm=TrackedLLM(_mock_client_returning(content), "user_partial"),
        user_id="user_partial",
        notebook_id="nb_partial",
    )

    results = judge.evaluate_batch(
        "target", "target_meaning", candidates, from_id="from_x",
    )

    # 5 well-formed accepted
    accepted_ids = [cid for cid, j in results.items() if j is not None]
    assert sorted(accepted_ids) == [f"c{i}" for i in range(5)]
    # The other 5 are None (rejected)
    rejected_ids = [cid for cid, j in results.items() if j is None]
    assert sorted(rejected_ids) == [f"c{i}" for i in range(5, 10)]

    # judge_log must contain ALL 10 candidates — none silently dropped.
    rows = judge_log.get_log("user_partial", notebook_id="nb_partial", limit=100)
    assert len(rows) == 10
    by_id = {r["to_id"]: r for r in rows}
    assert set(by_id.keys()) == {f"c{i}" for i in range(10)}

    # Accepted entries
    for i in range(5):
        r = by_id[f"c{i}"]
        assert r["accepted"] is True
        assert r["verdict"] == "shares_usage"
        assert r["reject_reason"] is None

    # Malformed-but-positionally-present entries (c5, c6, c7) are rejected
    # via the natural reject paths (not_applicable / low_confidence) —
    # exact reject_reason depends on which field was missing, but they must
    # be accepted=False with a non-null reject_reason and non-empty verdict.
    for cid in ("c5", "c6", "c7"):
        r = by_id[cid]
        assert r["accepted"] is False
        assert r["reject_reason"] in {"not_applicable", "low_confidence", "invalid_kind"}

    # Truncated entries — recorded as no_response so the pipeline can tell
    # them apart from semantic rejections.
    for cid in ("c8", "c9"):
        r = by_id[cid]
        assert r["accepted"] is False
        assert r["verdict"] == "no_response"
        assert r["reject_reason"] == "no_response"

    judge_log._reset()


# ── Test 2: degree cap respected & logged ───────────────────────


def _make_card(cid, content, meaning):
    return SimpleNamespace(
        id=cid,
        content=content,
        meaning=meaning,
        pos="n.",
        note="",
        difficulty=None,
        is_deleted=False,
        is_archived=False,
        notebook_id="default",
        embed_text=lambda c=content: c,
    )


class _FakeCards:
    def __init__(self, cards):
        self._cards = {c.id: c for c in cards}
        self.touched_ids: set[str] = set()

    def all(self, include_deleted=False, notebook_id=None):
        return list(self._cards.values())

    def get_batch(self, ids):
        return {cid: self._cards[cid] for cid in ids if cid in self._cards}

    def touch(self, card_id):
        self.touched_ids.add(card_id)

    def batch_touch(self, card_ids, *, notebook_id=None):
        self.touched_ids.update(card_ids)


class _FakeEmbeddings:
    def __init__(self, has_ids, similar_map):
        self._has = set(has_ids)
        self._similar = similar_map

    def has(self, cid):
        return cid in self._has

    def add_batch(self, items):
        for cid, _ in items:
            self._has.add(cid)

    def find_similar(self, cid, k=12):
        return self._similar.get(cid, [])


class _FakeGraph:
    def __init__(self, *, pending=None, links=None):
        self._pending = list(pending or [])
        self._links = links or {}
        self.created_links: list = []

    def add_pending_judge(self, ids):
        self._pending.extend(ids)

    def pop_pending_judge(self):
        out = list(self._pending)
        self._pending.clear()
        return out

    def get_links_for(self, cid):
        return self._links.get(cid, [])

    def has_link(self, a, b):
        return False

    def batch_add_links(self, links):
        self.created_links.extend(links)
        return links


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg, *args, **kw):
        self.messages.append(("info", msg % args if args else msg))

    def warning(self, msg, *args, **kw):
        self.messages.append(("warning", msg % args if args else msg))

    def error(self, msg, *args, **kw):
        self.messages.append(("error", msg % args if args else msg))


def test_batch_judge_degree_cap_respected(tmp_path, monkeypatch):
    """A card with only K slots left where the **real** ``Judge.evaluate_batch``
    accepts all N candidates (N > K). The pipeline must:
      - create only K links (respect cap on the from-side),
      - flip the surplus rows that ``evaluate_batch`` already wrote as
        ``accepted=1`` into ``accepted=0, reject_reason='degree_cap'``,
      - end up with **N** rows total (no double-count) — exactly K with
        ``accepted=1`` and N-K with ``reject_reason='degree_cap'``,
      - report a model acceptance rate of K/K = 1.0 via
        ``get_acceptance_stats`` (cap evictions excluded).
    """
    judge_log = _fresh_judge_log(tmp_path, monkeypatch)

    from kg.vocab_graph import MAX_DEGREE
    from kg.pipeline_service import _step_embed_and_judge

    available_slots = 2
    existing = [SimpleNamespace(id=f"existing{i}", status="active")
                for i in range(MAX_DEGREE - available_slots)]

    cand_ids = [f"c{i}" for i in range(2, 7)]  # 5 candidates
    cards_list = [_make_card("c1", "target", "意義")] + [
        _make_card(cid, cid, f"m_{cid}") for cid in cand_ids
    ]
    cards = _FakeCards(cards_list)

    similar_map = {"c1": [(cid, 0.9) for cid in cand_ids]}
    embeddings = _FakeEmbeddings(
        has_ids={"c1", *cand_ids}, similar_map=similar_map,
    )
    graph = _FakeGraph(pending=["c1"], links={"c1": existing})
    logger = _FakeLogger()

    # Real Judge with a mocked LLM client returning an "accept all" batch
    # response. evaluate_batch will itself write accepted=1 rows for every
    # candidate — exactly the path that exposed the original double-count bug.
    accept_items = [
        {"word": cid, "link": "shares_usage", "confidence": 0.9, "reason": "ok"}
        for cid in cand_ids
    ]
    mock_client = _mock_client_returning(json.dumps(accept_items))

    asyncio.run(_step_embed_and_judge(
        "user_cap", {"id": "user_cap", "dir": Path("/tmp/user_cap"), "config": {}},
        card_store_factory=lambda d: cards,
        graph_store_factory=lambda d, notebook_id="default": graph,
        embedding_store_factory=lambda d, llm=None, notebook_id="default": embeddings,
        gemini_client_factory=lambda: mock_client,
        logger=logger,
        link_kind_enum=lambda v: v,
    ))

    # Cap respected on the from-side.
    assert len(graph.created_links) == available_slots

    rows = judge_log.get_log("user_cap", notebook_id="default", limit=100)
    by_id = {r["to_id"]: r for r in rows}

    # Every candidate is represented EXACTLY ONCE — no second row from
    # the degree_cap logger.
    assert set(by_id.keys()) == set(cand_ids), (
        f"Expected exactly one row per candidate, got rows={rows}"
    )
    assert len(rows) == len(cand_ids)

    cap_rejects = [r for r in rows if r["reject_reason"] == "degree_cap"]
    accepted = [r for r in rows if r["accepted"] and r["reject_reason"] is None]
    assert len(cap_rejects) == len(cand_ids) - available_slots
    assert len(accepted) == available_slots
    for r in cap_rejects:
        assert r["accepted"] is False
        assert r["from_id"] == "c1"
        assert r["to_id"] in cand_ids
        # Verdict from the LLM is preserved on the flipped row.
        assert r["verdict"] == "shares_usage"

    # Acceptance stats: cap evictions are NOT counted against the model.
    # K accepts survive, N-K are excluded → rate is 1.0.
    stats = judge_log.get_acceptance_stats(user_id="user_cap")
    assert stats["total"] == available_slots
    assert stats["accepted"] == available_slots
    assert stats["rate"] == 1.0

    judge_log._reset()


# ── Regression: get_acceptance_stats excludes degree_cap rejects ─


def test_judge_log_get_acceptance_stats_excludes_degree_cap_rejects(
    tmp_path, monkeypatch,
):
    """``get_acceptance_stats`` measures **model** decisions. Rows whose
    rejection came from a pipeline cap eviction (``reject_reason='degree_cap'``)
    are not model decisions and must not appear in the denominator.

    Seed 5 accepted + 1 model reject + 2 degree_cap rejects → model
    acceptance is 5 / (5+1) = 0.8333, NOT 5/8.
    """
    judge_log = _fresh_judge_log(tmp_path, monkeypatch)

    for i in range(5):
        judge_log.record(
            user_id="u_stats", notebook_id="nb", from_id="a", to_id=f"acc_{i}",
            similarity=0.8, verdict="shares_usage", confidence=0.9,
            accepted=True, reject_reason=None, reason="ok", source="auto",
        )
    judge_log.record(
        user_id="u_stats", notebook_id="nb", from_id="a", to_id="rej_model",
        similarity=0.6, verdict="not_applicable", confidence=0.3,
        accepted=False, reject_reason="low_confidence",
        reason="no link", source="auto",
    )
    for i in range(2):
        judge_log.record(
            user_id="u_stats", notebook_id="nb", from_id="a", to_id=f"cap_{i}",
            similarity=0.85, verdict="shares_usage", confidence=0.9,
            accepted=False, reject_reason="degree_cap",
            reason="ok", source="auto",
        )

    stats = judge_log.get_acceptance_stats(user_id="u_stats")
    # 5 accepted + 1 model reject in denominator; 2 cap rows excluded.
    assert stats["total"] == 6
    assert stats["accepted"] == 5
    assert stats["rejected"] == 1
    assert abs(stats["rate"] - (5 / 6)) < 1e-4

    # Global view: same exclusion applies.
    glob = judge_log.get_acceptance_stats()
    assert glob["total"] == 6
    assert glob["accepted"] == 5

    judge_log._reset()


# ── Regression: update_to_rejected flips the latest accepted row ─


def test_judge_log_update_to_rejected_flips_existing_row(tmp_path, monkeypatch):
    """``update_to_rejected`` must mutate the latest matching accepted
    row instead of inserting a new one — otherwise the pair gets
    double-counted in stats.
    """
    judge_log = _fresh_judge_log(tmp_path, monkeypatch)

    judge_log.record(
        user_id="u_upd", notebook_id="nb", from_id="x", to_id="y",
        similarity=0.9, verdict="shares_usage", confidence=0.92,
        accepted=True, reject_reason=None, reason="ok", source="auto",
    )

    updated = judge_log.update_to_rejected("x", "y", reason="degree_cap")
    assert updated is True

    rows = judge_log.get_log("u_upd", limit=10)
    assert len(rows) == 1  # no second row inserted
    assert rows[0]["accepted"] is False
    assert rows[0]["reject_reason"] == "degree_cap"
    # Verdict / confidence are preserved on the flipped row.
    assert rows[0]["verdict"] == "shares_usage"
    assert abs(rows[0]["confidence"] - 0.92) < 1e-6

    # Calling again with no matching accepted row returns False (idempotent).
    updated2 = judge_log.update_to_rejected("x", "y", reason="degree_cap")
    assert updated2 is False

    judge_log._reset()


# ── Test 3: one-shot token savings vs individual ────────────────


def test_one_shot_judge_token_savings_vs_individual():
    """Characterization: same N candidates evaluated as one batch call
    consume substantially fewer prompt characters than N individual calls.

    We use prompt-character count as a tokenization-agnostic proxy for
    token usage (the 86% saving claim was measured in tokens on a live
    Gemini run, see test_batch_judge_30pairs.py). For a deterministic
    unit test we lock in the **lower bound** of the saving on the actual
    prompts the codebase will send.
    """
    N = 10
    candidates = [(f"id_{i}", f"word_{i}", f"meaning_{i}") for i in range(N)]

    # ── Individual: N single-candidate calls, each carries the full
    # system prompt + a one-line user message.
    individual_prompt_chars = 0
    for _, w, m in candidates:
        cand_lines = f"1. {w} ({m})"
        user_msg = BATCH_USER_TEMPLATE.format(
            target_word="target", target_meaning="target_meaning",
            candidate_list=cand_lines,
        )
        individual_prompt_chars += len(BATCH_SYSTEM_PROMPT) + len(user_msg)

    # ── One-shot batch: single call with all N candidates.
    batch_cand_lines = "\n".join(
        f"{i+1}. {w} ({m})" for i, (_, w, m) in enumerate(candidates)
    )
    batch_user_msg = BATCH_USER_TEMPLATE.format(
        target_word="target", target_meaning="target_meaning",
        candidate_list=batch_cand_lines,
    )
    batch_prompt_chars = len(BATCH_SYSTEM_PROMPT) + len(batch_user_msg)

    saving = 1 - batch_prompt_chars / individual_prompt_chars

    # One-shot must be strictly cheaper.
    assert batch_prompt_chars < individual_prompt_chars

    # Lock in the saving lower bound at 80% (live measurement was 86%;
    # the unit-test proxy lands slightly lower because it ignores the
    # fixed assistant-response overhead each individual call carries).
    assert saving > 0.80, (
        f"Expected >80% prompt-char saving, got {saving:.1%} "
        f"(batch={batch_prompt_chars}, individual={individual_prompt_chars})"
    )

    # And there should be ONE prompt vs N — verify via the actual Judge
    # that batch mode issues a single LLM call regardless of N.
    from kg.tracked_llm import TrackedLLM
    mock_client = MagicMock()
    items = [{"word": w, "link": "shares_usage", "confidence": 0.8, "reason": "r"}
             for _, w, _ in candidates]
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = json.dumps(items)
    mock_resp.usage = None
    mock_client.chat.completions.create.return_value = mock_resp

    judge = Judge(llm=TrackedLLM(mock_client, "user_token"))
    results = judge.evaluate_batch("target", "target_meaning", candidates)

    assert mock_client.chat.completions.create.call_count == 1
    assert len(results) == N
    assert all(j is not None for j in results.values())
