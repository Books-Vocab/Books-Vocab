"""``KG_DATA_DIR`` belongs to one pytest process (#2112).

Importing ``kg.api`` builds the global ``app`` from ``KG_DATA_DIR``.  Its
lifespan takes ``<data_dir>/.worker.lock`` without blocking and sweeps that
directory's orphaned rows, and the autouse translate-log fixture deletes every
``translate_log`` row there before each test.  A fixed directory shared the
lock and the rows with every other run on the machine (sibling worktrees, the
in-container admin test matrix): one run's fixtures failed with
``MultipleWorkersError`` or wiped another run's rows.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import SESSION_DATA_DIR

TESTS_DIR = Path(__file__).resolve().parent

# Run conftest.py's module-level code (what pytest executes when loading it)
# and report the data dir it chose; the process then exits, which must remove
# that dir.
_PROBE = """
import importlib.util, json, os, pathlib, sys
sys.path.insert(0, {tests_dir!r})
spec = importlib.util.spec_from_file_location("conftest", {conftest!r})
spec.loader.exec_module(importlib.util.module_from_spec(spec))
root = pathlib.Path(os.environ["KG_DATA_DIR"])
entries = sorted(os.listdir(root)) if root.is_dir() else None
print(json.dumps({{"data_dir": str(root), "entries": entries}}))
"""


def test_global_app_locks_the_process_data_dir():
    """For the whole run ``KG_DATA_DIR`` names conftest's per-process dir, and
    the import-time ``app`` locks it.

    A test module that re-points the variable while being collected either
    builds the global app on that path (if it imports ``kg.api`` first) or
    splits runtime stores, which re-read the variable, from the lock and the
    startup sweep.
    """
    from kg.api import app

    assert Path(os.environ["KG_DATA_DIR"]) == SESSION_DATA_DIR
    lock_path = SESSION_DATA_DIR / ".worker.lock"
    with TestClient(app):
        assert lock_path.is_file()
        fd = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)


def test_each_process_gets_a_fresh_data_dir_removed_at_exit(tmp_path):
    # Stands in for an inherited KG_DATA_DIR, e.g. the production data dir the
    # admin test matrix's pytest subprocess inherits inside the container.
    inherited = tmp_path / "inherited"
    inherited.mkdir()
    probe = _PROBE.format(tests_dir=str(TESTS_DIR), conftest=str(TESTS_DIR / "conftest.py"))

    result = subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, "KG_DATA_DIR": str(inherited)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.splitlines()[-1])
    child_dir = Path(seen["data_dir"])
    assert child_dir not in (inherited, SESSION_DATA_DIR), (
        "each pytest process needs its own data dir, not an inherited or shared one"
    )
    assert seen["entries"] == [], "the per-process data dir must start empty"
    assert not child_dir.exists(), "process exit must remove the per-process data dir"
    assert list(inherited.iterdir()) == []
