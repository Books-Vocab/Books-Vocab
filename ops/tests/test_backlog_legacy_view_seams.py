"""Focused tests for the legacy import and generated-view seams."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"
sys.path.insert(0, str(OPS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LEGACY = _load("backlog_legacy_under_test", OPS / "backlog_legacy.py")
VIEW = _load("backlog_view_under_test", OPS / "backlog_view.py")


def test_legacy_parser_and_view_keep_pipe_and_id_token_rules():
    assert LEGACY.split_row_raw(r"| IMP-0001 | detail \| safe |") == [
        " IMP-0001 ", r" detail \| safe "
    ]
    assert VIEW.cell("a|b") == r"a\|b"
    assert VIEW.view_entry_ids("| IMP-0001 | x |\n| APP-0002 | y |") == {
        "IMP-0001", "APP-0002"
    }
