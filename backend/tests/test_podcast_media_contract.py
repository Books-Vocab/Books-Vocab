from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import kg.routers.podcast_media as media_mod


def test_podcast_media_module_exports_named_helper_surface():
    expected = {
        "_S3_AUDIO_FMT_CACHE",
        "_audio_filename",
        "_get_object_from_s3",
        "_is_s3_not_found",
        "_iter_s3_body",
        "_media_type_for",
        "_podcasts_dir",
        "_read_bytes_from_s3",
        "_read_json_file",
        "_read_json_from_s3",
        "_s3_audio_format",
        "_s3_client",
        "_s3_client_cached",
        "_s3_static_headers",
        "_serve_audio_from_s3",
        "_serve_static_media",
        "_settings",
        "_using_s3",
    }

    missing = [name for name in sorted(expected) if not hasattr(media_mod, name)]
    assert not missing, f"Missing podcast media helpers: {missing}"


def test_s3_reversed_range_is_forwarded_for_416_semantics():
    calls = []

    class _RangeError(Exception):
        response = {"ResponseMetadata": {"HTTPStatusCode": 416}}

    class _FakeS3:
        def get_object(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("Range") == "bytes=10-5":
                raise _RangeError()
            return {
                "Body": SimpleNamespace(read=lambda size: b"", close=lambda: None),
                "ContentLength": 1,
                "ResponseMetadata": {"HTTPStatusCode": 200},
            }

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                kg_settings=SimpleNamespace(
                    podcast_bucket="bucket",
                    podcast_bucket_region="us-east-1",
                    podcast_bucket_endpoint_url=None,
                )
            )
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        media_mod._serve_audio_from_s3(
            request,
            "series_a",
            1,
            "bytes=10-5",
            stem="audio",
            settings_fn=media_mod._settings,
            s3_client_fn=lambda _request: _FakeS3(),
            audio_filename=lambda _request, _series_id, _ep_num, stem: f"{stem}.mp3",
            media_type_for=media_mod._media_type_for,
            is_s3_not_found_fn=lambda _exc, _s3: False,
            iter_s3_body=lambda body, chunk_size=65536: iter(()),
            logger_=SimpleNamespace(error=lambda *args, **kwargs: None),
        )

    assert exc_info.value.status_code == 416
    assert calls == [
        {
            "Bucket": "bucket",
            "Key": "series_a/ep_01/audio.mp3",
            "Range": "bytes=10-5",
        }
    ]
