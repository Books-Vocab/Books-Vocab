"""Wrapper delegation tests for backend ops entrypoints.

The public CLI paths stay at backend/ops_cli.py and backend/ops_edit.py, but
the heavy implementation should live in importable kg modules so the entrypoint
files can stay thin.
"""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_ops_cli_wrapper_delegates_to_kg_module():
    import ops_cli
    from kg import ops_cli_app

    assert ops_cli.main is ops_cli_app.main
    assert ops_cli._bucket_key is ops_cli_app._bucket_key
    assert ops_cli.cmd_trends is ops_cli_app.cmd_trends


def test_ops_edit_wrapper_delegates_to_kg_module():
    import ops_edit
    from kg import ops_edit_app

    assert ops_edit.main is ops_edit_app.main
    assert ops_edit.cmd_user_create is ops_edit_app.cmd_user_create
    assert ops_edit.cmd_world_restore is ops_edit_app.cmd_world_restore
