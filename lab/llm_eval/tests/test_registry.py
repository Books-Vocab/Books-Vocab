"""Tests for prompt registry."""

from __future__ import annotations

import pytest

from llm_eval.registry import PromptRegistry


def test_load_manifest(tmp_prompts_dir):
    registry = PromptRegistry(prompts_dir=tmp_prompts_dir)
    assert registry.list_prompts() == ["test_prompt"]
    assert registry.list_versions("test_prompt") == ["v1"]


def test_get_meta(tmp_prompts_dir):
    registry = PromptRegistry(prompts_dir=tmp_prompts_dir)
    meta = registry.get_meta("test_prompt", "v1")
    assert meta.name == "test_prompt"
    assert meta.version == "v1"
    assert meta.source_of_truth == "backend/test.py:test_fn"


def test_get_meta_latest(tmp_prompts_dir):
    registry = PromptRegistry(prompts_dir=tmp_prompts_dir)
    meta = registry.get_meta("test_prompt")
    assert meta.version == "v1"


def test_render(tmp_prompts_dir):
    registry = PromptRegistry(prompts_dir=tmp_prompts_dir)
    rendered = registry.render("test_prompt", word="hello")
    assert rendered.name == "test_prompt"
    assert rendered.version == "v1"
    assert rendered.system is None
    assert "hello" in rendered.user
    assert rendered.response_format == {"type": "json_object"}


def test_render_missing_prompt(tmp_prompts_dir):
    registry = PromptRegistry(prompts_dir=tmp_prompts_dir)
    with pytest.raises(KeyError):
        registry.render("nonexistent")


def test_render_with_system_section(tmp_prompts_dir):
    tpl = tmp_prompts_dir / "test_v1.md"
    tpl.write_text(
        "## System\nYou are a test assistant.\n\n"
        "## User\nTest: {{ word }}\n",
        encoding="utf-8",
    )
    registry = PromptRegistry(prompts_dir=tmp_prompts_dir)
    rendered = registry.render("test_prompt", word="hello")
    assert rendered.system == "You are a test assistant."
    assert "hello" in rendered.user


def test_version_natural_sort_and_latest(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    versions = "".join(f"      - id: {v}\n        file: {v}.md\n" for v in ("v2", "v10", "v9"))
    (prompts_dir / "manifest.yaml").write_text(
        "prompts:\n  - name: p\n    versions:\n" + versions, encoding="utf-8"
    )
    registry = PromptRegistry(prompts_dir=prompts_dir)
    assert registry.list_versions("p") == ["v2", "v9", "v10"]
    assert registry.get_meta("p").version == "v10"


def _ds(monkeypatch, tmp_path, text):
    from llm_eval import datasets

    (tmp_path / "d.jsonl").write_text(text, encoding="utf-8")
    monkeypatch.setattr(datasets, "_DATASET_DIR", tmp_path)
    return datasets


def test_load_dataset_ok(monkeypatch, tmp_path):
    ds = _ds(monkeypatch, tmp_path, '{"id": 1}\n\n{"id": 2}\n')
    assert ds.load_dataset("d") == [{"id": 1}, {"id": 2}]


def test_load_dataset_non_dict_row(monkeypatch, tmp_path):
    ds = _ds(monkeypatch, tmp_path, '{"id": 1}\n[1, 2]\n')
    with pytest.raises(ValueError, match=r"d\.jsonl:2"):
        ds.load_dataset("d")


def test_load_dataset_corrupt_line(monkeypatch, tmp_path):
    ds = _ds(monkeypatch, tmp_path, '{"id": 1}\n{"id": \n')
    with pytest.raises(ValueError, match=r"d\.jsonl:2"):
        ds.load_dataset("d")


def test_load_dataset_rejects_traversal(monkeypatch, tmp_path):
    ds = _ds(monkeypatch, tmp_path, "{}\n")
    with pytest.raises(ValueError):
        ds.load_dataset("../x")
