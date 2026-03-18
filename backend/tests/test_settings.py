"""Tests for KGSettings defaults."""
from kg.settings import KGSettings
from pathlib import Path


def test_settings_has_llm_defaults():
    s = KGSettings(data_dir=Path("/tmp"), jwt_secret="x" * 16)
    assert s.gemini_model == "gemini-2.5-flash-lite"
    assert s.gemini_temperature == 0.3
    assert s.judge_temperature == 0.1
    assert s.similarity_threshold == 0.70
    assert s.candidate_k == 20
    assert s.max_batch_size == 500
    assert s.max_word_length == 200
