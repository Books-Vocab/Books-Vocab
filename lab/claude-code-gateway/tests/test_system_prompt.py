"""Tests for the gateway system-prompt assembly that trims CLI overhead."""

from src.routes.chat_completions import (
    GATEWAY_BASE_SYSTEM,
    GATEWAY_IMAGE_SYSTEM,
    _assemble_system_prompt,
)


class TestAssembleSystemPrompt:
    """Build the --system-prompt value passed to the Claude CLI."""

    def test_text_no_user_system(self):
        assert _assemble_system_prompt(None, has_images=False) == GATEWAY_BASE_SYSTEM

    def test_image_no_user_system(self):
        s = _assemble_system_prompt(None, has_images=True)
        assert s == GATEWAY_IMAGE_SYSTEM
        assert "Read tool" in s
        assert "current directory" in s

    def test_user_system_appended_text(self):
        s = _assemble_system_prompt("Be terse.", has_images=False)
        assert s.startswith(GATEWAY_BASE_SYSTEM)
        assert s.endswith("Be terse.")

    def test_user_system_appended_image(self):
        s = _assemble_system_prompt("Speak French.", has_images=True)
        assert s.startswith(GATEWAY_IMAGE_SYSTEM)
        assert s.endswith("Speak French.")

    def test_empty_user_system_treated_as_none(self):
        assert _assemble_system_prompt("", has_images=False) == GATEWAY_BASE_SYSTEM
