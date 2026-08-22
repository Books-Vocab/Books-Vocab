"""Compatibility facade for machine-verified same-owner merge-front reanchor."""

from worktree_reanchor_core.cli import add_parser, cmd_reanchor
from worktree_reanchor_core.domain import EXIT_BLOCK, EXIT_OK, SCHEMA
from worktree_reanchor_core.errors import ReanchorRefused
from worktree_reanchor_core.transaction import perform_reanchor

__all__ = (
    "EXIT_BLOCK",
    "EXIT_OK",
    "SCHEMA",
    "ReanchorRefused",
    "add_parser",
    "cmd_reanchor",
    "perform_reanchor",
)
