from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from .api_models import (
    AuthVerifyResponse,
    ExplainResponse,
    GraphLinkResponse,
    QuickTranslateResponse,
    VocabAddResponse,
)


def register_routes(
    app: FastAPI,
    *,
    get_privacy_policy: Callable[..., Any],
    get_support: Callable[..., Any],
    list_vocab: Callable[..., Any],
    lookup_word: Callable[..., Any],
    delete_word: Callable[..., Any],
    get_graph_links: Callable[..., Any],
    add_vocab: Callable[..., Any],
    run_pipeline: Callable[..., Any],
    translate_quick: Callable[..., Any],
    translate_phrase: Callable[..., Any],
    translate_explain: Callable[..., Any],
    auth_verify: Callable[..., Any],
    admin_ui: Callable[..., Any],
    admin_stats: Callable[..., Any],
    admin_logs: Callable[..., Any],
    admin_run_tests: Callable[..., Any],
    admin_last_test_run: Callable[..., Any],
    admin_test_catalog: Callable[..., Any],
    admin_tests_ui: Callable[..., Any],
) -> None:
    app.get("/privacy.html", response_class=FileResponse)(get_privacy_policy)
    app.get("/support.html", response_class=FileResponse)(get_support)

    app.get("/api/vocab")(list_vocab)
    app.get("/api/vocab/{word}")(lookup_word)
    app.delete("/api/vocab/{word}")(delete_word)
    app.get("/api/graph/links", response_model=list[GraphLinkResponse])(get_graph_links)
    app.post("/api/vocab", response_model=VocabAddResponse)(add_vocab)
    app.post("/api/pipeline")(run_pipeline)
    app.post("/api/translate/quick", response_model=QuickTranslateResponse)(translate_quick)
    app.post("/api/translate/phrase", response_model=dict)(translate_phrase)
    app.post("/api/translate/explain", response_model=ExplainResponse)(translate_explain)
    app.post("/auth/verify", response_model=AuthVerifyResponse)(auth_verify)

    app.get("/admin", response_class=HTMLResponse, include_in_schema=False)(admin_ui)
    app.get("/api/admin/stats", include_in_schema=False)(admin_stats)
    app.get("/api/admin/logs", include_in_schema=False)(admin_logs)
    app.post("/api/admin/tests/run", include_in_schema=False)(admin_run_tests)
    app.get("/api/admin/tests/last", include_in_schema=False)(admin_last_test_run)
    app.get("/api/admin/tests/catalog", include_in_schema=False)(admin_test_catalog)
    app.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)(admin_tests_ui)
    app.get("/admin/test", response_class=HTMLResponse, include_in_schema=False)(admin_tests_ui)
