"""Contract for ops/lib/provenance.py — the tool-identity primitive.

A verdict is only as trustworthy as the knowledge of WHO produced it. This module
answers that with a content hash of the tool file itself, which is strictly stronger
than a git commit: it also catches an uncommitted edit to the tool that a commit id
would silently attribute to the committed version.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))
from lib.provenance import logical_tool_path, sha256_file  # noqa: E402


def test_sha256_file_matches_known_digest(tmp_path):
    # sha256("") — the one digest that can be asserted without recomputing it the
    # same way the implementation does (which would make the test tautological).
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    assert sha256_file(empty) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_file_discriminates_one_byte(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"gate")
    b.write_bytes(b"gatf")
    assert sha256_file(a) != sha256_file(b)
    assert len(sha256_file(a)) == 64


def test_sha256_file_spans_chunk_boundary(tmp_path):
    """The streaming reader must not lose bytes across its 1 MiB chunk boundary."""
    big = tmp_path / "big"
    payload = b"x" * (1024 * 1024) + b"TAIL"
    big.write_bytes(payload)
    other = tmp_path / "other"
    other.write_bytes(b"x" * (1024 * 1024) + b"LIAT")
    assert sha256_file(big) != sha256_file(other)


def test_sha256_file_missing_path_raises(tmp_path):
    with pytest.raises(OSError):
        sha256_file(tmp_path / "nope")


def test_logical_tool_path_is_checkout_independent(tmp_path):
    """The logical path is the identity key: the SAME tool in a worktree and in the
    primary checkout must produce the same string, or provenance could not be compared
    across the two — which is the entire point."""
    primary = tmp_path / "kg" / "ops" / "worktree_orchestrate.py"
    worktree = tmp_path / "kg" / ".claude" / "worktrees" / "x" / "ops" / "worktree_orchestrate.py"
    for p in (primary, worktree):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#\n")
    assert logical_tool_path(primary) == "ops/worktree_orchestrate.py"
    assert logical_tool_path(worktree) == "ops/worktree_orchestrate.py"


def test_logical_tool_path_keeps_subdirs_under_ops(tmp_path):
    p = tmp_path / "ops" / "lib" / "provenance.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#\n")
    assert logical_tool_path(p) == "ops/lib/provenance.py"


def test_logical_tool_path_uses_last_ops_segment(tmp_path):
    """A repo that happens to sit under a directory called `ops` must not swallow the
    whole prefix — the RIGHTMOST `ops` is the tool root."""
    p = tmp_path / "ops" / "checkout" / "ops" / "docs_lint.sh"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#\n")
    assert logical_tool_path(p) == "ops/docs_lint.sh"


def test_logical_tool_path_without_ops_falls_back_to_name(tmp_path):
    p = tmp_path / "elsewhere" / "tool.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#\n")
    assert logical_tool_path(p) == "tool.py"


def test_logical_tool_path_resolves_symlinks_on_both_branches(tmp_path):
    """A symlink under ops/ pointing outside it has no ops/-relative identity; reporting
    the LINK's name would claim one the real file does not have."""
    real = tmp_path / "elsewhere" / "real.py"
    real.parent.mkdir(parents=True)
    real.write_text("#\n")
    link = tmp_path / "ops" / "tool.py"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    assert logical_tool_path(link) == "real.py"

    inside = tmp_path / "checkout" / "ops" / "real2.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("#\n")
    link2 = tmp_path / "link2.py"
    link2.symlink_to(inside)
    assert logical_tool_path(link2) == "ops/real2.py"
