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
