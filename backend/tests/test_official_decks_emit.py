"""Phase 1b-ii: official-deck governance — git-SoT spec → emit into the global
``shared_decks.db`` catalog, seedable + guest-browsable.

Load-bearing invariants pinned here:
* ``source`` / ``owner_id`` / ``visibility`` / ``status`` are SERVER-authoritative
  — a spec that supplies ``source='community'`` / ``owner_id='attacker'`` is
  still emitted as an official (badge-trusted) deck. The verified-tier badge is
  a security property, so this gets a dedicated negative test.
* ``content_guid`` covers (content, pos, mode, meaning) so homographs (``lead``
  the metal vs the verb) do NOT collide into one card.
* idempotency: re-emitting the same spec is a no-op (content_hash unchanged →
  no version bump, no card proliferation); a content change mints a new version
  and atomically flips ``current_version`` while the old version stays immutable.
* ``--check`` round-trip self-consistency: a spec that cannot be faithfully
  stored (colliding cards collapse under the guid UNIQUE) drifts → exit 1.
* ``--commit`` snapshots the whole data-dir (backup_world) BEFORE writing.
* end-to-end: a committed official deck is guest-browsable via GET /api/decks
  with zero SRS leakage.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from conftest import TEST_JWT_SECRET, _swap_settings
from kg.shared_decks.store import SharedDeck, SharedDeckCard, SharedDeckStore

# The official-deck emitter lives OUTSIDE backend/src (it is an ops tool), so
# make its directory importable by bare name — the same trick build_demo.py uses
# for its sibling emitters.
_OPS_DIR = Path(__file__).resolve().parents[2] / "ops" / "official_decks"
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))

import build_official  # noqa: E402

# The 7 SRS columns that must never surface in a shared card payload.
_SRS_KEYS = {
    "reviewIntervalHours", "review_interval_hours",
    "nextReviewAt", "next_review_at",
    "lastReviewedAt", "last_reviewed_at",
    "reviewCount", "review_count",
    "lapseCount", "lapse_count",
    "reviewStreak", "review_streak",
    "lastReviewFeedback", "last_review_feedback",
}


def _spec(deck_id="official-test", cards=None, **over):
    base = {
        "schema": "kg.official_deck.v1",
        "deckId": deck_id,
        "title": "Test Deck",
        "description": "A test deck",
        "category": "language",
        "languagePair": "en-zh",
        "tags": ["test", "starter"],
        "color": "#3366FF",
        "coverPattern": "waves",
        "cards": cards if cards is not None else [
            {"content": "apple", "pos": "noun", "meaning": "蘋果",
             "examples": ["An apple a day."], "mode": "recognition"},
            {"content": "book", "pos": "noun", "meaning": "書", "mode": "recognition"},
        ],
    }
    base.update(over)
    return base


def _open(path):
    store = SharedDeckStore(path)
    return store


def _card_rows(store, deck_id):
    with Session(store.engine) as s:
        return list(s.exec(select(SharedDeckCard).where(
            SharedDeckCard.shared_deck_id == deck_id)).all())


# ── store.publish_official: server-authoritative stamping ──────────────

def test_publish_official_stamps_server_authoritative_fields(tmp_path):
    store = _open(tmp_path / "shared_decks.db")
    try:
        result = store.publish_official(
            deck_id="official-core",
            title="Core",
            category="language",
            language_pair="en-zh",
            tags=["core"],
            cards=[
                {"content": "apple", "pos": "noun", "meaning": "蘋果",
                 "mode": "recognition"},
                {"content": "book", "pos": "noun", "meaning": "書",
                 "mode": "recognition"},
            ],
        )
        with Session(store.engine) as s:
            deck = s.get(SharedDeck, "official-core")
        assert deck is not None
        assert deck.source == "official"
        assert deck.owner_id is None
        assert deck.visibility == "official"
        assert deck.status == "active"
        assert deck.is_deleted is False
        assert deck.current_version == 1
        assert deck.card_count == 2
        assert deck.title_nfc_lower == "core"
        assert result["cardCount"] == 2
    finally:
        store.close()


def test_publish_official_ignores_caller_supplied_source_and_owner(tmp_path):
    """Badge trust: even if a spec smuggles source='community'/owner_id, the
    emitted deck is official with owner_id NULL — the signature has no such
    params, so the fields are structurally unreachable."""
    store = _open(tmp_path / "shared_decks.db")
    try:
        spec = _spec(deck_id="official-x")
        spec["source"] = "community"      # attacker attempt
        spec["ownerId"] = "attacker-123"  # attacker attempt
        build_official.emit(spec, commit=True, data_dir=tmp_path)
        with Session(store.engine) as s:
            deck = s.get(SharedDeck, "official-x")
        assert deck.source == "official"
        assert deck.owner_id is None
        assert deck.visibility == "official"
    finally:
        store.close()


# ── content_guid: homograph safety ─────────────────────────────────────

def test_content_guid_covers_pos_and_meaning(tmp_path):
    store = _open(tmp_path / "shared_decks.db")
    try:
        store.publish_official(
            deck_id="d",
            title="Homographs",
            cards=[
                {"content": "lead", "pos": "noun", "meaning": "鉛（金屬）",
                 "mode": "recognition"},
                {"content": "lead", "pos": "verb", "meaning": "帶領",
                 "mode": "recognition"},
            ],
        )
        rows = _card_rows(store, "d")
        assert len(rows) == 2, "homographs must not collapse to one guid"
        assert len({r.content_guid for r in rows}) == 2
    finally:
        store.close()


def test_identical_cards_dedup_by_guid(tmp_path):
    store = _open(tmp_path / "shared_decks.db")
    try:
        result = store.publish_official(
            deck_id="d",
            title="Dup",
            cards=[
                {"content": "run", "pos": "verb", "meaning": "跑", "mode": "recognition"},
                {"content": "run", "pos": "verb", "meaning": "跑", "mode": "recognition"},
            ],
        )
        # A collision under the guid UNIQUE must be absorbed, not crash.
        assert result["cardCount"] == 1
        assert len(_card_rows(store, "d")) == 1
    finally:
        store.close()


# ── idempotency + versioning ───────────────────────────────────────────

def test_reemit_same_spec_is_noop(tmp_path):
    spec = _spec(deck_id="official-idem")
    build_official.emit(spec, commit=True, data_dir=tmp_path)
    second = build_official.emit(spec, commit=True, data_dir=tmp_path)
    store = _open(tmp_path / "shared_decks.db")
    try:
        with Session(store.engine) as s:
            deck = s.get(SharedDeck, "official-idem")
        assert deck.current_version == 1, "re-emit must not bump version"
        # No card proliferation: rows == card_count, not doubled.
        assert len(_card_rows(store, "official-idem")) == deck.card_count == 2
        assert second["result"]["action"] == "noop"
    finally:
        store.close()


def test_content_change_bumps_version_and_flips_pointer(tmp_path):
    spec = _spec(deck_id="official-ver")
    build_official.emit(spec, commit=True, data_dir=tmp_path)
    changed = _spec(deck_id="official-ver", cards=[
        {"content": "apple", "pos": "noun", "meaning": "蘋果", "mode": "recognition"},
        {"content": "cat", "pos": "noun", "meaning": "貓", "mode": "recognition"},
        {"content": "dog", "pos": "noun", "meaning": "狗", "mode": "recognition"},
    ])
    result = build_official.emit(changed, commit=True, data_dir=tmp_path)
    store = _open(tmp_path / "shared_decks.db")
    try:
        with Session(store.engine) as s:
            deck = s.get(SharedDeck, "official-ver")
        assert deck.current_version == 2
        assert deck.card_count == 3
        assert result["result"]["action"] == "versioned"
        # Old version-1 cards are immutable — still present.
        v1 = [r for r in _card_rows(store, "official-ver") if r.version == 1]
        v2 = [r for r in _card_rows(store, "official-ver") if r.version == 2]
        assert len(v1) == 2
        assert len(v2) == 3
    finally:
        store.close()


def test_metadata_only_change_updates_in_place_without_version_bump(tmp_path):
    """Same cards but changed title/tags → action='metadata': in-place update,
    updated_at bumped, no new version, no card proliferation."""
    spec = _spec(deck_id="official-meta")
    build_official.emit(spec, commit=True, data_dir=tmp_path)
    renamed = _spec(deck_id="official-meta", title="Renamed Deck", tags=["fresh"])
    result = build_official.emit(renamed, commit=True, data_dir=tmp_path)
    store = _open(tmp_path / "shared_decks.db")
    try:
        with Session(store.engine) as s:
            deck = s.get(SharedDeck, "official-meta")
        assert result["result"]["action"] == "metadata"
        assert deck.current_version == 1, "metadata change must not bump version"
        assert deck.title == "Renamed Deck"
        assert deck.tags == ["fresh"]
        assert deck.card_count == 2
        assert len(_card_rows(store, "official-meta")) == 2, "no card proliferation"
    finally:
        store.close()


def test_commit_writes_audit_entry(tmp_path):
    build_official.emit(_spec(deck_id="official-audit"), commit=True, data_dir=tmp_path)
    audit = tmp_path / "_ops_edit_audit.jsonl"
    assert audit.exists(), "official injection must leave an audit trail"
    entries = [json.loads(ln) for ln in audit.read_text().splitlines() if ln.strip()]
    inj = [e for e in entries if e.get("schema") == "kg.official_deck_injection.v1"]
    assert inj and inj[-1]["deckId"] == "official-audit"
    assert inj[-1]["action"] == "created"
    assert "contentHash" in inj[-1] and "ts" in inj[-1]


def test_commit_result_surfaces_resolved_data_dir(tmp_path):
    res = build_official.emit(_spec(deck_id="official-dd"), commit=True, data_dir=tmp_path)
    assert res["dataDir"] == str(tmp_path)


def test_invalid_category_is_rejected(tmp_path):
    with pytest.raises(build_official.SpecError):
        build_official.emit(_spec(category="not-an-enum"), commit=False, data_dir=tmp_path)


def test_non_numeric_difficulty_is_rejected(tmp_path):
    bad = _spec(cards=[{"content": "x", "meaning": "y", "difficulty": "hard"}])
    with pytest.raises(build_official.SpecError):
        build_official.emit(bad, commit=False, data_dir=tmp_path)


# ── --check round-trip self-consistency ────────────────────────────────

def test_check_passes_for_clean_spec(tmp_path):
    res = build_official.emit(_spec(), check=True)
    assert res["drift"] is False


def test_check_detects_drift_on_colliding_cards(tmp_path):
    # Two cards identical in (content, pos, mode, meaning) collide to one guid
    # → the stored deck cannot faithfully represent the spec-as-written → drift.
    bad = _spec(cards=[
        {"content": "same", "pos": "noun", "meaning": "同", "mode": "recognition"},
        {"content": "same", "pos": "noun", "meaning": "同", "mode": "recognition"},
    ])
    res = build_official.emit(bad, check=True)
    assert res["drift"] is True


# ── copyability: reject NOCASE-colliding homographs at curation ─────────

def test_nocase_colliding_cards_rejected_as_uncopyable(tmp_path):
    """A homograph pair distinct only by pos/meaning but sharing a
    case-insensitive content ("Lead" n. vs "lead" v.) survives as two
    shared_deck_card rows (distinct content_guid) yet COLLAPSES under the
    copier's UNIQUE(content COLLATE NOCASE, notebook_id) → every copy 409s.
    build_official must reject it at curation, in EVERY mode, not ship a dead
    deck the round-trip check can't see."""
    bad = _spec(cards=[
        {"content": "Lead", "pos": "noun", "meaning": "鉛（金屬）", "mode": "recognition"},
        {"content": "lead", "pos": "verb", "meaning": "帶領", "mode": "recognition"},
    ])
    with pytest.raises(build_official.SpecError, match="(?i)case-insensitive|nocase|collide"):
        build_official.emit(bad, check=True)
    with pytest.raises(build_official.SpecError):
        build_official.emit(bad, commit=False, data_dir=tmp_path)
    with pytest.raises(build_official.SpecError):
        build_official.emit(bad, commit=True, data_dir=tmp_path)
    assert not (tmp_path / "shared_decks.db").exists(), "rejected spec must not write"


def test_distinct_content_homograph_is_copyable(tmp_path):
    """Distinct content strings (no NOCASE collision) copy 1:1 → allowed."""
    ok = _spec(cards=[
        {"content": "lead", "pos": "noun", "meaning": "鉛", "mode": "recognition"},
        {"content": "leads", "pos": "verb", "meaning": "帶領", "mode": "recognition"},
    ])
    assert build_official.emit(ok, check=True)["drift"] is False


def test_exact_duplicate_cards_not_flagged_by_copyability_guard(tmp_path):
    """Two identical cards share ONE content_guid → they collapse to a single
    shared_deck_card and copy 1:1, so the NOCASE copyability guard must NOT trip
    (it dedups by guid first, exactly as publish_official does). Dry-run runs the
    guard but not the round-trip --check (which separately flags redundant cards
    as drift — a different gate)."""
    dup = _spec(cards=[
        {"content": "run", "pos": "verb", "meaning": "跑", "mode": "recognition"},
        {"content": "run", "pos": "verb", "meaning": "跑", "mode": "recognition"},
    ])
    res = build_official.emit(dup, commit=False, data_dir=tmp_path)
    assert res["committed"] is False
    assert res["cardCount"] == 1  # deduped by guid, no SpecError raised


def test_check_over_committed_specs_is_clean():
    """Every git-committed official spec must round-trip cleanly (PR gate)."""
    specs = build_official.discover_specs()
    assert specs, "expected at least one committed official spec"
    drift = []
    for path in specs:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
        if build_official.emit(spec, check=True)["drift"]:
            drift.append(path)
    assert not drift, f"committed specs drift: {drift}"


# ── dry-run purity + backup hook ───────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path):
    res = build_official.emit(_spec(), commit=False, data_dir=tmp_path)
    assert res["committed"] is False
    assert not (tmp_path / "shared_decks.db").exists(), "dry-run must not touch disk"
    assert res["cardCount"] == 2
    assert res["contentHash"]


def test_commit_calls_backup_world_before_writing(tmp_path):
    build_official.emit(_spec(deck_id="official-bk"), commit=True, data_dir=tmp_path)
    backups = list((tmp_path / "_ops_world_backups").glob("shared-decks-official__*.tar.gz"))
    assert backups, "commit must snapshot the world before writing"


# ── end-to-end: seeded official deck is guest-browsable ────────────────

@pytest.fixture()
def api(tmp_path):
    (tmp_path / "users").mkdir()
    _swap_settings(_settings(tmp_path))
    yield SimpleNamespace(
        client=TestClient(app, raise_server_exceptions=False),
        data_dir=tmp_path,
    )


def _settings(tmp_path):
    from kg.settings import KGSettings
    return KGSettings(data_dir=tmp_path, jwt_secret=TEST_JWT_SECRET)


# Imported lazily so _swap_settings can rewire app state per test.
from kg.api import app  # noqa: E402


def test_seeded_official_deck_is_guest_browsable(api):
    spec = _spec(deck_id="official-e2e", cards=[
        {"content": "meticulous", "pos": "adjective", "meaning": "一絲不苟的",
         "examples": ["a meticulous plan"], "mode": "recognition"},
        {"content": "plain", "pos": "adjective", "meaning": "平凡的", "mode": "recognition"},
    ])
    build_official.emit(spec, commit=True, data_dir=api.data_dir)

    r = api.client.get("/api/decks")  # NO auth header (guest)
    assert r.status_code == 200, r.text
    decks = r.json()["decks"]
    deck = next((d for d in decks if d["deckId"] == "official-e2e"), None)
    assert deck is not None, "official deck must be guest-browsable"
    assert deck["isOfficial"] is True
    assert deck["cardCount"] == 2

    detail = api.client.get("/api/decks/official-e2e")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["sampleCards"]) == 2
    for card in body["sampleCards"]:
        assert _SRS_KEYS.isdisjoint(card.keys()), f"SRS leaked: {_SRS_KEYS & card.keys()}"


# ── git-index reference frame: what ships vs what check reads ──────────
#
# The bug this section pins: ``check`` enumerated the FILESYSTEM while the
# deploy ships the GIT INDEX. A spec the curator forgot to ``git add`` was
# validated locally, passed CI, and then simply did not exist in production.
# Every test here therefore controls "on disk" and "in the index" SEPARATELY —
# an implementation that reads the working directory twice would satisfy the
# positive case and fail the negative one.

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _write_spec(repo: Path, name: str, *, tracked: bool) -> Path:
    path = repo / f"{name}.json"
    path.write_text(json.dumps(_spec(deck_id=name)), encoding="utf-8")
    if tracked:
        _git(repo, "add", path.name)
    return path


@pytest.fixture()
def spec_repo(tmp_path, monkeypatch):
    """A throwaway git repo standing in for ``ops/official_decks/``."""
    repo = tmp_path / "specrepo"
    repo.mkdir()
    _git(repo, "init", "-q")
    monkeypatch.setattr(build_official, "_HERE", repo)
    return repo


def test_check_fails_on_untracked_spec(spec_repo, capsys):
    """A spec on disk but absent from the index must turn the gate red — and
    name itself. ``drift is False`` proves the round-trip check was happy and
    the NEW gate is what failed the run; the exact-list assertion proves the
    tracked sibling was not swept in (a filesystem-reading implementation
    would report both).

    Deliberately paired with ``test_check_passes_when_no_untracked_specs``:
    the two lay down the SAME two filenames with the SAME contents and differ
    only in whether ``git add`` ran. Nothing readable from the filesystem —
    name, size, mtime, contents — can tell the two fixtures apart, so no
    implementation can satisfy both without asking git."""
    _write_spec(spec_repo, "deck-one", tracked=True)
    orphan = _write_spec(spec_repo, "deck-two", tracked=False)

    rc = build_official.main(["check", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["drift"] is False, "round-trip was clean; only the index gate should fail"
    assert out["gitIndex"]["checked"] is True
    assert out["gitIndex"]["untracked"] == [str(orphan)]
    assert out["gitIndex"]["missing"] == []


def test_check_passes_when_no_untracked_specs(spec_repo, capsys):
    """Same two files as the test above; only ``git add`` differs. Without this
    reverse case ``untracked_specs`` could return the whole directory listing
    (or ``check`` could just always exit 1) and still pass the positive one."""
    _write_spec(spec_repo, "deck-one", tracked=True)
    _write_spec(spec_repo, "deck-two", tracked=True)

    rc = build_official.main(["check", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert out["gitIndex"] == {"checked": True, "untracked": [], "missing": []}
    assert rc == 0


def test_check_flags_index_only_spec_as_well_as_untracked(spec_repo, capsys):
    """The mirror hole: ``rm`` without ``git rm`` leaves the spec in the index
    (so it still ships) while the filesystem walk stops seeing it — the same
    divergence, pointing the other way. Only the index can name a file that is
    no longer on disk, so this direction is unfakeable from the filesystem."""
    ghost = _write_spec(spec_repo, "deck-one", tracked=True)
    _write_spec(spec_repo, "deck-two", tracked=True)
    ghost.unlink()

    rc = build_official.main(["check", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["gitIndex"]["missing"] == [str(ghost)]
    assert out["gitIndex"]["untracked"] == []


def test_gitignored_spec_is_still_reported_as_untracked(spec_repo, capsys):
    """A spec swallowed by ``.gitignore`` is exactly as absent from production
    as a forgotten one, so it must be reported the same way.

    This pins the one property that makes subtracting-the-index the right
    derivation: ``git ls-files --others --exclude-standard`` — the listing
    originally prescribed for this fix — does not report ignored files, so an
    implementation built on it goes green here while the deck never ships."""
    _write_spec(spec_repo, "deck-one", tracked=True)
    (spec_repo / ".gitignore").write_text("deck-two.json\n", encoding="utf-8")
    _git(spec_repo, "add", ".gitignore")
    ignored = _write_spec(spec_repo, "deck-two", tracked=False)

    rc = build_official.main(["check", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["gitIndex"]["untracked"] == [str(ignored)]


def test_nested_json_is_not_mistaken_for_a_missing_or_untracked_spec(spec_repo, capsys):
    """``git ls-files`` recurses; ``discover_specs`` does not. The index side
    must be clipped to the same depth or every nested JSON (fixtures, notes)
    reads as a spec that vanished from disk."""
    _write_spec(spec_repo, "deck-one", tracked=True)
    nested = spec_repo / "sub"
    nested.mkdir()
    (nested / "nested.json").write_text("{}", encoding="utf-8")
    _git(spec_repo, "add", "sub/nested.json")

    rc = build_official.main(["check", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert out["gitIndex"] == {"checked": True, "untracked": [], "missing": []}
    assert rc == 0


def test_untracked_specs_refuses_to_report_a_non_git_tree_as_clean(tmp_path, monkeypatch, capsys):
    """"I cannot see the index" and "the index is clean" are the two states
    this gate exists to keep apart, so a missing/unavailable git must raise —
    and must not let ``check`` exit 0."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    (plain / "loose-deck.json").write_text(
        json.dumps(_spec(deck_id="loose-deck")), encoding="utf-8")
    monkeypatch.setattr(build_official, "_HERE", plain)

    with pytest.raises(build_official.GitIndexUnavailable):
        build_official.untracked_specs()

    rc = build_official.main(["check", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["mode"] == "error"
    # `pytest.raises` above carries the load; these two only check the message
    # is actionable. Note what each touches: `str(plain)` is the value the test
    # itself handed to `_HERE`, so it proves the message is addressed to the
    # right directory but NOT that git ran. "git repository" is git's own
    # stderr, echoed through — that one is not ours to fake.
    assert str(plain) in out["error"]
    assert "git repository" in out["error"]
    assert "gitIndex" not in out, "a failed lookup must not also issue a clean bill"


def test_single_spec_check_reports_index_unchecked_not_untracked_empty(spec_repo, capsys):
    """``check <one spec>`` never enumerates the directory, so it must report
    the index as UNCHECKED rather than as empty — reporting ``untracked: []``
    there would be the same false-clean this ticket removes."""
    orphan = _write_spec(spec_repo, "deck-one", tracked=False)

    rc = build_official.main(["check", str(orphan), "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["gitIndex"]["checked"] is False
    assert "untracked" not in out["gitIndex"]


# ── CLI surface ────────────────────────────────────────────────────────

def test_cli_emit_dry_run_json(tmp_path, capsys):
    spec_path = tmp_path / "deck.json"
    spec_path.write_text(json.dumps(_spec(deck_id="official-cli")), encoding="utf-8")
    rc = build_official.main(["emit", str(spec_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["mode"] == "dry-run"
    assert out["committed"] is False


def test_cli_check_all_committed_specs(capsys):
    rc = build_official.main(["check", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["drift"] is False
