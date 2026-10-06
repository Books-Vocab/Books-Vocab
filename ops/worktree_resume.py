"""Compatibility facade for exact same-owner published-claim resume."""

from worktree_reanchor_core.resume_cli import add_parser, cmd_resume
from worktree_reanchor_core.resume_domain import EXIT_BLOCK, EXIT_OK, SCHEMA
from worktree_reanchor_core.resume_transaction import perform_resume

__all__ = (
    "EXIT_BLOCK",
    "EXIT_OK",
    "SCHEMA",
    "add_parser",
    "cmd_resume",
    "perform_resume",
)
