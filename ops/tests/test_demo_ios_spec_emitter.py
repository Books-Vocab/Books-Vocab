"""Spec-driven emit-ios (kg.seed_spec.v1 -> UI World v2) contract tests.

Covers the Phase 2/6 UI World seed projector:
  * spec mode derives vocabulary / notebook / reviewDeck / todayReview from the
    seed spec; every other domain stays byte-equal to the committed baseline
    (ops/fixtures/ui_worlds/marketing_demo.json) + identity auth overlay.
  * output passes the shared ui_world_manifest validator and is byte-stable.
  * baseline emit-ios (no --spec) and its --check drift gate are frozen.
  * end-to-end: ops_edit seed (sandbox) -> ops_cli world-export -> emit --spec.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "ops" / "demo"
BACKEND_DIR = ROOT / "backend"
BASELINE_PATH = ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"

SPEC_DOMAINS = ("vocabulary", "notebook", "reviewDeck", "todayReview")

# Catalog scenario / UITest seed seam 釘死特定內容/形狀的 fixtures（SoT 註解見
# emit_ios.SPEC_BASELINE_KEPT_FIXTURES）：任意合法 spec 無法保證命中 →
# spec 模式必須保留 baseline，不得投影。
CONTENT_PINNED_FIXTURES = (
    ("vocabulary", "wordDetail"),
    ("vocabulary", "wordEdit"),
    ("vocabulary", "searchVocabNotebook"),
    ("vocabulary", "kgVocabRow"),
    ("vocabulary", "vocabLinkedCards"),
    ("vocabulary", "archivedPopulated"),
    ("vocabulary", "archivedSingle"),
    ("vocabulary", "archivedLong"),
    # UITest seam pins（NotebookReviewFlowUITests: probeword 前綴 + 量測卡片配對）
    ("reviewDeck", "probe"),
    ("reviewDeck", "notebookReviewDeck"),
)


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, DEMO_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(DEMO_DIR))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(DEMO_DIR))
        except ValueError:
            pass
    return module


sot = _load_module("sot")
spec_world = _load_module("spec_world")
emit_ios = _load_module("emit_ios")
build_demo = _load_module("build_demo")


# --------------------------------------------------------------------------- #
# spec fixtures
# --------------------------------------------------------------------------- #
def _card(
    content: str,
    notebook: str,
    *,
    mode: str = "recognition",
    is_archived: bool = False,
    review_count: int = 0,
    review_streak: int = 0,
    lapse_count: int = 0,
    interval: float = 12.0,
    next_review_at: str | None = None,
    last_reviewed_at: str | None = None,
    last_feedback: int = -1,
) -> dict:
    return {
        "content": content,
        "pos": "n.",
        "meaning": f"{content} 的意思",
        "examples": [f"The word **{content}** appears in a real sentence."],
        "collocations": [f"{content} pattern"],
        "note": None,
        "difficulty": 4.5,
        "mode": mode,
        "root_form": None,
        "inflections": [],
        "notebook": notebook,
        "is_archived": is_archived,
        "review": {
            "review_count": review_count,
            "review_streak": review_streak,
            "lapse_count": lapse_count,
            "review_interval_hours": interval,
            "next_review_at": next_review_at,
            "last_reviewed_at": last_reviewed_at,
            "last_review_feedback": last_feedback,
        },
    }


def _small_spec() -> dict:
    """2 notebooks, 4 active + 1 archived cards in the primary, 2 links."""
    nb, side = "Primary Notebook", "Side Notes"
    return {
        "schema": "kg.seed_spec.v1",
        "notebooks": [
            {"name": nb, "color": "#4F7C73", "cover_pattern": "waves",
             "sort_order": 0, "is_default": True},
            {"name": side, "color": None, "cover_pattern": None,
             "sort_order": 1, "is_default": False},
        ],
        "cards": [
            _card("alpha", nb, review_count=4, review_streak=2, lapse_count=1,
                  interval=48.0, next_review_at="2026-06-01T00:00:00+00:00",
                  last_reviewed_at="2026-05-30T12:00:00+00:00", last_feedback=1),
            _card("bravo", nb, mode="production", review_count=2, review_streak=1,
                  interval=24.0, next_review_at="2026-06-02T00:00:00+00:00",
                  last_reviewed_at="2026-05-31T09:00:00+00:00", last_feedback=1),
            _card("charlie", nb),
            _card("delta", nb, is_archived=True, review_count=1,
                  last_reviewed_at="2026-05-01T00:00:00+00:00", last_feedback=0),
            _card("echo", side),
        ],
        "links": [
            {"from": "alpha", "to": "bravo", "kind": "shares_usage",
             "confidence": 0.9, "reason": "related usage", "notebook": nb},
            {"from": "alpha", "to": "charlie", "kind": "contrasts_with",
             "confidence": 0.6, "reason": "contrast", "notebook": nb},
        ],
    }


def _big_spec(n: int = 636) -> dict:
    notebooks = [
        {"name": f"Deck {i}", "color": "#4F7C73", "cover_pattern": "waves",
         "sort_order": i, "is_default": i == 0}
        for i in range(3)
    ]
    cards, links = [], []
    for i in range(n):
        nb = notebooks[i % 3]["name"]
        word = f"word{i:04d}"
        count = i % 9
        cards.append(_card(
            word, nb,
            mode="production" if i % 7 == 0 else "recognition",
            is_archived=i % 20 == 19,
            review_count=count,
            review_streak=min(count, i % 4),
            lapse_count=count // 3,
            interval=12.0 * (1 + i % 5),
            next_review_at=(f"2026-06-{1 + i % 28:02d}T08:00:00+00:00" if i % 3 else None),
            last_reviewed_at=(f"2026-05-{1 + i % 28:02d}T08:00:00+00:00" if count else None),
            last_feedback=-1 if count == 0 else i % 2,
        ))
        if i % 3 == 0 and i + 3 < n:
            links.append({
                "from": word, "to": f"word{i + 3:04d}",
                "kind": "shares_usage" if i % 6 else "contrasts_with",
                "confidence": 0.5 + (i % 50) / 100,
                "reason": f"link {i}", "notebook": nb,
            })
    return {"schema": "kg.seed_spec.v1", "notebooks": notebooks,
            "cards": cards, "links": links}


def _write_spec(tmp_path: Path, payload: dict, name: str = "spec.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def _emit_spec_bytes(tmp_path: Path, payload: dict) -> bytes:
    spec_path = _write_spec(tmp_path, payload)
    bundle = sot.load_sot()
    [(path, content)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "fixture.json")
    assert path == tmp_path / "fixture.json"
    return content


def _baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# guard rails
# --------------------------------------------------------------------------- #
def test_spec_mode_requires_both_spec_and_out(tmp_path):
    bundle = sot.load_sot()
    spec_path = _write_spec(tmp_path, _small_spec())
    with pytest.raises(ValueError, match="--spec .*--out|--out .*--spec"):
        emit_ios.emit(bundle, spec_path=spec_path)
    with pytest.raises(ValueError, match="--spec .*--out|--out .*--spec"):
        emit_ios.emit(bundle, out_path=tmp_path / "fixture.json")


def test_load_seed_spec_rejects_wrong_schema(tmp_path):
    payload = _small_spec()
    payload["schema"] = "kg.demo_dataset.v1"
    spec_path = _write_spec(tmp_path, payload)
    with pytest.raises(spec_world.SpecWorldError, match="kg.seed_spec.v1"):
        spec_world.load_seed_spec(spec_path)


def test_load_seed_spec_rejects_link_to_unknown_card(tmp_path):
    payload = _small_spec()
    payload["links"].append({
        "from": "alpha", "to": "ghost", "kind": "shares_usage",
        "confidence": 0.5, "reason": "dangling", "notebook": "Primary Notebook",
    })
    spec_path = _write_spec(tmp_path, payload)
    with pytest.raises(spec_world.SpecWorldError, match="ghost"):
        spec_world.load_seed_spec(spec_path)


def test_spec_mode_requires_active_card_in_primary_notebook(tmp_path):
    # primary = 最多 active 卡的 notebook；全部卡都 archived -> 無法投影 -> fail-loud
    payload = _small_spec()
    for card in payload["cards"]:
        card["is_archived"] = True
    spec_path = _write_spec(tmp_path, payload)
    bundle = sot.load_sot()
    with pytest.raises(ValueError, match="active"):
        emit_ios._spec_artifacts(
            bundle, spec_path=spec_path, out_path=tmp_path / "fixture.json")


# --------------------------------------------------------------------------- #
# projection contract
# --------------------------------------------------------------------------- #
def test_spec_mode_derives_spec_domains_and_keeps_baseline_domains(tmp_path):
    content = _emit_spec_bytes(tmp_path, _small_spec())
    document = json.loads(content)
    baseline = _baseline()

    assert document["schema"] == "kg.fixture.dataset.v2"
    assert document["datasetID"].startswith("spec-")

    # non-spec domains stay byte-equal to the baseline（scenarioContext 為 spec/plan
    # 驅動 overlay，與 auth/datasetID 同排除）
    for key in sorted(set(document) - {"datasetID", "auth", "scenarioContext", *SPEC_DOMAINS}):
        assert document[key] == baseline[key], f"domain {key} drifted from baseline"

    # identity overlay identical to baseline mode
    signed_in = document["auth"]["signedIn"]
    identity = sot.load_identity()
    assert signed_in["userId"] == identity["user_id"]
    assert signed_in["token"] == identity["access_token"]

    # vocabulary: populated list mirrors the primary notebook's active cards
    populated = document["vocabulary"]["vocabListPopulated"]
    assert [e["word"] for e in populated["entries"]] == ["alpha", "bravo", "charlie"]
    assert populated["notebookName"] == "Primary Notebook"
    assert all(e["syncStatus"] == 1 and e["actionType"] == "add"
               and e["isArchived"] is False for e in populated["entries"])
    alpha = populated["entries"][0]
    assert alpha["reviewCount"] == 4
    assert alpha["reviewStreak"] == 2
    assert alpha["reviewIntervalHours"] == 48.0
    assert alpha["nextReviewAt"] == "2026-06-01T00:00:00Z"
    assert alpha["lastReviewedAt"] == "2026-05-30T12:00:00Z"
    assert alpha["reviewMode"] == "recognition"
    assert alpha["translation"] == "alpha 的意思"

    # archived views are content-pinned by ArchivedVocabScenarios (≥5 / ==1 / ≥40)
    # -> spec mode keeps them baseline instead of projecting (see
    # test_spec_mode_keeps_content_pinned_vocabulary_fixtures_baseline)
    assert document["vocabulary"]["archivedPopulated"] == baseline["vocabulary"]["archivedPopulated"]

    # notebook rows mirror the spec notebooks
    rows = document["notebook"]["populated"]["notebooks"]
    assert [(r["name"], r["isDefault"], r["sortOrder"]) for r in rows] == [
        ("Primary Notebook", True, 0), ("Side Notes", False, 1)]
    assert rows[0]["coverPattern"] == "waves"
    assert rows[0]["color"] == "#4F7C73"
    assert [e["word"] for e in rows[0]["entries"]] == ["alpha", "bravo", "charlie"]
    assert len({r["remoteId"] for r in rows}) == 2

    # reviewDeck: due order = scheduled first (by nextReviewAt), then unscheduled
    deck = document["reviewDeck"]["phaseMulti"]
    assert [e["word"] for e in deck["entries"]] == ["alpha", "bravo", "charlie"]
    assert deck["notebookName"] == "Primary Notebook"
    assert [e["word"] for e in document["reviewDeck"]["phaseSingle"]["entries"]] == ["alpha"]
    # probe / notebookReviewDeck 是 UITest 量測 deck（probeword content-pin）→ 保留 baseline
    assert document["reviewDeck"]["probe"] == baseline["reviewDeck"]["probe"]
    assert document["reviewDeck"]["notebookReviewDeck"] == baseline["reviewDeck"]["notebookReviewDeck"]


def test_spec_mode_notebook_entries_carry_review_scheduling(tmp_path):
    # Notebook list 徽章/進度條資料面：notebook entry 投影必須帶 review
    # scheduling 欄位（否則列表徽章=總卡數、進度條全空）。
    content = _emit_spec_bytes(tmp_path, _small_spec())
    document = json.loads(content)

    rows = document["notebook"]["populated"]["notebooks"]
    by_word = {e["word"]: e for e in rows[0]["entries"]}
    alpha = by_word["alpha"]
    assert alpha["reviewCount"] == 4
    assert alpha["reviewIntervalHours"] == 48.0
    assert alpha["nextReviewAt"] == "2026-06-01T00:00:00Z"
    assert alpha["lastReviewedAt"] == "2026-05-30T12:00:00Z"
    charlie = by_word["charlie"]
    assert charlie["reviewCount"] == 0
    assert charlie["reviewIntervalHours"] == 12.0
    assert charlie["nextReviewAt"] is None
    assert charlie["lastReviewedAt"] is None

    single = document["notebook"]["single"]["notebooks"][0]
    assert {e["word"]: e["reviewCount"] for e in single["entries"]}["alpha"] == 4


def test_spec_mode_fixture_id_key_sets_match_baseline_and_whitelist_kept(tmp_path):
    content = _emit_spec_bytes(tmp_path, _small_spec())
    document = json.loads(content)
    baseline = _baseline()

    for domain in SPEC_DOMAINS:
        assert set(document[domain]) == set(baseline[domain]), domain

    # account-data-independent UI chrome fixtures stay byte-equal to baseline
    for domain, fixture_id in emit_ios.SPEC_BASELINE_KEPT_FIXTURES:
        assert document[domain][fixture_id] == baseline[domain][fixture_id], (
            f"{domain}.{fixture_id} should stay baseline")


def test_spec_mode_today_review_invariants(tmp_path):
    content = _emit_spec_bytes(tmp_path, _small_spec())
    today = json.loads(content)["todayReview"]

    front = today["front"]
    assert front["revealStage"] == "front"
    assert front["currentCard"]["word"] == "alpha"
    assert front["nextCard"]["word"] == "bravo"
    assert front["remainingCount"] >= 1
    assert front["canGoPrevious"] is False

    back = today["back"]
    assert back["revealStage"] == "back"
    assert back["currentCard"]["word"] == front["currentCard"]["word"]

    completed = today["completed"]
    assert completed["currentCard"] is None
    assert completed["nextCard"] is None
    assert completed["remainingCount"] == 0
    assert completed["forgotCount"] + completed["rememberedCount"] == 3

    autoplay = today["autoplay"]
    assert autoplay["isAutoPlaying"] is True and autoplay["isAutoPlayPaused"] is False
    paused = today["autoplayPaused"]
    assert paused["isAutoPlaying"] is True and paused["isAutoPlayPaused"] is True

    # production fixtures surface production-mode cards
    assert today["productionFront"]["currentCard"]["reviewMode"] == "production"
    assert today["productionBack"]["revealStage"] == "back"


def test_spec_mode_today_review_cards_declare_non_null_date_added(tmp_path):
    """Swift TodayReviewCardSeed.dateAdded 是非 optional Date（FixtureDatasetStore
    decode contract）→ 投影出的每張 session 卡 dateAdded 必須非空可解析。"""
    from datetime import datetime as _dt

    content = _emit_spec_bytes(tmp_path, _small_spec())
    today = json.loads(content)["todayReview"]
    kept = {f for d, f in emit_ios.SPEC_BASELINE_KEPT_FIXTURES if d == "todayReview"}
    checked = 0
    for fixture_id, seed in today.items():
        if fixture_id in kept:
            continue
        for key in ("currentCard", "nextCard"):
            card = seed[key]
            if card is None:
                continue
            assert card["dateAdded"], f"todayReview.{fixture_id}.{key}.dateAdded must be non-null"
            _dt.strptime(card["dateAdded"], "%Y-%m-%dT%H:%M:%SZ")
            checked += 1
    assert checked >= 8  # front/back/autoplay*/production* 的 current+next 都要被驗到


def test_spec_mode_date_added_precedes_first_synth_review_event(tmp_path):
    content = _emit_spec_bytes(tmp_path, _small_spec())
    document = json.loads(content)
    front = document["todayReview"]["front"]
    assert front["currentCard"]["word"] == "alpha"
    history = document["vocabulary"]["reviewCalendarDense"]["reviewHistory"]
    alpha_events = [r["reviewedAt"] for r in history if r["word"] == "alpha"]
    assert alpha_events
    assert front["currentCard"]["dateAdded"] < min(alpha_events)


def test_spec_mode_date_added_deterministic_fallback_without_review_dates(tmp_path):
    """spec 完全無 review 日期素材時，dateAdded 落到固定錨點（禁 Date.now/隨機）。"""
    payload = _small_spec()
    for card in payload["cards"]:
        card["review"] = {
            "review_count": 0, "review_streak": 0, "lapse_count": 0,
            "review_interval_hours": 12.0, "next_review_at": None,
            "last_reviewed_at": None, "last_review_feedback": -1,
        }
    content = _emit_spec_bytes(tmp_path, payload)
    front = json.loads(content)["todayReview"]["front"]
    assert front["currentCard"]["dateAdded"] == spec_world._DATE_ADDED_FALLBACK_ANCHOR
    assert content == _emit_spec_bytes(tmp_path, payload)  # byte-stable


def test_spec_mode_keeps_content_pinned_fixtures_baseline(tmp_path):
    spec_path = _write_spec(tmp_path, _small_spec())
    domains, _stats = spec_world.derive_domains(spec_world.load_seed_spec(spec_path))
    for domain, fixture_id in CONTENT_PINNED_FIXTURES:
        assert fixture_id not in domains[domain], (
            f"{domain}.{fixture_id} is content-pinned and must not be spec-derived")

    kept = set(emit_ios.SPEC_BASELINE_KEPT_FIXTURES)
    assert set(CONTENT_PINNED_FIXTURES) <= kept

    content = _emit_spec_bytes(tmp_path, _small_spec())
    document = json.loads(content)
    baseline = _baseline()
    for domain, fixture_id in CONTENT_PINNED_FIXTURES:
        assert document[domain][fixture_id] == baseline[domain][fixture_id], (
            f"{domain}.{fixture_id} must stay byte-equal to baseline in spec mode")


def test_spec_mode_date_added_anchor_fallback_without_history(tmp_path):
    """階梯第 2 級：無合成 history（review_count=0）但有 next_review_at →
    dateAdded = 錨點往前 _DATE_ADDED_LEAD_HOURS。"""
    payload = _small_spec()
    for card in payload["cards"]:
        card["review"] = {
            "review_count": 0, "review_streak": 0, "lapse_count": 0,
            "review_interval_hours": 12.0,
            "next_review_at": "2026-06-10T08:00:00+00:00",
            "last_reviewed_at": None, "last_review_feedback": -1,
        }
    content = _emit_spec_bytes(tmp_path, payload)
    front = json.loads(content)["todayReview"]["front"]
    assert front["currentCard"]["dateAdded"] == "2026-06-09T08:00:00Z"  # 錨點 - 24h


def test_spec_mode_prunes_graph_links_to_in_seed_targets(tmp_path):
    """KnowledgeGraphViewScenarios 驗 graph link cardId 必 resolve 同 seed entries
    （KnowledgeGraphViewScenarios.swift:199）→ 子集 seed 的 links 必須 prune 到
    子集內 target；全量 seed 保留完整 links。"""
    content = _emit_spec_bytes(tmp_path, _small_spec())
    vocab = json.loads(content)["vocabulary"]

    # 全量 populated：alpha 的兩條 link（bravo/charlie 皆在 seed）保留
    populated = {e["word"]: e for e in vocab["vocabListPopulated"]["entries"]}
    assert set(populated["alpha"]["graphLinksByKind"]) == {"contrasts_with", "shares_usage"}

    # 單卡子集：alpha 的 link target（bravo/charlie）不在 seed → 全 prune
    single = vocab["vocabListSingle"]["entries"]
    assert [e["word"] for e in single] == ["alpha"]
    assert single[0]["graphLinksByKind"] == {}

    # 大 spec（merge 後完整文件，kgVocabRow 為 baseline kept、一併驗其自足）：
    # 子集 seed 必須 link 自足（word + cardId 都 in-seed）
    big = json.loads(_emit_spec_bytes(tmp_path, _big_spec(636)))
    for fixture_id in ("knowledgeGraphPopulated", "vocabListSingle", "kgVocabRow"):
        seed = big["vocabulary"][fixture_id]
        words = {e["word"] for e in seed["entries"]}
        ids = {e["kgCardId"] for e in seed["entries"]}
        for entry in seed["entries"]:
            for links in entry["graphLinksByKind"].values():
                for link in links:
                    assert link["word"] in words, f"{fixture_id}: dangling word {link['word']}"
                    assert link["cardId"] in ids, f"{fixture_id}: dangling cardId {link['cardId']}"


def test_spec_mode_sync_pending_mixed_covers_add_and_delete_with_two_active(tmp_path):
    """SyncViewScenarios mixed 釘 pending>1 且同時含 add+delete —— 只要 spec 有
    ≥2 張 active 卡就必須滿足，不得依賴恰有 4 張。"""
    payload = _small_spec()
    payload["cards"] = [c for c in payload["cards"] if c["content"] in {"alpha", "bravo", "echo"}]
    payload["links"] = [payload["links"][0]]  # alpha -> bravo；去掉指向 charlie 的 link
    content = _emit_spec_bytes(tmp_path, payload)
    mixed = json.loads(content)["vocabulary"]["syncPendingMixed"]
    pending = [e for e in mixed["entries"] if e["syncStatus"] != 1]
    actions = {e["actionType"] for e in pending}
    assert len(pending) > 1
    assert {"add", "delete"} <= actions


def test_spec_mode_dedupes_duplicate_card_contents(tmp_path):
    payload = _small_spec()
    dupe = _card("alpha", "Primary Notebook")
    dupe["meaning"] = "duplicate meaning (must be dropped)"
    payload["cards"].append(dupe)
    content = _emit_spec_bytes(tmp_path, payload)
    populated = json.loads(content)["vocabulary"]["vocabListPopulated"]
    words = [e["word"] for e in populated["entries"]]
    assert words == ["alpha", "bravo", "charlie"]
    assert populated["entries"][0]["translation"] == "alpha 的意思"  # first wins


def test_spec_mode_review_history_is_synthesized_and_references_entries(tmp_path):
    content = _emit_spec_bytes(tmp_path, _small_spec())
    dense = json.loads(content)["vocabulary"]["reviewCalendarDense"]
    words = {e["word"] for e in dense["entries"]}
    history = dense["reviewHistory"]
    assert history, "expected synthesized review history"
    assert {r["word"] for r in history} <= words
    alpha_events = [r for r in history if r["word"] == "alpha"]
    assert len(alpha_events) == 4  # review_count expanded
    assert max(r["reviewedAt"] for r in alpha_events) == "2026-05-30T12:00:00Z"
    # streak=2, lapses=1 -> [1, 0, 1, 1]
    assert sum(r["feedback"] for r in alpha_events) == 3
    # deterministic ordering: newest first
    assert history == sorted(history, key=lambda r: (r["reviewedAt"], r["word"]),
                             reverse=True)


def test_spec_mode_stats_populated_covers_all_primary_active_cards(tmp_path):
    """statsPopulated 是 Stats/ReviewCalendar 的敘事底稿：entries 必須是 primary
    notebook 全 active 卡（非只取前 8 張），reviewHistory 必須涵蓋前 8 張以外的
    卡的合成事件——否則 streak / heatmap 只剩 8 條幾何序列，敘事必崩。"""
    content = _emit_spec_bytes(tmp_path, _big_spec(60))
    document = json.loads(content)
    stats = document["vocabulary"]["statsPopulated"]
    populated = document["vocabulary"]["vocabListPopulated"]

    assert [e["word"] for e in stats["entries"]] == [
        e["word"] for e in populated["entries"]]
    assert len(stats["entries"]) > 8

    history_words = {r["word"] for r in stats["reviewHistory"]}
    beyond_first_8 = {
        e["word"] for e in stats["entries"][8:] if e["reviewCount"] > 0}
    assert beyond_first_8 & history_words, (
        "statsPopulated.reviewHistory 必須含前 8 張以外的卡事件")


def test_spec_staleness_warning_helper():
    """emit --spec 防呆：spec 錨日（max last_reviewed_at）距 now > 48h → WARN。"""
    stale = _small_spec()  # last_reviewed 全在 2026-05-31 之前
    now = __import__("datetime").datetime(
        2026, 7, 9, tzinfo=__import__("datetime").timezone.utc)
    warning = emit_ios.spec_staleness_warning(stale, now=now)
    assert warning is not None and "48h" in warning

    fresh = _small_spec()
    fresh["cards"][0]["review"]["last_reviewed_at"] = "2026-07-09T01:00:00+00:00"
    assert emit_ios.spec_staleness_warning(fresh, now=now) is None


def test_spec_mode_accepts_empty_link_reason(tmp_path):
    """export 面容許 reason=""；投影必須確定式 fallback，不得在 session 卡位置炸。"""
    payload = _small_spec()
    for link in payload["links"]:
        link["reason"] = ""  # alpha 是 todayReview current card，其 link 必經嚴格 validator
    content = _emit_spec_bytes(tmp_path, payload)
    document = json.loads(content)
    links = document["todayReview"]["front"]["currentCard"]["graphLinksByKind"]
    assert links["shares_usage"][0]["reason"] == "相關"
    assert links["contrasts_with"][0]["reason"] == "對比"


def test_reader_passage_projection_is_real_deterministic_and_highlights_match(tmp_path):
    """reader passage 投影：欄位齊備、hero 是真實卡、highlight 詞真的出現在段落、
    zero wall-clock 確定式（同 spec 重跑相等）。"""
    spec = _small_spec()
    passage = spec_world.derive_reader_passage(spec)
    # 欄位契約
    for key in ("bookTitle", "activeWord", "activePartOfSpeech", "activeTranslation",
                "activeExplanation", "activeContext", "paragraphs", "vocabWords", "activeWords"):
        assert key in passage, key
    assert passage["bookTitle"] == "Primary Notebook"  # primary notebook 名
    # small_spec 每卡 example = "The word **X** appears in a real sentence."
    assert passage["activeWords"] == [passage["activeWord"]]
    assert passage["activeWord"] in {"alpha", "bravo", "charlie"}
    # active + vocab 高亮詞必須真的以 token 出現在段落（iOS tokenizer 才命中）
    joined = " ".join(passage["paragraphs"])
    tokens = {spec_world._bare_token(t) for t in joined.split()}
    assert passage["activeWord"] in tokens
    for w in passage["vocabWords"]:
        assert w in tokens, f"vocab highlight {w!r} 未出現在段落"
    # 段落不得含殘留 ** 標記
    assert "**" not in joined
    # activeContext = hero example 去標記全文
    assert "**" not in passage["activeContext"]
    assert passage["activeWord"] in {spec_world._bare_token(t) for t in passage["activeContext"].split()}
    # 確定式
    assert spec_world.derive_reader_passage(_small_spec()) == passage


def test_reader_passage_fails_loud_without_highlightable_card():
    """primary notebook 全無「單詞 + 單 token marker」卡 → fail-loud（不靜默降級）。"""
    spec = _small_spec()
    for card in spec["cards"]:
        card["examples"] = ["no markers here at all"]  # 去掉 ** marker
    with pytest.raises(spec_world.SpecWorldError, match="reader/wordDetail hero"):
        spec_world.derive_reader_passage(spec)


def test_word_detail_scenario_seed_is_spec_derived_and_link_self_contained(tmp_path):
    """scenarioContext.wordDetail：spec-derived、entries[0]=聚焦字、graph link
    target 在 seed 內自足（關聯詞可解析）。"""
    seed = spec_world.derive_word_detail(_small_spec())
    words = {e["word"] for e in seed["entries"]}
    ids = {e["kgCardId"] for e in seed["entries"]}
    assert seed["entries"], "scenarioContext.wordDetail 必須有 entries"
    focus = seed["entries"][0]
    # small_spec: alpha 有 2 link（bravo/charlie）→ hero=alpha，關聯卡入 seed
    assert focus["word"] == "alpha"
    assert {"bravo", "charlie"} <= words
    for entry in seed["entries"]:
        for links in entry["graphLinksByKind"].values():
            for link in links:
                assert link["word"] in words, f"dangling link word {link['word']}"
                assert link["cardId"] in ids, f"dangling link cardId {link['cardId']}"
    # 確定式
    assert spec_world.derive_word_detail(_small_spec()) == seed


def test_spec_mode_graph_links_reference_target_kg_card_ids(tmp_path):
    content = _emit_spec_bytes(tmp_path, _small_spec())
    populated = json.loads(content)["vocabulary"]["vocabListPopulated"]
    by_word = {e["word"]: e for e in populated["entries"]}
    links = by_word["alpha"]["graphLinksByKind"]
    assert set(links) == {"contrasts_with", "shares_usage"}
    [shares] = links["shares_usage"]
    assert shares["word"] == "bravo"
    assert shares["cardId"] == by_word["bravo"]["kgCardId"]
    assert shares["label"] == "相關"
    assert shares["hidden"] is False
    [contrast] = links["contrasts_with"]
    assert contrast["word"] == "charlie"
    assert contrast["label"] == "對比"
    assert by_word["charlie"]["graphLinksByKind"] == {}


# --------------------------------------------------------------------------- #
# validator + determinism + size
# --------------------------------------------------------------------------- #
def test_spec_mode_output_passes_shared_validator_and_is_byte_stable(tmp_path):
    first = _emit_spec_bytes(tmp_path, _small_spec())
    second = _emit_spec_bytes(tmp_path, _small_spec())
    assert first == second, "spec mode must be byte-stable across reruns"

    out = tmp_path / "validated.json"
    out.write_bytes(first)
    from ui_world_manifest import validate_fixture_dataset_file
    assert validate_fixture_dataset_file(out, label="spec fixture")


def test_spec_mode_large_synthetic_spec(tmp_path):
    payload = _big_spec(636)
    first = _emit_spec_bytes(tmp_path, payload)
    second = _emit_spec_bytes(tmp_path, payload)
    assert first == second

    out = tmp_path / "big.json"
    out.write_bytes(first)
    from ui_world_manifest import validate_fixture_dataset_file
    assert validate_fixture_dataset_file(out, label="big spec fixture")

    document = json.loads(first)
    populated = document["vocabulary"]["vocabListPopulated"]
    # primary = "Deck 0" -> i % 3 == 0 -> 212 cards, minus archived (i%20==19 never
    # hits i%3==0 ... it can: i=39? 39%3=0 and 39%20=19 -> archived), so < 212.
    assert len(populated["entries"]) > 150
    # probe 是 UITest 量測 deck（probeword pin）→ 大 spec 下仍保留 baseline
    assert document["reviewDeck"]["probe"] == _baseline()["reviewDeck"]["probe"]
    assert document["reviewDeck"]["phaseMulti"]["entries"]
    assert document["todayReview"]["front"]["currentCard"] is not None
    # emit-side size guard: plaintext must stay well under the injection ceiling
    assert len(first) < 3 * 1024 * 1024, f"fixture too large: {len(first)} bytes"


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #
def test_build_demo_cli_spec_flow(tmp_path, capsys):
    spec_path = _write_spec(tmp_path, _small_spec())
    out_path = tmp_path / "fixture.json"

    # dry-run: plan only, no file
    rc = build_demo.main(["emit-ios", "--spec", str(spec_path),
                          "--out", str(out_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["result"]["action"] == "dry-run"
    assert not out_path.exists()

    # commit writes the fixture
    rc = build_demo.main(["emit-ios", "--spec", str(spec_path),
                          "--out", str(out_path), "--commit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["result"]["action"] == "commit"
    assert out_path.exists()

    # check passes against the fresh artifact
    rc = build_demo.main(["emit-ios", "--spec", str(spec_path),
                          "--out", str(out_path), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["result"]["drift"] is False

    # tampering -> drift -> exit 1
    out_path.write_text(out_path.read_text(encoding="utf-8") + "\n",
                        encoding="utf-8")
    rc = build_demo.main(["emit-ios", "--spec", str(spec_path),
                          "--out", str(out_path), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["result"]["drift"] is True


def test_build_demo_baseline_mode_unaffected_by_spec_flags(capsys):
    rc = build_demo.main(["emit-ios", "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["result"]["drift"] is False
    assert payload["result"]["checked"] == ["ops/demo/generated/ios_fixture_dataset.json"]


# --------------------------------------------------------------------------- #
# end-to-end: ops_edit seed (sandbox) -> ops_cli world-export -> emit --spec
# --------------------------------------------------------------------------- #
def _run_backend_cli(script: str, argv: list[str], *, sandbox: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["KG_DATA_DIR"] = sandbox
    return subprocess.run(
        [sys.executable, str(BACKEND_DIR / script), *argv],
        cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
    )


@functools.lru_cache(maxsize=1)
def _backend_cli_ready() -> bool:
    """This e2e spawns backend CLIs with sys.executable, which needs the backend
    deps installed. Under a bare pytest sandbox (`uv run --no-project --with pytest`
    — e.g. the worktree gate's ops-pytest route) they are absent: probe once and
    let the e2e SKIP instead of false-failing the whole suite. Full-fat coverage
    runs via `uv run --project backend --with pytest pytest <this file>`."""
    probe = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "ops_edit.py"), "--help"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True,
    )
    return probe.returncode == 0


def test_spec_mode_end_to_end_from_world_export(tmp_path):
    if not _backend_cli_ready():
        pytest.skip("backend deps unavailable to sys.executable (sandbox pytest run) "
                    "— run with `uv run --project backend --with pytest` for the e2e")
    identity = sot.load_identity()
    uid = identity["user_id"]
    with tempfile.TemporaryDirectory(prefix="kg-spec-e2e-") as sandbox:
        created = _run_backend_cli("ops_edit.py", [
            "user-create", uid, "--email", identity["email"],
            "--provider", identity["provider"], "--commit", "--json",
        ], sandbox=sandbox)
        assert created.returncode == 0, created.stderr

        seeded = _run_backend_cli("ops_edit.py", [
            "seed", uid, str(DEMO_DIR / "demo_dataset.json"), "--commit", "--json",
        ], sandbox=sandbox)
        assert seeded.returncode == 0, seeded.stderr

        spec_path = tmp_path / "world_export_spec.json"
        exported = _run_backend_cli("ops_cli.py", [
            "world-export", uid, "--out", str(spec_path),
        ], sandbox=sandbox)
        assert exported.returncode == 0, exported.stderr

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["schema"] == "kg.seed_spec.v1"
    dataset_cards = json.loads(
        (DEMO_DIR / "demo_dataset.json").read_text(encoding="utf-8"))["cards"]
    assert {c["content"] for c in spec["cards"]} == {c["content"] for c in dataset_cards}

    bundle = sot.load_sot()
    out_path = tmp_path / "e2e_fixture.json"
    result = emit_ios.emit(bundle, spec_path=spec_path, out_path=out_path,
                           commit=True)
    assert result["action"] == "commit"
    assert out_path.exists()

    from ui_world_manifest import validate_fixture_dataset_file
    assert validate_fixture_dataset_file(out_path, label="e2e spec fixture")

    # byte-stable re-emit
    [(_, fresh)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=out_path)
    assert out_path.read_bytes() == fresh


# --------------------------------------------------------------------------- #
# review-clock freeze overlay（UI World確定式凍結在 anchor）
# --------------------------------------------------------------------------- #
SCENARIO_PLAN_PATH = DEMO_DIR / "ui_world_seed" / "history_plan.json"


def _scenario_plan() -> dict:
    return json.loads(SCENARIO_PLAN_PATH.read_text(encoding="utf-8"))


def _freeze_dt_from_plan(plan: dict):
    from datetime import date, datetime, timedelta, timezone
    anchor = date.fromisoformat(str(plan["anchor_day"]))
    max_offset = max(plan["render_utc_offset_hours"])
    base = datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc)
    return base + timedelta(hours=24 - max_offset) - timedelta(seconds=1)


def test_scenario_context_frozen_carries_review_clock_and_reader_passage(tmp_path):
    """凍結 emit → scenarioContext.reviewClock = anchor 凍結時刻（= preferences
    overlay epoch，單一 SoT）+ readerPassage 齊備。"""
    freeze = _freeze_dt_from_plan(_scenario_plan())
    epoch = int(freeze.timestamp())
    spec_path = _write_spec(tmp_path, _small_spec())
    bundle = sot.load_sot()
    [(_, content)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "frozen.json",
        review_clock_frozen_at=freeze)
    mc = json.loads(content)["scenarioContext"]
    assert set(mc) == {"reviewClock", "readerPassage", "wordDetail"}
    assert mc["wordDetail"]["entries"][0]["word"]  # 聚焦字非空
    clock = mc["reviewClock"]
    assert clock["frozenEpoch"] == epoch  # 與 preferences overlay 同一凍結時刻
    assert clock["frozenNow"] == "2026-07-09T14:59:59Z"
    assert clock["anchorDay"] == "2026-07-09"
    assert clock["source"] == "history_plan.anchor_day"
    passage = mc["readerPassage"]
    assert passage["activeWord"] and passage["paragraphs"]
    assert passage["activeWords"] == [passage["activeWord"]]


def test_scenario_context_unfrozen_review_clock_is_null(tmp_path):
    """未凍結（無 plan）emit → reviewClock null（無 anchor 素材）、readerPassage 仍在。"""
    spec_path = _write_spec(tmp_path, _small_spec())
    bundle = sot.load_sot()
    [(_, content)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "unfrozen.json")
    mc = json.loads(content)["scenarioContext"]
    assert mc["reviewClock"] is None
    assert mc["readerPassage"]["activeWord"]


def test_review_clock_field_matches_preferences_overlay_epoch(tmp_path):
    """reviewClock.frozenEpoch 必須 == preferences review-clock overlay 的 epoch
    （防兩處錨日 drift；單一 SoT = plan freeze 時刻）。"""
    freeze = _freeze_dt_from_plan(_scenario_plan())
    spec_path = _write_spec(tmp_path, _small_spec())
    bundle = sot.load_sot()
    [(_, content)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "f.json",
        review_clock_frozen_at=freeze)
    doc = json.loads(content)
    clock_epoch = doc["scenarioContext"]["reviewClock"]["frozenEpoch"]
    for store in ("userDefaults", "ubiquitousKeyValueStore"):
        assert doc["preferences"][store]["review_settings_progress_paused_at"] == clock_epoch


def test_word_detail_scenario_emitted_and_word_detail_stays_baseline(tmp_path):
    """emit 後：scenarioContext.wordDetail 為 spec-derived（entries[0]=hero）、
    baseline-kept 的 vocabulary.wordDetail（ephemeral/terse QA pin）仍 byte-equal
    baseline（未被 spec 投影污染，QA 不受影響）。"""
    content = _emit_spec_bytes(tmp_path, _small_spec())
    document = json.loads(content)
    baseline = _baseline()
    assert document["vocabulary"]["wordDetail"] == baseline["vocabulary"]["wordDetail"]
    wdm = document["scenarioContext"]["wordDetail"]
    assert wdm["entries"][0]["word"] == "alpha"  # hero = 共用 _scenario_hero


def test_review_clock_freeze_matches_known_scenario_epoch():
    """scenario plan（anchor 2026-07-09、offsets [9,8]）→ 2026-07-09T14:59:59Z。"""
    freeze = _freeze_dt_from_plan(_scenario_plan())
    assert int(freeze.timestamp()) == 1783609199
    assert freeze.isoformat() == "2026-07-09T14:59:59+00:00"


def test_review_clock_freeze_overlays_both_stores(tmp_path):
    """(a) emit with freeze → preferences 兩 store 都 paused@epoch（含新增 paused_at）。"""
    freeze = _freeze_dt_from_plan(_scenario_plan())
    epoch = int(freeze.timestamp())
    spec_path = _write_spec(tmp_path, _small_spec())
    bundle = sot.load_sot()
    [(_, content)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "frozen.json",
        review_clock_frozen_at=freeze)
    doc = json.loads(content)
    baseline = _baseline()
    for store in ("userDefaults", "ubiquitousKeyValueStore"):
        s = doc["preferences"][store]
        assert s["review_settings_progress_paused"] is True
        assert s["review_settings_progress_paused_at"] == epoch
        assert s["review_settings_progress_updated_at"] == epoch
        # 只有時鐘 key 偏離：其餘 key 與 baseline byte-equal
        for k, v in baseline["preferences"][store].items():
            if k in emit_ios.REVIEW_CLOCK_OVERLAY_KEYS:
                continue
            assert s[k] == v, f"non-clock preferences.{store}.{k} drifted"
    # LWW：freeze epoch 晚於 baseline updated_at 故勝
    assert epoch > baseline["preferences"]["userDefaults"]["review_settings_progress_updated_at"]


def test_review_clock_unfrozen_preferences_byte_equal_baseline(tmp_path):
    """(b) emit 無 freeze → preferences byte-equal baseline（回歸不破，向後相容）。"""
    spec_path = _write_spec(tmp_path, _small_spec())
    bundle = sot.load_sot()
    [(_, content)] = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "unfrozen.json")
    doc = json.loads(content)
    assert doc["preferences"] == _baseline()["preferences"]


def test_review_clock_validator_blocks_non_clock_preferences_drift(tmp_path):
    """(c) validator 仍擋非時鐘 key 的 preferences 偏離（精準守住只有時鐘可變）。"""
    bundle = sot.load_sot()
    spec = spec_world.load_seed_spec(_write_spec(tmp_path, _small_spec()))
    freeze = _freeze_dt_from_plan(_scenario_plan())
    doc, _stats = emit_ios._build_spec_fixture_document(
        bundle, spec, review_clock_frozen_at=freeze)
    baseline = emit_ios._load_base_ui_world()
    # 合法凍結世界 + 一個 rogue 非時鐘 preferences 改動 → 必 raise
    tampered = dict(doc["preferences"])
    ud = dict(tampered["userDefaults"])
    ud["auto_sync_enabled"] = not ud["auto_sync_enabled"]
    tampered["userDefaults"] = ud
    doc = dict(doc)
    doc["preferences"] = tampered
    with pytest.raises(ValueError, match="non-clock preferences"):
        emit_ios._validate_fixture_document(
            doc, baseline, spec_domains=emit_ios.SPEC_DOMAINS, review_clock_frozen=True)


def test_review_clock_validator_blocks_rogue_added_preferences_key(tmp_path):
    """(c') 新增非時鐘 preferences key 也要 raise（不可整域放行）。"""
    bundle = sot.load_sot()
    spec = spec_world.load_seed_spec(_write_spec(tmp_path, _small_spec()))
    freeze = _freeze_dt_from_plan(_scenario_plan())
    doc, _stats = emit_ios._build_spec_fixture_document(
        bundle, spec, review_clock_frozen_at=freeze)
    baseline = emit_ios._load_base_ui_world()
    tampered = dict(doc["preferences"])
    ud = dict(tampered["userDefaults"])
    ud["rogue_injected_key"] = 42
    tampered["userDefaults"] = ud
    doc = dict(doc)
    doc["preferences"] = tampered
    with pytest.raises(ValueError, match="non-clock preferences"):
        emit_ios._validate_fixture_document(
            doc, baseline, spec_domains=emit_ios.SPEC_DOMAINS, review_clock_frozen=True)


def test_review_clock_freeze_deterministic(tmp_path):
    """(d) 同 plan 重跑 → 同 epoch、byte-stable。"""
    freeze = _freeze_dt_from_plan(_scenario_plan())
    spec_path = _write_spec(tmp_path, _small_spec())
    bundle = sot.load_sot()
    first = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "a.json",
        review_clock_frozen_at=freeze)[0][1]
    second = emit_ios._spec_artifacts(
        bundle, spec_path=spec_path, out_path=tmp_path / "b.json",
        review_clock_frozen_at=freeze)[0][1]
    assert first == second


def test_emit_rejects_freeze_without_spec_mode(tmp_path):
    """freeze 只在 spec 模式支援（baseline 模式傳入應 fail-loud）。"""
    bundle = sot.load_sot()
    freeze = _freeze_dt_from_plan(_scenario_plan())
    with pytest.raises(ValueError, match="spec mode"):
        emit_ios.emit(bundle, review_clock_frozen_at=freeze)


def test_build_demo_cli_plan_freezes_review_clock(tmp_path, capsys):
    """build_demo emit-ios --plan → world 凍結；--plan 無 --spec 應報錯。"""
    spec_path = _write_spec(tmp_path, _small_spec())
    out_path = tmp_path / "frozen_cli.json"
    rc = build_demo.main(["emit-ios", "--spec", str(spec_path),
                          "--plan", str(SCENARIO_PLAN_PATH),
                          "--out", str(out_path), "--commit", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0, payload
    assert out_path.exists()
    epoch = int(_freeze_dt_from_plan(_scenario_plan()).timestamp())
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    for store in ("userDefaults", "ubiquitousKeyValueStore"):
        s = doc["preferences"][store]
        assert s["review_settings_progress_paused"] is True
        assert s["review_settings_progress_paused_at"] == epoch
        assert s["review_settings_progress_updated_at"] == epoch

    # --plan without --spec → error, non-zero
    rc2 = build_demo.main(["emit-ios", "--plan", str(SCENARIO_PLAN_PATH), "--json"])
    payload2 = json.loads(capsys.readouterr().out)
    assert rc2 == 1
    assert "requires --spec" in payload2["error"]
