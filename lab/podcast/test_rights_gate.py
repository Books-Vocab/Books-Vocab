#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest",
# ]
# ///
"""Unit contract of rights_gate (#2094): sidecar rules, overlap measurement,
prompt policy rendering, plan validator, thresholds and the read-only report.

Run:
    cd lab/podcast && uv run --with pytest python -m pytest test_rights_gate.py -q
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

import rights_gate as rg

ROOT = Path(__file__).parent

BOOK = (
    "When the evening began the keeper climbed the iron stairs with a lamp in one "
    "hand and the ledger in the other and he counted every step aloud because his "
    "father had counted them before him and the count had never once changed in "
    "sixty years of storms tides and visitors who asked him why he bothered at all"
)
WORDS = BOOK.split()


def _index(text: str = BOOK, thresholds=rg.DEFAULT_THRESHOLDS) -> rg.SourceIndex:
    return rg.SourceIndex.from_texts([text], thresholds)


def _measure(script: str, *, source: str = BOOK, thresholds=rg.DEFAULT_THRESHOLDS):
    return rg.measure_overlap(
        rg.tokenize(script), _index(source, thresholds), thresholds
    )


# ─── tokenizer ──────────────────────────────────────────────────────────────


def test_tokenize_drops_speaker_labels_tags_and_comments():
    text = (
        "**Ava:** [slow] Don't—stop. **Ben**: Molière’s café!\n<!-- END_OF_SCRIPT -->"
    )
    assert rg.tokenize(text) == ["dont", "stop", "molieres", "cafe"]


def test_tokenize_srt_speaker_tags():
    srt = "1\n00:00:00,000 --> 00:00:00,500\n[Marcus] Welcome\n\n2\n00:00:00,500 --> 00:00:01,000\n[Marcus] home.\n"
    assert rg.tokenize(rg.srt_text(srt)) == ["welcome", "home"]


def test_tokenize_cjk_one_token_per_character():
    assert rg.tokenize("書本 is good") == ["書", "本", "is", "good"]


# ─── overlap measurement ────────────────────────────────────────────────────


def test_reading_split_across_hosts_and_tags_is_one_run():
    quote = WORDS[5:45]
    script = (
        "**Ava:** Listen to this. [slow] " + " ".join(quote[:20]) + "\n\n"
        "**Ben:** [excited] " + " ".join(quote[20:]) + " — wild.\n"
    )
    r = _measure(script)
    assert r.longest_run >= 40
    assert r.copied_words >= 40


def test_ocr_merged_word_does_not_break_the_run():
    """Source OCR glued two words ('oppositeinspire'); the script has both."""
    source = "do not go too far or you might accomplish the oppositeinspire fear and insecurity in the people above you every single time"
    script = "do not go too far or you might accomplish the opposite inspire fear and insecurity in the people above you every single time"
    r = _measure(script, source=source)
    assert r.longest_run == len(script.split())


def test_chance_short_phrases_are_not_counted_as_copied():
    script = (
        "the keeper climbed the iron stairs "
        + " ".join(f"x{i}" for i in range(200))
        + " in one hand and the ledger"
    )
    r = _measure(script)
    assert r.longest_run < rg.DEFAULT_THRESHOLDS.min_run_words
    assert r.copied_words == 0
    assert r.copied_share == 0.0


def test_paraphrase_has_no_overlap():
    r = _measure(
        "**Ava:** He climbs a tower every night, counting stairs like his dad did."
    )
    assert r.longest_run == 0 and r.copied_words == 0


def test_copied_share_counts_only_runs_of_min_length():
    quote = " ".join(WORDS[0:14])  # 14 words >= min_run 12
    filler = " ".join(f"y{i}" for i in range(186))
    r = _measure(f"{quote} {filler}")
    assert r.longest_run == 14
    assert r.copied_words == 14
    assert r.copied_share == pytest.approx(14 / 200, abs=1e-4)


# ─── thresholds ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_workflow_versions_declare_valid_verbatim_thresholds(version):
    workflow = json.loads(
        (ROOT / "workflow_versions" / version / "workflow.json").read_text()
    )
    assert "verbatim" in workflow["qa_thresholds"]
    t = rg.verbatim_thresholds(workflow)
    assert t == rg.DEFAULT_THRESHOLDS, "workflow and code defaults must not drift"
    assert workflow["validator_versions"]["verbatim"] == rg.VALIDATOR_VERSION


def test_default_thresholds_are_conservative():
    t = rg.DEFAULT_THRESHOLDS
    # The issue's acceptance fixture is a 40-word copy — it must be blocked.
    assert t.max_run_words < 40
    assert t.max_copied_share <= 0.05
    assert t.min_run_words <= t.max_run_words


def test_missing_verbatim_section_falls_back_to_conservative_defaults():
    assert rg.verbatim_thresholds({"qa_thresholds": {}}) == rg.DEFAULT_THRESHOLDS


@pytest.mark.parametrize(
    "bad",
    [
        {"max_run_words": 0},
        {"max_run_words": "30"},
        {"max_copied_share": 1.5},
        {"min_run_words": 40, "max_run_words": 30},
        {"gap_words": -1},
        {"typo_key": 3},
    ],
)
def test_invalid_thresholds_raise(bad):
    with pytest.raises(ValueError):
        rg.verbatim_thresholds({"qa_thresholds": {"verbatim": bad}})


# ─── rights sidecar ─────────────────────────────────────────────────────────


def test_read_rights_missing_is_copyrighted(tmp_path):
    assert rg.read_rights(tmp_path) == rg.COPYRIGHTED


@pytest.mark.parametrize("value", rg.RIGHTS_VALUES)
def test_read_rights_valid_values(tmp_path, value):
    (tmp_path / rg.RIGHTS_SIDECAR).write_text(value + "\n")
    assert rg.read_rights(tmp_path) == value


def test_read_rights_corrupt_value_raises(tmp_path):
    (tmp_path / rg.RIGHTS_SIDECAR).write_text("public domain probably")
    with pytest.raises(rg.RightsError):
        rg.read_rights(tmp_path)


def test_resolve_writes_requested_rights_on_creation(tmp_path):
    assert rg.resolve_workspace_rights(tmp_path, "licensed", created=True) == "licensed"
    assert (tmp_path / rg.RIGHTS_SIDECAR).read_text().strip() == "licensed"


def test_resolve_creation_default_is_copyrighted(tmp_path):
    assert rg.resolve_workspace_rights(tmp_path, None, created=True) == rg.COPYRIGHTED


def test_resolve_frozen_sidecar_rejects_change(tmp_path):
    (tmp_path / rg.RIGHTS_SIDECAR).write_text("copyrighted")
    with pytest.raises(rg.RightsError, match="frozen"):
        rg.resolve_workspace_rights(tmp_path, "public_domain", created=False)
    # Same value is fine, and a fresh-looking run cannot overwrite it either.
    assert (
        rg.resolve_workspace_rights(tmp_path, "copyrighted", created=False)
        == "copyrighted"
    )
    with pytest.raises(rg.RightsError, match="frozen"):
        rg.resolve_workspace_rights(tmp_path, "public_domain", created=True)


def test_resolve_legacy_workspace_pins_copyrighted(tmp_path):
    with pytest.raises(rg.RightsError, match="fail closed"):
        rg.resolve_workspace_rights(tmp_path, "public_domain", created=False)
    assert not (tmp_path / rg.RIGHTS_SIDECAR).exists()
    assert rg.resolve_workspace_rights(tmp_path, None, created=False) == rg.COPYRIGHTED
    assert (tmp_path / rg.RIGHTS_SIDECAR).read_text().strip() == rg.COPYRIGHTED


# ─── prompt policy ──────────────────────────────────────────────────────────

_PROMPT_FILES = sorted(
    [
        *(ROOT / "prompts").glob("*.md"),
        *(ROOT / "workflow_versions").glob("*/prompts/*.md"),
    ]
)
_POLICY_PROMPTS = {
    "analyst",
    "architect",
    "plan_review",
    "scriptwriter",
    "script_review",
}


@pytest.mark.parametrize("path", _PROMPT_FILES, ids=lambda p: str(p.relative_to(ROOT)))
@pytest.mark.parametrize("rights", rg.RIGHTS_VALUES)
def test_rendered_prompts_offer_full_text_only_for_public_domain(path, rights):
    rendered = rg.render_prompt(path.read_text(), rights, rg.DEFAULT_THRESHOLDS)
    assert "{rights_policy}" not in rendered
    assert "{strategy_options}" not in rendered
    if rights != rg.PUBLIC_DOMAIN:
        assert "full_text" not in rendered, f"{path.name} offers full_text to {rights}"


@pytest.mark.parametrize("path", _PROMPT_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_quote_heavy_prompts_carry_the_rights_policy(path):
    text = path.read_text()
    if path.stem in _POLICY_PROMPTS:
        assert "{rights_policy}" in text, (
            f"{path.name} lost its rights policy injection point"
        )
    if path.stem in {"architect", "plan_review"}:
        assert "{strategy_options}" in text


def test_public_domain_architect_offers_full_text():
    rendered = rg.render_prompt(
        (ROOT / "workflow_versions" / "v1" / "prompts" / "architect.md").read_text(),
        rg.PUBLIC_DOMAIN,
        rg.DEFAULT_THRESHOLDS,
    )
    assert "- **Strategy**: full_text / key_passages / summary_plus_quotes" in rendered


def test_policy_states_the_real_thresholds():
    t = rg.VerbatimThresholds(min_run_words=10, max_run_words=25, max_copied_share=0.02)
    policy = rg.render_rights_policy(rg.COPYRIGHTED, t)
    assert "25 words" in policy and "2%" in policy and "10+ words" in policy


def test_policy_text_has_no_bracket_tags():
    """Bracketed words in a prompt read like TTS audio tags to the writer."""
    for rights in rg.RIGHTS_VALUES:
        assert "[" not in rg.render_rights_policy(rights, rg.DEFAULT_THRESHOLDS)


# ─── plan validator ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "- **Strategy**: full_text",
        "- **Strategy:** Full text with light commentary",
        "Strategy: full-text",
        "* **strategy**: FULL_TEXT",
    ],
)
def test_full_text_strategy_detected(tmp_path, line):
    (tmp_path / "plan" / "episodes").mkdir(parents=True)
    (tmp_path / "plan" / "episodes" / "ep_03.md").write_text(f"# Ep\n{line}\n")
    assert rg.full_text_strategy_plans(tmp_path) == ["plan/episodes/ep_03.md"]


def test_commentary_and_opening_strategies_not_flagged(tmp_path):
    (tmp_path / "plan" / "episodes").mkdir(parents=True)
    (tmp_path / "plan" / "episodes" / "ep_01.md").write_text(
        "- **Strategy**: key_passages\n## Opening\n- **Strategy**: cold_open\n"
    )
    assert rg.full_text_strategy_plans(tmp_path) == []


# ─── read-only report ───────────────────────────────────────────────────────


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
    }


def test_report_is_read_only_and_flags_copying_workspace(tmp_path):
    root = tmp_path / "workspaces"
    ws = root / "book_x"
    (ws / "source" / "chapters").mkdir(parents=True)
    (ws / "scripts").mkdir()
    (ws / "plan" / "episodes").mkdir(parents=True)
    (ws / "source" / "chapters" / "ch_01.md").write_text(BOOK)
    (ws / "scripts" / "ep_1_script.md").write_text("**Ava:** " + " ".join(WORDS[:45]))
    (ws / "scripts" / "ep_1_flash.mp3").write_bytes(b"ID3")
    (ws / ".stage_publish_done").write_text("x")
    (ws / "plan" / "episodes" / "ep_01.md").write_text("- **Strategy**: full_text\n")
    before = _snapshot(root)

    report = rg.report_workspaces(root, ROOT / "workflow_versions")

    assert _snapshot(root) == before, "report must not write into workspaces"
    (row,) = report["workspaces"]
    assert row["rights"] == rg.COPYRIGHTED
    assert row["rights_source"] == "default (no sidecar)"
    assert row["published_marker"] is True
    assert row["full_text_plans"] == ["plan/episodes/ep_01.md"]
    assert row["max_run_script"] >= 45
    assert row["would_block_publish"] is True
    md = rg.render_markdown(report)
    assert "book_x" in md and "BLOCK" in md


def test_report_cli_missing_dir_exits_3(tmp_path):
    assert rg.main(["report", str(tmp_path / "nope")]) == 3


def test_gate_report_round_trips_to_json(tmp_path):
    report = rg.GateReport(
        stage="synthesize",
        rights="copyrighted",
        blocked=True,
        thresholds=asdict(rg.DEFAULT_THRESHOLDS),
    )
    rg.write_report(tmp_path / rg.REPORT_FILE, report)
    assert json.loads((tmp_path / rg.REPORT_FILE).read_text())["blocked"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
