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
    """A card with current_degree such that only K slots remain. The
    judge returns K+extra accepted candidates. The pipeline must:
      - create only K links (respect cap on the from-side),
      - record the over-cap accepted candidates in judge_log with
        accepted=False and reject_reason='degree_cap', so the audit
        trail explains why a semantically-accepted candidate didn't
        become a link.
    """
    judge_log = _fresh_judge_log(tmp_path, monkeypatch)

    from kg.vocab_graph import MAX_DEGREE
    from kg.pipeline_service import _step_embed_and_judge

    available_slots = 2
    # Seed c1 with (MAX_DEGREE - available_slots) existing active links so
    # it has exactly `available_slots` slots left.
    existing = [SimpleNamespace(id=f"existing{i}", status="active")
                for i in range(MAX_DEGREE - available_slots)]

    # 5 candidates — exceed remaining cap by 3.
    cand_ids = [f"c{i}" for i in range(2, 7)]
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

    # Patched Judge that accepts ALL candidates → forces pipeline to
    # enforce the cap and decide what to do with the surplus.
    import kg.judge as judge_mod
    orig_judge = judge_mod.Judge

    class CapJudge:
        def __init__(self, llm, **kwargs):
            self.user_id = kwargs.get("user_id", "")
            self.notebook_id = kwargs.get("notebook_id", "default")

        def evaluate_batch(self, target_word, target_meaning, candidates,
                           *, from_id="", similarities=None, max_links=None):
            # Accept every candidate.
            results = {}
            for cid, _, _ in candidates:
                results[cid] = Judgement(
                    link="shares_usage", confidence=0.9, reason="ok",
                )
            # Mirror the real Judge: write accepted entries to judge_log.
            from kg import judge_log as jl
            for cid, _, _ in candidates:
                jl.record(
                    user_id=self.user_id, notebook_id=self.notebook_id,
                    from_id=from_id, to_id=cid,
                    similarity=(similarities or {}).get(cid),
                    verdict="shares_usage", confidence=0.9,
                    accepted=True, reject_reason=None,
                    reason="ok", source="auto",
                )
            return results

    judge_mod.Judge = CapJudge
    try:
        asyncio.run(_step_embed_and_judge(
            "user_cap", {"id": "user_cap", "dir": Path("/tmp/user_cap"), "config": {}},
            card_store_factory=lambda d: cards,
            graph_store_factory=lambda d, notebook_id="default": graph,
            embedding_store_factory=lambda d, llm=None, notebook_id="default": embeddings,
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda v: v,
        ))
    finally:
        judge_mod.Judge = orig_judge

    # Only `available_slots` links should be created — cap respected.
    assert len(graph.created_links) == available_slots

    # Surplus candidates must be in judge_log as degree-cap rejects so
    # auditors can tell apart "LLM rejected" from "we ran out of room".
    rows = judge_log.get_log("user_cap", notebook_id="default", limit=100)
    cap_rejects = [r for r in rows if r["reject_reason"] == "degree_cap"]
    assert len(cap_rejects) == len(cand_ids) - available_slots, (
        f"Expected {len(cand_ids) - available_slots} degree_cap rejects, "
        f"got {len(cap_rejects)}; rows={rows}"
    )
    for r in cap_rejects:
        assert r["accepted"] is False
        assert r["from_id"] == "c1"
        assert r["to_id"] in cand_ids

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
