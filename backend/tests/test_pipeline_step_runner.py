"""Tests for pipeline step execution helper."""
import logging
import pytest
from kg.pipeline_service import _run_step


@pytest.mark.asyncio
async def test_run_step_success():
    called = []

    async def step():
        called.append(True)

    await _run_step("test_user", "TestStep", step, logger=logging.getLogger("test"))
    assert called == [True]


@pytest.mark.asyncio
async def test_run_step_catches_errors():
    async def failing_step():
        raise ValueError("boom")

    # Should not raise
    await _run_step("test_user", "FailStep", failing_step, logger=logging.getLogger("test"))
