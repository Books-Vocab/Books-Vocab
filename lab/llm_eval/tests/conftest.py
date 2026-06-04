"""Test fixtures for llm_eval."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure llm_eval package and backend/src are on path
_EVAL_ROOT = Path(__file__).parent.parent
if str(_EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_EVAL_ROOT))

_BACKEND_SRC = Path(__file__).parent.parent.parent.parent / "backend" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

import pytest


@pytest.fixture
def tmp_prompts_dir(tmp_path):
    """Create a temporary prompts directory with a minimal manifest."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    manifest = prompts_dir / "manifest.yaml"
    manifest.write_text(
        'prompts:\n'
        '  - name: test_prompt\n'
        '    versions:\n'
        '      - id: v1\n'
        '        file: test_v1.md\n'
        '        source_of_truth: backend/test.py:test_fn\n'
        '        tags: [test]\n'
        '        schema:\n'
        '          required_keys: [output]\n'
        '          response_format: json_object\n',
        encoding="utf-8",
    )
    tpl = prompts_dir / "test_v1.md"
    tpl.write_text(
        "## User\nTest: {{ word }}\nOutput JSON: { \"output\": \"...\" }\n",
        encoding="utf-8",
    )
    return prompts_dir
