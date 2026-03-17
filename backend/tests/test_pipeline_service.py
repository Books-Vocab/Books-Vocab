from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from kg.pipeline_service import run_pipeline_background


class _FakeLogger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.warning_messages: list[str] = []
        self.error_messages: list[str] = []

    def info(self, msg, *args, **kwargs):
        self.info_messages.append(msg % args if args else msg)

    def warning(self, msg, *args, **kwargs):
        self.warning_messages.append(msg % args if args else msg)

    def error(self, msg, *args, **kwargs):
        self.error_messages.append(msg % args if args else msg)


class _CardsOk:
    def all(self, include_deleted: bool = False, notebook_id: str | None = None):
        return [
            SimpleNamespace(
                id="c1",
                content="evoke",
                pos="v.",
                note="note",
                difficulty=None,
                is_deleted=False,
                notebook_id="default",
                embed_text=lambda: "evoke",
            )
        ]

    def update(self, card_id, **kwargs):
        return None

    def get(self, card_id):
        return None


class _GraphOk:
    def pop_candidates(self):
        return []

    def candidate_count(self):
        return 0

    def link_count(self):
        return 0


class _EmbeddingsBoom:
    def has(self, card_id):
        raise RuntimeError("embedding unavailable")


async def _locked_lock():
    lock = asyncio.Lock()
    await lock.acquire()
    return lock


def test_pipeline_service_skips_when_lock_is_held():
    logger = _FakeLogger()
    user = {"id": "u1", "dir": Path("/tmp/u1"), "config": {}}
    lock = asyncio.run(_locked_lock())

    async def get_user_lock_fn(user_id: str):
        return lock

    asyncio.run(
        run_pipeline_background(
            user,
            get_user_lock_fn=get_user_lock_fn,
            card_store_factory=lambda user_dir: _CardsOk(),
            graph_store_factory=lambda user_dir, notebook_id="default": _GraphOk(),
            embedding_store_factory=lambda user_dir, user_id=None, notebook_id="default": _EmbeddingsBoom(),
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda value: value,
        )
    )

    assert any("skipping" in message.lower() for message in logger.info_messages)


def test_pipeline_service_logs_error_when_step_fails():
    logger = _FakeLogger()
    user = {"id": "u2", "dir": Path("/tmp/u2"), "config": {}}

    async def get_user_lock_fn(user_id: str):
        return asyncio.Lock()

    asyncio.run(
        run_pipeline_background(
            user,
            get_user_lock_fn=get_user_lock_fn,
            card_store_factory=lambda user_dir: _CardsOk(),
            graph_store_factory=lambda user_dir, notebook_id="default": _GraphOk(),
            embedding_store_factory=lambda user_dir, user_id=None, notebook_id="default": _EmbeddingsBoom(),
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda value: value,
        )
    )

    assert any("Step 1b" in message for message in logger.error_messages)
    assert any("Pipeline completed." in message for message in logger.info_messages)
