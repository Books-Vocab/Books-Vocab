"""Pipeline integration tests.

Verifies that POST /api/pipeline triggers the background pipeline
(Enrich -> Link -> Difficulty) and completes without errors.

External APIs (Gemini enrich, embedding) are mocked. Difficulty (Zipf) and
candidate-link evaluation run against an empty graph, so no LLM calls needed.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from conftest import _DummyEmbeddingStore, _swap_settings, make_jwt

os.environ.setdefault("KG_DATA_DIR", "/tmp/kg_test_default")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-ci-at-least-32-bytes")
os.environ.setdefault("GEMINI_API_KEY", "fake-key")

import kg.api as api_mod  # noqa: E402
import kg.deps as deps_mod  # noqa: E402
import kg.routers.pipeline as pipeline_router_mod  # noqa: E402
import kg.routers.vocab as vocab_router_mod  # noqa: E402
from kg.api import app  # noqa: E402
from kg.settings import KGSettings

_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


@pytest.fixture()
def pipeline_api(tmp_path):
    (tmp_path / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = tmp_path / "users.json"
    tmp_path / "users.json.lock"
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
    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(data_dir=tmp_path, jwt_secret=_JWT_SECRET)
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client, user_id=user_id, headers=headers, data_dir=tmp_path,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


class TestPipelineIntegration:

    def test_pipeline_runs_to_completion(self, pipeline_api, caplog):
        """Pipeline must complete all stages and log 'Pipeline completed' with no ERROR logs."""
        client = pipeline_api.client
        headers = pipeline_api.headers
        emb = _DummyEmbeddingStore()

        # Add a card (no pos/note -> enrich step will have work to do)
        with patch.object(vocab_router_mod, "_embedding_store", return_value=emb):
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
            patch.object(pipeline_router_mod, "_embedding_store", return_value=emb),
            patch("kg.enrich.enrich_cards_stream", _fake_enrich),
            caplog.at_level(logging.INFO, logger="kg.api"),
        ):
            r = client.post("/api/pipeline", headers=headers)
            assert r.status_code == 200
            assert r.json()["status"] == "queued"
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if any("Pipeline completed" in rec.message for rec in caplog.records):
                    break
                time.sleep(0.05)

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
        with patch.object(pipeline_router_mod, "_embedding_store", return_value=emb):
            r = pipeline_api.client.post("/api/pipeline", headers=pipeline_api.headers)
        assert r.status_code == 200
        body = r.json()
        assert "status" in body
        assert "message" in body
