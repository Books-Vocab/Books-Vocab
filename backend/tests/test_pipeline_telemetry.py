"""Integration test: pipeline telemetry recording."""

import pytest

from kg import pipeline_log

pytestmark = pytest.mark.usefixtures("isolate_pipeline_db")


def test_run_step_records_telemetry():
    """_run_step should call pipeline_log when run_id is provided."""
    import asyncio
    import logging

    from kg.pipeline_service import _run_step

    logger = logging.getLogger("test")

    async def fake_step():
        return 42

    run_id = "test_run_001"
    pipeline_log.start_run(run_id, "u1", "default", "background")

    asyncio.run(
        _run_step("u1", "TestStep", fake_step, logger=logger, run_id=run_id)
    )

    runs = pipeline_log.get_runs("u1")
    assert len(runs) == 1
    steps = runs[0]["steps"]
    assert len(steps) == 1
    assert steps[0]["name"] == "TestStep"
    assert steps[0]["status"] == "ok"
    assert steps[0]["items"] == 42


def test_run_step_records_failure():
    """_run_step should record failed status on error."""
    import asyncio
    import logging

    from kg.pipeline_service import _run_step

    logger = logging.getLogger("test")

    async def failing_step():
        raise ValueError("test error")

    run_id = "test_run_002"
    pipeline_log.start_run(run_id, "u1", "default", "background")

    asyncio.run(
        _run_step("u1", "FailStep", failing_step, logger=logger, run_id=run_id)
    )

    runs = pipeline_log.get_runs("u1")
    steps = runs[0]["steps"]
    assert steps[0]["status"] == "failed"
    assert "test error" in steps[0]["error"]


def test_run_step_without_run_id_does_not_log():
    """_run_step should not call pipeline_log when run_id is None."""
    import asyncio
    import logging

    from kg.pipeline_service import _run_step

    logger = logging.getLogger("test")

    async def fake_step():
        return 5

    asyncio.run(
        _run_step("u1", "NoLog", fake_step, logger=logger)
    )

    runs = pipeline_log.get_runs("u1")
    assert len(runs) == 0
