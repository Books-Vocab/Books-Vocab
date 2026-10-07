#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "boto3",
#     "pytest",
# ]
# ///
"""Copyright line enforced in code (#2094).

Project stance: transformative commentary is fine; the HARD line is that a
non-public-domain book never gets full_text / audiobook-like verbatim audio.
These tests drive the real pipeline entry points:

  * rights sidecar: set at creation (``--rights``), missing = copyrighted
    (fail closed), resume cannot change it;
  * prompts never offer ``full_text`` unless the book is public domain, and
    plan-review fails on a ``Strategy: full_text`` plan;
  * a code gate before ``synthesize`` AND ``publish`` blocks over-threshold
    verbatim overlap with ``source/chapters`` — including the
    ``--skip-to publish`` / ``--only-stage publish`` / ``--force`` paths.

Run:
    cd lab/podcast && uv run --with pytest --with ebooklib --with beautifulsoup4 \
        --with boto3 python -m pytest test_copyright_stage_gates.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import pipeline

# Original fixture prose (written for this test — not from any book).
SOURCE_TEXT = (
    "The lighthouse keeper rose before dawn on every morning of his long working "
    "life, and he kept a ledger in which he recorded the colour of the sea, the "
    "direction of the wind, and the name of every vessel that slipped through the "
    "narrow channel beneath the cliffs. Nobody had asked him to keep it. The "
    "harbour authority wanted only a lamp that burned and a horn that sounded in "
    "fog. Yet the ledger grew to forty volumes, each bound in oilcloth and stacked "
    "beside the stove, and when the keeper finally retired the new men found that "
    "he had written down not merely the ships but the moods of the people who "
    "sailed them: a captain who sang to his crew, a fisherman who never once "
    "looked up at the tower, a girl who waved a red scarf every Sunday for eleven "
    "years and then stopped. Historians later treated the ledger as a record of "
    "trade. The keeper's daughter insisted it was something closer to a diary of "
    "attention, a discipline of noticing that he practised the way other men "
    "practised prayer, and she argued that the habit mattered more than anything "
    "he ever wrote in it."
)
SOURCE_WORDS = SOURCE_TEXT.split()
COPY_40 = SOURCE_WORDS[20:60]  # 40 consecutive verbatim words
SHORT_QUOTE = SOURCE_WORDS[100:115]  # 15 words — an ordinary commentary quote

# Commentary filler: unique tokens that never occur in the source.
FILLER = " ".join(f"riff{i}" for i in range(700))


def _script(body: str) -> str:
    return (
        "# Episode 1: The Ledger\n> A keeper who wrote everything down.\n\n"
        f"**Ava:** Welcome back. {FILLER[:2000]}\n\n"
        f"{body}\n\n"
        f"**Ben:** {FILLER[2000:]}\n\n"
        "<!-- END_OF_SCRIPT -->\n"
    )


# A 40-word reading split across both hosts with an audio tag in the middle —
# the split must not hide it.
COPIED_SCRIPT = _script(
    f"**Ava:** There is a passage I keep rereading. [slow] {' '.join(COPY_40[:22])}\n\n"
    f"**Ben:** {' '.join(COPY_40[22:])} — and that is the whole chapter, honestly."
)
CLEAN_SCRIPT = _script(
    f'**Ava:** His daughter puts it best: "{" ".join(SHORT_QUOTE)}" and I buy it.'
)


def _srt(text: str) -> str:
    """Word-level SRT in subtitle.py's shape: one ``[Speaker] word`` per cue."""
    cues = []
    for i, word in enumerate(text.split(), 1):
        cues.append(
            f"{i}\n00:00:{i % 60:02d},000 --> 00:00:{i % 60:02d},500\n[Ava] {word}\n"
        )
    return "\n".join(cues)


class _FakeLog:
    def __init__(self):
        self.events: list[str] = []
        self.errors: list[str] = []

    def event(self, msg, **kw):
        self.events.append(msg)

    def error(self, msg, **kw):
        self.errors.append(msg)


def _ws(
    tmp_path: Path,
    *,
    rights: str | None,
    script: str = COPIED_SCRIPT,
    srt: str | None = None,
    audio: bool = False,
    with_source: bool = True,
    name: str = "ledger_book_0123abcd",
) -> Path:
    ws = tmp_path / name
    (ws / "scripts").mkdir(parents=True)
    (ws / "plan" / "episodes").mkdir(parents=True)
    (ws / "log.md").write_text("# log\n")
    (ws / "plan" / "overview.md").write_text("# The Ledger\n")
    if with_source:
        (ws / "source" / "chapters").mkdir(parents=True)
        (ws / "source" / "chapters" / "ch_01.md").write_text(
            f"# Chapter 1\n\n{SOURCE_TEXT}\n"
        )
    (ws / "scripts" / "ep_1_script.md").write_text(script)
    if srt is not None:
        (ws / "scripts" / "ep_1_flash.srt").write_text(srt)
    if audio:
        (ws / "scripts" / "ep_1_flash.mp3").write_bytes(b"ID3fake")
    if rights is not None:
        (ws / ".rights").write_text(rights)
    return ws


@pytest.fixture
def no_subprocess(monkeypatch):
    """Record any attempt to run a tool stage or spawn a subprocess."""
    calls: list[object] = []

    def _tool(stage, cmd, **kw):
        calls.append(("tool", stage, cmd))
        return 0

    def _popen(*a, **kw):
        calls.append(("popen", a))
        raise AssertionError("a subprocess was spawned")

    def _bounded(cmd, **kw):
        calls.append(("bounded", cmd))
        return 0

    monkeypatch.setattr(pipeline, "_run_tool_stage", _tool)
    monkeypatch.setattr(pipeline, "_run_bounded", _bounded)
    monkeypatch.setattr(pipeline.subprocess, "Popen", _popen)
    return calls


# ─── synthesize gate ────────────────────────────────────────────────────────


def test_copyrighted_40_word_copy_blocks_synthesize_and_runs_nothing(
    tmp_path, no_subprocess
):
    ws = _ws(tmp_path, rights="copyrighted")
    log = _FakeLog()

    assert pipeline.stage_synthesize(ws, log) is False
    assert no_subprocess == [], "synthesize must not start any subprocess"
    assert any("verbatim" in e.lower() for e in log.errors), log.errors


def test_missing_rights_sidecar_fails_closed_as_copyrighted(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights=None)

    assert pipeline.stage_synthesize(ws, _FakeLog()) is False
    assert no_subprocess == []


def test_licensed_is_gated_like_copyrighted(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights="licensed")

    assert pipeline.stage_synthesize(ws, _FakeLog()) is False
    assert no_subprocess == []


def test_public_domain_40_word_copy_proceeds_to_synthesize(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights="public_domain")

    assert pipeline.stage_synthesize(ws, _FakeLog()) is True
    assert [c[0] for c in no_subprocess] == ["tool"], "positive control: synth ran"


def test_copyrighted_commentary_with_short_quote_proceeds(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)

    assert pipeline.stage_synthesize(ws, _FakeLog()) is True
    assert [c[0] for c in no_subprocess] == ["tool"]
    report = json.loads((ws / "verbatim_qa.json").read_text())
    assert report["blocked"] is False
    assert report["texts"][0]["longest_run"] >= len(SHORT_QUOTE)


def test_copyrighted_without_source_chapters_fails_closed(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT, with_source=False)
    log = _FakeLog()

    assert pipeline.stage_synthesize(ws, log) is False
    assert no_subprocess == []
    assert any("source/chapters" in e for e in log.errors), log.errors


def test_synthesize_gate_writes_reviewable_report(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights="copyrighted")

    pipeline.stage_synthesize(ws, _FakeLog())

    report = json.loads((ws / "verbatim_qa.json").read_text())
    assert report["stage"] == "synthesize"
    assert report["rights"] == "copyrighted"
    assert report["blocked"] is True
    (text,) = report["texts"]
    assert text["artifact"] == "scripts/ep_1_script.md"
    assert text["longest_run"] >= 40
    assert text["violations"]


def test_only_episode_synthesize_checks_that_episode(tmp_path, no_subprocess):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)
    (ws / "scripts" / "ep_2_script.md").write_text(COPIED_SCRIPT)

    assert pipeline.stage_synthesize(ws, _FakeLog(), only_episode=1) is True
    assert pipeline.stage_synthesize(ws, _FakeLog(), only_episode=2) is False


# ─── publish gate ───────────────────────────────────────────────────────────


@pytest.fixture
def publish_env(monkeypatch):
    monkeypatch.setenv("PODCAST_BUCKET", "kg-test-bucket")
    monkeypatch.setattr(pipeline, "_verify_published", lambda sid: True)
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)


def test_copyrighted_copy_blocks_publish_before_upload(
    tmp_path, no_subprocess, publish_env
):
    ws = _ws(tmp_path, rights="copyrighted", audio=True, srt=_srt(CLEAN_SCRIPT))

    assert pipeline.stage_publish(ws, _FakeLog()) is False
    assert no_subprocess == [], "upload must not be attempted"


def test_subtitle_copy_blocks_publish_even_if_script_was_cleaned(
    tmp_path, no_subprocess, publish_env
):
    """Audio/subtitles made from an older, copying script cannot be laundered by
    editing script.md afterwards: the published SRT is measured too."""
    ws = _ws(
        tmp_path,
        rights="copyrighted",
        script=CLEAN_SCRIPT,
        audio=True,
        srt=_srt(COPIED_SCRIPT),
    )

    assert pipeline.stage_publish(ws, _FakeLog()) is False
    assert no_subprocess == []


def test_publish_audio_without_any_text_fails_closed(
    tmp_path, no_subprocess, publish_env
):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT, audio=True)
    (ws / "scripts" / "ep_1_script.md").unlink()

    assert pipeline.stage_publish(ws, _FakeLog()) is False
    assert no_subprocess == []


def test_public_domain_copy_publishes(tmp_path, no_subprocess, publish_env):
    ws = _ws(tmp_path, rights="public_domain", audio=True, srt=_srt(COPIED_SCRIPT))

    assert pipeline.stage_publish(ws, _FakeLog()) is True
    assert [c[0] for c in no_subprocess] == ["bounded"], "positive control: uploaded"


def test_copyrighted_clean_series_publishes(tmp_path, no_subprocess, publish_env):
    ws = _ws(
        tmp_path,
        rights="copyrighted",
        script=CLEAN_SCRIPT,
        audio=True,
        srt=_srt(CLEAN_SCRIPT),
    )

    assert pipeline.stage_publish(ws, _FakeLog()) is True
    assert [c[0] for c in no_subprocess] == ["bounded"]


# ─── CLI bypass attempts: --skip-to / --only-stage / --force ────────────────


def _complete_ws(tmp_path: Path, rights: str) -> Path:
    ws = _ws(tmp_path, rights=rights, audio=True, srt=_srt(COPIED_SCRIPT))
    for stage in pipeline.STAGES[: pipeline.STAGES.index("publish")]:
        (ws / f".stage_{stage}_done").write_text("2026-10-07T00:00:00")
    (ws / ".plan_approved").write_text("ok")
    (ws / ".script_approved").write_text("ok")
    return ws


@pytest.fixture
def cli(monkeypatch, publish_env):
    """Run pipeline.main() in-process with every side channel stubbed."""
    uploads: list[list[str]] = []

    def _bounded(cmd, **kw):
        uploads.append(list(cmd))
        return 0

    monkeypatch.setattr(pipeline, "_run_bounded", _bounded)
    monkeypatch.setattr(pipeline, "_ensure_dashboard_running", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_pipeline_commit", lambda: "test")
    for key in (
        "PODCAST_AGENT_PROFILE",
        "PODCAST_AGENT_MODEL",
        "PODCAST_WORKFLOW_VERSION",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(pipeline, "AGENT_PROFILE", pipeline.AGENT_PROFILE)
    monkeypatch.setattr(pipeline, "MODEL", pipeline.MODEL)

    def run(*argv: str) -> None:
        monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
        pipeline.main()

    run.uploads = uploads
    return run


@pytest.mark.parametrize(
    "flags",
    [
        ("--skip-to", "publish"),
        ("--only-stage", "publish"),
        ("--skip-to", "publish", "--force", "--ignore-gates"),
    ],
    ids=["skip-to", "only-stage", "skip-to-force-ignore-gates"],
)
def test_cli_publish_paths_cannot_bypass_verbatim_gate(tmp_path, cli, flags):
    ws = _complete_ws(tmp_path, "copyrighted")

    with pytest.raises(SystemExit) as exc:
        cli(str(ws), *flags)

    assert exc.value.code == 1
    assert cli.uploads == [], f"{flags} uploaded a blocked series"


def test_cli_skip_to_publish_positive_control_public_domain(tmp_path, cli):
    """The same harness DOES reach the upload when the book is public domain —
    so the blocked case above is the gate, not a broken harness."""
    ws = _complete_ws(tmp_path, "public_domain")

    cli(str(ws), "--skip-to", "publish")

    assert len(cli.uploads) == 1


# ─── rights sidecar via the CLI ─────────────────────────────────────────────


def _make_epub(path: Path) -> Path:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("ledger-test")
    book.set_title("The Ledger Test Book")
    book.set_language("en")
    book.add_author("Fixture Author")
    ch = epub.EpubHtml(title="One", file_name="ch1.xhtml", lang="en")
    ch.content = f"<h1>One</h1><p>{SOURCE_TEXT}</p>"
    book.add_item(ch)
    book.toc = (ch,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", ch]
    epub.write_epub(str(path), book)
    return path


@pytest.fixture
def workspaces(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", root)
    return root


def _only_ws(root: Path) -> Path:
    (ws,) = [p for p in root.iterdir() if p.is_dir()]
    return ws


def test_cli_rights_flag_is_frozen_into_sidecar_at_creation(tmp_path, cli, workspaces):
    epub_path = _make_epub(tmp_path / "book.epub")

    cli(str(epub_path), "--rights", "public_domain", "--dry-run")

    assert (_only_ws(workspaces) / ".rights").read_text().strip() == "public_domain"


def test_cli_creation_without_rights_flag_defaults_to_copyrighted(
    tmp_path, cli, workspaces
):
    epub_path = _make_epub(tmp_path / "book.epub")

    cli(str(epub_path), "--dry-run")

    assert (_only_ws(workspaces) / ".rights").read_text().strip() == "copyrighted"


def test_cli_resume_cannot_change_frozen_rights(tmp_path, cli, capsys):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)

    with pytest.raises(SystemExit) as exc:
        cli(str(ws), "--rights", "public_domain", "--dry-run")

    assert exc.value.code == 2
    assert "frozen" in capsys.readouterr().err
    assert (ws / ".rights").read_text().strip() == "copyrighted"


def test_cli_legacy_workspace_cannot_be_relabelled_on_resume(tmp_path, cli, capsys):
    ws = _ws(tmp_path, rights=None, script=CLEAN_SCRIPT)

    with pytest.raises(SystemExit) as exc:
        cli(str(ws), "--rights", "public_domain", "--dry-run")

    assert exc.value.code == 2
    assert "fail closed" in capsys.readouterr().err
    assert not (ws / ".rights").exists() or (
        (ws / ".rights").read_text().strip() == "copyrighted"
    )


# ─── prompts + plan-review validator ────────────────────────────────────────


@pytest.fixture
def captured_prompts(monkeypatch):
    prompts: list[str] = []

    def _fake(cmd, workspace, label, log, timeout, prompt=None):
        prompts.append(prompt or "")
        return True, 0.0

    monkeypatch.setattr(pipeline, "_run_claude_with_retry", _fake)
    return prompts


@pytest.mark.parametrize("rights", ["copyrighted", "licensed", None])
def test_architect_prompt_never_offers_full_text_for_non_public_domain(
    tmp_path, captured_prompts, rights
):
    ws = _ws(tmp_path, rights=rights, script=CLEAN_SCRIPT)

    assert pipeline.stage_architect(ws, _FakeLog()) is True

    (prompt,) = captured_prompts
    assert "full_text" not in prompt
    assert "key_passages" in prompt
    assert "RIGHTS POLICY" in prompt
    assert "{rights_policy}" not in prompt and "{strategy_options}" not in prompt


def test_architect_prompt_offers_full_text_for_public_domain(
    tmp_path, captured_prompts
):
    ws = _ws(tmp_path, rights="public_domain", script=CLEAN_SCRIPT)

    pipeline.stage_architect(ws, _FakeLog())

    (prompt,) = captured_prompts
    strategy_line = next(l for l in prompt.splitlines() if "**Strategy**:" in l)
    assert "full_text" in strategy_line


def test_scriptwriter_and_reviewer_prompts_carry_rights_policy(
    tmp_path, captured_prompts
):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)

    pipeline.run_scriptwriter(ws, 1)
    pipeline.run_script_reviewer(ws, 1)

    assert len(captured_prompts) == 2
    for prompt in captured_prompts:
        assert "RIGHTS POLICY" in prompt
        assert "full_text" not in prompt
        assert "{rights_policy}" not in prompt


def _plan(ws: Path, strategy: str) -> None:
    (ws / "plan" / "episodes" / "ep_01.md").write_text(
        "# Episode 1: The Ledger\n\n## Overview\n"
        "- **Source chapters**: ch_01.md\n"
        f"- **Strategy**: {strategy}\n\n"
        "## Opening\n- **Strategy**: cold_open\n"
    )


@pytest.fixture
def passing_reviewer(monkeypatch):
    calls: list[str] = []

    def _fake_run_claude(prompt, workspace, label, log, **kw):
        calls.append(label)
        (workspace / "plan" / "review.md").write_text("# Plan Review\nOverall: PASS\n")
        return True

    monkeypatch.setattr(pipeline, "run_claude", _fake_run_claude)
    return calls


def test_plan_review_fails_on_full_text_strategy_for_copyrighted(
    tmp_path, passing_reviewer
):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)
    _plan(ws, "full_text")
    log = _FakeLog()

    assert pipeline.stage_plan_review(ws, log) is False
    assert passing_reviewer == ["Plan Review"], "positive control: reviewer ran"
    assert any("ep_01.md" in e and "full_text" in e for e in log.errors), log.errors


def test_plan_review_passes_full_text_for_public_domain(tmp_path, passing_reviewer):
    ws = _ws(tmp_path, rights="public_domain", script=CLEAN_SCRIPT)
    _plan(ws, "full_text")

    assert pipeline.stage_plan_review(ws, _FakeLog()) is True


def test_plan_review_passes_commentary_strategy_for_copyrighted(
    tmp_path, passing_reviewer
):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)
    _plan(ws, "key_passages")

    assert pipeline.stage_plan_review(ws, _FakeLog()) is True


def test_plan_review_fails_closed_on_corrupt_sidecar(tmp_path, passing_reviewer):
    ws = _ws(tmp_path, rights="public_domain", script=CLEAN_SCRIPT)
    (ws / ".rights").write_text("public-ish\n")
    _plan(ws, "key_passages")
    log = _FakeLog()

    assert pipeline.stage_plan_review(ws, log) is False
    assert any(".rights" in e or "rights" in e.lower() for e in log.errors), log.errors


def test_plan_review_provenance_records_strategy_violation(tmp_path):
    ws = _ws(tmp_path, rights="copyrighted", script=CLEAN_SCRIPT)
    _plan(ws, "full_text")
    (ws / "plan" / "review.md").write_text("# Plan Review\nOverall: PASS\n")

    prov = pipeline.write_stage_provenance(
        ws,
        stage="plan-review",
        success=False,
        elapsed_s=0.1,
        input_artifacts={},
        only_episode=None,
    )

    result = prov["validator_result"]
    assert result["status"] == "fail"
    assert result["full_text_strategy"] == ["plan/episodes/ep_01.md"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
