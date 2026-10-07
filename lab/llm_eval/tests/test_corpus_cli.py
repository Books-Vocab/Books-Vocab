"""Tests for private corpus CLI entrypoints."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from llm_eval.corpus_cli import main

# Derived from this file, not from the code under test.
_LAB_ROOT = Path(__file__).resolve().parents[1]


def _write_dump(tmp_path: Path) -> Path:
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "content": "resplendent",
                        "meaning": "輝煌的",
                        "pos": "adj.",
                        "root_form": "resplendent",
                        "examples": ["The robe was **resplendent**."],
                        "review_count": 2,
                        "last_review_feedback": 1,
                    },
                    {
                        "content": "stamped out",
                        "meaning": "被徹底消滅",
                        "pos": "phr.",
                        "examples": ["The fire was **stamped out**."],
                        "review_count": 4,
                        "last_review_feedback": 0,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return dump_path


def _git_repo(path: Path, gitignore: str | None = None) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if gitignore is not None:
        (path / ".gitignore").write_text(gitignore, encoding="utf-8")
    return path


def test_build_private_corpus_cli_writes_outputs_and_summary(tmp_path, capsys):
    dump_path = _write_dump(tmp_path)
    output_dir = tmp_path / "private_corpus"

    exit_code = main([str(dump_path), "--output-dir", str(output_dir), "--limit", "10"])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["output_dir"] == str(output_dir)
    assert "dump_path" not in summary
    assert summary["files"]["translate_quick"]["rows"] == 2
    assert summary["files"]["translate_phrase"]["rows"] == 1
    assert summary["files"]["translate_explain"]["rows"] == 2
    assert (output_dir / "translate_quick_candidates.jsonl").exists()


def test_build_private_corpus_cli_rejects_unsafe_context_chars(tmp_path):
    dump_path = tmp_path / "dump.json"
    dump_path.write_text(json.dumps({"cards": []}), encoding="utf-8")

    exit_code = main([str(dump_path), "--context-chars", "0"])

    assert exit_code == 2


def test_default_output_dir_resolves_against_package_root_not_cwd(
    tmp_path, monkeypatch
):
    """From a cwd inside some checkout, the default must still be the
    git-ignored <package>/private_corpus, not <cwd>/private_corpus."""
    captured: list[Path] = []

    def _fake_build(dump_path, output_dir, **kwargs):
        captured.append(Path(output_dir))
        return {}

    monkeypatch.setattr("llm_eval.corpus_cli.build_private_corpus", _fake_build)
    dump_path = _write_dump(tmp_path)
    monkeypatch.chdir(_git_repo(tmp_path / "some_checkout"))

    exit_code = main([str(dump_path)])

    assert exit_code == 0
    assert [p.resolve() for p in captured] == [_LAB_ROOT / "private_corpus"]


def test_refuses_an_output_dir_git_would_let_you_commit(tmp_path, capsys):
    repo = _git_repo(tmp_path / "repo")
    output_dir = repo / "corpus"

    exit_code = main([str(_write_dump(tmp_path)), "--output-dir", str(output_dir)])

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "not git-ignored" in err
    assert "--allow-unignored" in err
    assert not output_dir.exists()


def test_allow_unignored_writes_into_a_committable_dir(tmp_path, capsys):
    output_dir = _git_repo(tmp_path / "repo") / "corpus"

    exit_code = main(
        [
            str(_write_dump(tmp_path)),
            "--output-dir",
            str(output_dir),
            "--allow-unignored",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "translate_quick_candidates.jsonl").exists()


def test_git_ignored_output_dir_needs_no_override(tmp_path, capsys):
    output_dir = _git_repo(tmp_path / "repo", gitignore="corpus/\n") / "corpus"

    exit_code = main([str(_write_dump(tmp_path)), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "translate_quick_candidates.jsonl").exists()


def test_build_private_corpus_script_wrapper_can_show_help():
    script = _LAB_ROOT / "scripts" / "build_private_corpus.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=_LAB_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Build ignored private candidate corpora" in result.stdout
