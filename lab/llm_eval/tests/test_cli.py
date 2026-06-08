"""Tests for the unified CLI dispatcher."""

from __future__ import annotations

import json

import pytest

from llm_eval.cli import main


def test_no_subcommand_prints_help(capsys):
    code = main([])
    assert code == 2
    assert "llm-eval" in capsys.readouterr().out


def test_help_shows_subcommands(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("eval", "prompts", "datasets", "providers", "corpus-build", "gold-queue"):
        assert cmd in out


def test_prompts_list(capsys):
    code = main(["prompts"])
    assert code == 0
    out = capsys.readouterr().out
    assert "translate_quick" in out


def test_prompts_list_json(capsys):
    code = main(["prompts", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    names = [item["name"] for item in data]
    assert "translate_quick" in names


def test_prompts_detail_json(capsys):
    code = main(["prompts", "--name", "translate_quick", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "translate_quick"
    assert "schema" in data


def test_prompts_unknown_name(capsys):
    code = main(["prompts", "--name", "nonexistent_prompt"])
    assert code == 1
    assert "Error" in capsys.readouterr().err


def test_datasets_list(capsys):
    code = main(["datasets"])
    assert code == 0
    out = capsys.readouterr().out
    assert "translate_quick" in out


def test_datasets_list_json(capsys):
    code = main(["datasets", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert any(d["name"] == "translate_quick" for d in data)
    assert all("rows" in d for d in data)


def test_datasets_detail_json(capsys):
    code = main(["datasets", "--name", "translate_quick", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "translate_quick"
    assert data["rows"] > 0
    assert "preview" in data
    assert len(data["preview"]) <= 3


def test_datasets_unknown_name(capsys):
    code = main(["datasets", "--name", "nonexistent_dataset"])
    assert code == 1
    assert "Error" in capsys.readouterr().err


def test_providers_list(capsys):
    code = main(["providers"])
    assert code == 0
    out = capsys.readouterr().out
    assert "ollama" in out


def test_providers_list_json(capsys):
    code = main(["providers", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    names = [p["name"] for p in data]
    assert "ollama" in names


def test_eval_requires_args(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["eval"])
    assert exc_info.value.code == 2


def test_corpus_build_shows_help(capsys):
    code = main(["corpus-build"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Build ignored private candidate corpora" in out


def test_gold_queue_shows_help(capsys):
    code = main(["gold-queue"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Sample private candidates" in out
