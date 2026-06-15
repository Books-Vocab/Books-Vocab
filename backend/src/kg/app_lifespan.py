from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .settings import KGSettings


@dataclass(frozen=True)
class AppLifespanDependencies:
    settings: KGSettings
    logger: logging.Logger | Any
    assert_single_worker_fn: Callable[[Path], None]
    reap_orphaned_runs_fn: Callable[[], int]
    release_worker_lock_fn: Callable[[], None]
    reset_clients_fn: Callable[[], None]
    reset_async_clients_fn: Callable[[], Awaitable[None]]


def build_app_lifespan_from_dependencies(
    *,
    dependencies: AppLifespanDependencies,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        dependencies.logger.info("KG API starting up")
        # Surface (but do not hard-fail on) missing admin credentials: with a
        # blank token/password, require_admin silently rejects every admin call,
        # which is easy to miss in production. Empty values stay valid for
        # test/dev flows by design.
        if not dependencies.settings.admin_token:
            dependencies.logger.warning(
                "admin_token is empty → admin API is disabled "
                "(set ADMIN_TOKEN to enable)"
            )
        if not dependencies.settings.admin_password:
            dependencies.logger.warning(
                "admin_password is empty → admin password login is disabled "
                "(set ADMIN_PASSWORD to enable)"
            )
        dependencies.assert_single_worker_fn(
            dependencies.settings.data_dir / ".worker.lock"
        )
        reaped = dependencies.reap_orphaned_runs_fn()
        if reaped:
            dependencies.logger.info(
                "Reaped %d orphaned pipeline run(s) → interrupted",
                reaped,
            )
        yield
        dependencies.logger.info("KG API shutting down")
        dependencies.release_worker_lock_fn()
        dependencies.reset_clients_fn()
        await dependencies.reset_async_clients_fn()

    return lifespan
