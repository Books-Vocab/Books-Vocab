"""Spec-driven emit-ios (kg.seed_spec.v1 -> UI World v2) contract tests.

Covers the Phase 2/6 marketing-account projector:
  * spec mode derives vocabulary / notebook / reviewDeck / todayReview from the
    seed spec; every other domain stays byte-equal to the committed baseline
    (ops/fixtures/ui_worlds/marketing_demo.json) + identity auth overlay.
  * output passes the shared ui_world_manifest validator and is byte-stable.
  * baseline emit-ios (no --spec) and its --check drift gate are frozen.
  * end-to-end: ops_edit seed (sandbox) -> ops_cli world-export -> emit --spec.
"""

from __future__ import annotations

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
    nb, side = "Marketing Core", "Side Notes"
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
        "confidence": 0.5, "reason": "dangling", "notebook": "Marketing Core",
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

    # non-spec domains stay byte-equal to the baseline
    for key in sorted(set(document) - {"datasetID", "auth", *SPEC_DOMAINS}):
        assert document[key] == baseline[key], f"domain {key} drifted from baseline"

    # identity overlay identical to baseline mode
    signed_in = document["auth"]["signedIn"]
    identity = sot.load_identity()
    assert signed_in["userId"] == identity["user_id"]
    assert signed_in["token"] == identity["access_token"]

    # vocabulary: populated list mirrors the primary notebook's active cards
    populated = document["vocabulary"]["vocabListPopulated"]
    assert [e["word"] for e in populated["entries"]] == ["alpha", "bravo", "charlie"]
    assert populated["notebookName"] == "Marketing Core"
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

    # archived views only carry genuinely archived cards
    archived = document["vocabulary"]["archivedPopulated"]
    assert [e["word"] for e in archived["entries"]] == ["delta"]
    assert archived["entries"][0]["isArchived"] is True

    # notebook rows mirror the spec notebooks
    rows = document["notebook"]["populated"]["notebooks"]
    assert [(r["name"], r["isDefault"], r["sortOrder"]) for r in rows] == [
        ("Marketing Core", True, 0), ("Side Notes", False, 1)]
    assert rows[0]["coverPattern"] == "waves"
    assert rows[0]["color"] == "#4F7C73"
    assert [e["word"] for e in rows[0]["entries"]] == ["alpha", "bravo", "charlie"]
    assert len({r["remoteId"] for r in rows}) == 2

    # reviewDeck: due order = scheduled first (by nextReviewAt), then unscheduled
    deck = document["reviewDeck"]["notebookReviewDeck"]
    assert [e["word"] for e in deck["entries"]] == ["alpha", "bravo", "charlie"]
    assert deck["notebookName"] == "Marketing Core"
    assert [e["word"] for e in document["reviewDeck"]["phaseSingle"]["entries"]] == ["alpha"]


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


def test_spec_mode_dedupes_duplicate_card_contents(tmp_path):
    payload = _small_spec()
    dupe = _card("alpha", "Marketing Core")
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
    assert document["reviewDeck"]["probe"]["entries"]
    assert len(document["reviewDeck"]["probe"]["entries"]) <= 40
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


def test_spec_mode_end_to_end_from_world_export(tmp_path):
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
