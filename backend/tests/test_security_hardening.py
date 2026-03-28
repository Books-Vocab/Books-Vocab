"""Tests for security hardening: notebook_id path traversal & transaction_id format."""
from __future__ import annotations

import pytest

from kg.service_factories import _resolve_notebook_paths


class TestNotebookIdPathTraversal:
    def test_valid_notebook_id(self, tmp_path):
        paths = _resolve_notebook_paths(tmp_path, "my-notebook_1", [("graph_{nb}.json", "graph.json")])
        assert len(paths) == 1

    @pytest.mark.parametrize("bad_id", [
        "../../etc/passwd",
        "../secret",
        "foo/bar",
        "foo\\bar",
        ".hidden",
        "",
        "a b c",
        "nb;rm -rf /",
        "nb\x00evil",
    ])
    def test_rejects_path_traversal(self, tmp_path, bad_id):
        with pytest.raises(ValueError, match="Invalid notebook_id"):
            _resolve_notebook_paths(tmp_path, bad_id, [("graph_{nb}.json", "graph.json")])


class TestTransactionIdFormat:
    def test_valid_transaction_id(self):
        from kg.app_store import fetch_transaction_info
        # We can't actually call the async function, but we test the validation
        # by importing the validator directly
        from kg.app_store import _validate_transaction_id
        _validate_transaction_id("123456789")

    @pytest.mark.parametrize("bad_id", [
        "abc",
        "12.34",
        "",
        "123; DROP TABLE",
        "../../../etc/passwd",
        "123\n456",
    ])
    def test_rejects_non_numeric_transaction_id(self, bad_id):
        from kg.app_store import _validate_transaction_id
        with pytest.raises(ValueError, match="Invalid transaction_id"):
            _validate_transaction_id(bad_id)
