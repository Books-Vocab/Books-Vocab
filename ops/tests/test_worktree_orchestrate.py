"""Compatibility collector for historical acceptance commands.

The executable test bodies live in the behavior-group modules.  This module
re-exports them so old ``pytest .../test_worktree_orchestrate.py -k ...``
commands keep their node-name contract without making the legacy path part of
the normal dispatcher.
"""

from test_worktree_orchestrate_planning import *  # noqa: F401,F403
from test_worktree_orchestrate_gate import *  # noqa: F401,F403
from test_worktree_orchestrate_lifecycle import *  # noqa: F401,F403
from test_worktree_orchestrate_claims import *  # noqa: F401,F403
from test_worktree_orchestrate_delivery import *  # noqa: F401,F403
from test_worktree_orchestrate_recovery import *  # noqa: F401,F403
