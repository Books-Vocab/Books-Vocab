from __future__ import annotations

from kg.api import app


def _schema_for(method: str, path: str, status: str = "200") -> dict:
    app.openapi_schema = None
    schema = app.openapi()
    return schema["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]


def test_podcast_catalog_endpoints_have_named_response_models():
    list_schema = _schema_for("get", "/api/podcasts")
    detail_schema = _schema_for("get", "/api/podcasts/{series_id}")

    assert list_schema["type"] == "array"
    assert list_schema["items"]["$ref"].endswith("/PodcastSeriesSummary")
    assert detail_schema["$ref"].endswith("/PodcastSeriesDetail")


def test_podcast_progress_endpoints_have_named_response_models():
    list_schema = _schema_for("get", "/api/podcasts/progress")
    post_schema = _schema_for("post", "/api/podcasts/{series_id}/{ep_num}/progress")
    get_schema = _schema_for("get", "/api/podcasts/{series_id}/{ep_num}/progress")

    assert list_schema["$ref"].endswith("/PodcastProgressListResponse")
    assert post_schema["$ref"].endswith("/PodcastProgressResponse")
    assert get_schema["$ref"].endswith("/PodcastProgressResponse")
