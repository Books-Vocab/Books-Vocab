"""Pipeline integration tests.

Verifies that POST /api/pipeline triggers the full 4-stage background pipeline
(Enrich → Link → Difficulty → Mochi Sync) and completes without errors.

External APIs (Gemini enrich, embedding) are mocked. Difficulty (Zipf) and
candidate-link evaluation run against an empty graph, so no LLM calls needed.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KG_DATA_DIR", "/tmp/kg_test_default")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-ci-at-least-32-bytes")
os.environ.setdefault("GEMINI_API_KEY", "fake-key")

import kg.api as api_mod  # noqa: E402
from kg.api import app  # noqa: E402

_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def _make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")


@pytest.fixture()
def pipeline_api(tmp_path):
    (tmp_path / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = tmp_path / "users.json"
    lock_file = tmp_path / "users.json.lock"
    users_file.write_text(
        json.dumps(
            {
                user_id: {
                    "config": {},
                    "subscription": {
                        "product_id": "kg.pro.monthly",
                        "status": "active",
                        "is_active": True,
                        "is_trial": True,
                        "expires_at": "2099-01-01T00:00:00Z",
                        "environment": "xcode",
                        "source": "tests",
                    },
                }
            }
        )
    )
    token = _make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    with (
        patch.object(api_mod, "DATA_DIR", tmp_path),
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
    ):
        api_mod._USER_LOCKS.clear()
        api_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client, user_id=user_id, headers=headers, data_dir=tmp_path,
        )


class _DummyEmbeddingStore:
    def __init__(self):
        self._ids: set[str] = set()

    def has(self, card_id: str) -> bool:
        return card_id in self._ids

    def add(self, card_id: str, text: str) -> None:
        self._ids.add(card_id)

    def find_similar(self, card_id: str, k: int = 3):
        return []


class TestPipelineIntegration:

    def test_pipeline_runs_to_completion(self, pipeline_api, caplog):
        """Pipeline must complete all stages and log 'Pipeline completed' with no ERROR logs."""
        client = pipeline_api.client
        headers = pipeline_api.headers
        emb = _DummyEmbeddingStore()

        # Add a card (no pos/note → enrich step will have work to do)
        with patch.object(api_mod, "_embedding_store", return_value=emb):
            r = client.post(
                "/api/vocab",
                json=[{"word": "serendipity", "translation": "意外之喜"}],
                headers=headers,
            )
            assert r.status_code == 200, r.text

        # Mock enrich stream to avoid real Gemini API call
        async def _fake_enrich(client, targets, **kwargs):
            for card in targets:
                yield {
                    "status": "ok",
                    "results": [{"word": card.content, "pos": "n.", "note": "test note"}],
                }

        with (
            patch.object(api_mod, "_embedding_store", return_value=emb),
            patch("kg.enrich.enrich_cards_stream", _fake_enrich),
            caplog.at_level(logging.INFO, logger="kg.api"),
        ):
            r = client.post("/api/pipeline", headers=headers)
            assert r.status_code == 200
            assert r.json()["status"] == "queued"
            time.sleep(0.5)

        completed = [rec for rec in caplog.records if "Pipeline completed" in rec.message]
        assert completed, (
            "Expected 'Pipeline completed' log.\n"
            f"Logs: {[(r.levelname, r.message) for r in caplog.records if r.levelno >= logging.INFO]}"
        )
        error_logs = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
        assert not error_logs, f"Unexpected ERROR logs: {[r.message for r in error_logs]}"

    def test_pipeline_response_schema(self, pipeline_api):
        """POST /api/pipeline must immediately return {status, message} with HTTP 200."""
        emb = _DummyEmbeddingStore()
        with patch.object(api_mod, "_embedding_store", return_value=emb):
            r = pipeline_api.client.post("/api/pipeline", headers=pipeline_api.headers)
        assert r.status_code == 200
        body = r.json()
        assert "status" in body
        assert "message" in body
