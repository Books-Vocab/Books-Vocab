"""Shared ops test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_delivery_operation_lock(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep tests off the real, shared delivery mutation lock.

    The lock is non-blocking and fail-closed in production, so a real delivery
    running concurrently would otherwise turn unrelated tests red with
    "delivery mutation already in progress".  Subprocesses inherit the env var.
    """
    lock_dir: Path = tmp_path_factory.mktemp("delivery-locks")
    monkeypatch.setenv("KG_DELIVERY_LOCK_DIR", str(lock_dir))
    # Operators and daemons export the opt-in wait (=120); an inherited value
    # would turn tests that expect an immediate busy refusal into long stalls.
    monkeypatch.delenv("KG_DELIVERY_LOCK_WAIT_SECONDS", raising=False)
