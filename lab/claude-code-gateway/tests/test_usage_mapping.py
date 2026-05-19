"""Tests for OpenAI-style usage mapping from Claude CLI output."""

from src.routes.chat_completions import _usage_from_result


class TestUsageFromResult:
    """Map Claude CLI `usage` to OpenAI UsageInfo."""

    def test_full_usage_sums_all_input_categories(self):
        result = {"usage": {
            "input_tokens": 9,
            "cache_creation_input_tokens": 31968,
            "cache_read_input_tokens": 100,
            "output_tokens": 137,
        }}
        u = _usage_from_result(result)
        assert u.prompt_tokens == 9 + 31968 + 100
        assert u.completion_tokens == 137
        assert u.total_tokens == 9 + 31968 + 100 + 137
        assert u.prompt_tokens_details is not None
        assert u.prompt_tokens_details.cached_tokens == 100

    def test_no_cache_read_omits_details(self):
        result = {"usage": {"input_tokens": 5, "output_tokens": 10}}
        u = _usage_from_result(result)
        assert u.prompt_tokens == 5
        assert u.completion_tokens == 10
        assert u.total_tokens == 15
        assert u.prompt_tokens_details is None

    def test_missing_usage_is_all_zero(self):
        u = _usage_from_result({"result": "hi"})
        assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (0, 0, 0)
        assert u.prompt_tokens_details is None

    def test_usage_none_is_all_zero(self):
        u = _usage_from_result({"usage": None})
        assert u.total_tokens == 0
