"""Unit tests for kg.routers.podcast_media helpers.

These exercise the DI-style pure functions that the podcast router delegates
to.  No real S3 or filesystem I/O — every external dependency is injected as a
callable so tests remain hermetic and fast.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from kg.routers import podcast_media as media_mod


# ---------------------------------------------------------------------------
# _media_type_for
# ---------------------------------------------------------------------------

class TestMediaTypeFor:
    def test_m4a_returns_audio_mp4(self):
        assert media_mod._media_type_for("audio.m4a") == "audio/mp4"

    def test_mp3_returns_audio_mpeg(self):
        assert media_mod._media_type_for("audio.mp3") == "audio/mpeg"

    def test_any_non_m4a_returns_audio_mpeg(self):
        assert media_mod._media_type_for("audio.wav") == "audio/mpeg"


# ---------------------------------------------------------------------------
# _read_json_file
# ---------------------------------------------------------------------------

class TestReadJsonFile:
    def test_reads_valid_json(self, tmp_path, monkeypatch):
        path = tmp_path / "meta.json"
        path.write_text('{"title": "x"}', encoding="utf-8")
        result = media_mod._read_json_file(path, context="metadata", logger_=MagicMock())
        assert result == {"title": "x"}

    def test_raises_500_on_malformed_json(self, tmp_path, monkeypatch):
        path = tmp_path / "meta.json"
        path.write_text("not json", encoding="utf-8")
        mock_logger = MagicMock()
        with pytest.raises(HTTPException) as ei:
            media_mod._read_json_file(path, context="metadata", logger_=mock_logger)
        assert ei.value.status_code == 500
        assert "Malformed metadata" in ei.value.detail
        mock_logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _is_s3_not_found
# ---------------------------------------------------------------------------

class TestIsS3NotFound:
    def test_nosuchkey_exception(self):
        class _FakeS3:
            class exceptions:
                class NoSuchKey(Exception):
                    pass

        exc = _FakeS3.exceptions.NoSuchKey()
        assert media_mod._is_s3_not_found(exc, _FakeS3()) is True

    def test_response_code_nosuchkey(self):
        class _NoSuchKey(Exception):
            pass

        class _FakeS3:
            exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)

        exc = Exception()
        exc.response = {"Error": {"Code": "NoSuchKey"}}
        assert media_mod._is_s3_not_found(exc, _FakeS3()) is True

    def test_response_code_404(self):
        class _NoSuchKey(Exception):
            pass

        class _FakeS3:
            exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)

        exc = Exception()
        exc.response = {"Error": {"Code": "404"}}
        assert media_mod._is_s3_not_found(exc, _FakeS3()) is True

    def test_other_exception_returns_false(self):
        class _NoSuchKey(Exception):
            pass

        class _FakeS3:
            exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)

        exc = Exception("access denied")
        assert media_mod._is_s3_not_found(exc, _FakeS3()) is False

    def test_none_response_returns_false(self):
        class _NoSuchKey(Exception):
            pass

        class _FakeS3:
            exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)

        exc = Exception()
        exc.response = None
        assert media_mod._is_s3_not_found(exc, _FakeS3()) is False


# ---------------------------------------------------------------------------
# _s3_static_headers
# ---------------------------------------------------------------------------

class TestS3StaticHeaders:
    def test_content_length_and_etag(self):
        obj = {"ContentLength": 42, "ETag": '"abc"'}
        headers = media_mod._s3_static_headers(obj)
        assert headers["Content-Length"] == "42"
        assert headers["ETag"] == '"abc"'

    def test_last_modified_with_timestamp(self):
        ts = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
        obj = {"LastModified": ts}
        headers = media_mod._s3_static_headers(obj)
        assert headers["Last-Modified"] == "Sat, 06 Jun 2026 12:00:00 GMT"

    def test_last_modified_without_timestamp(self):
        obj = {"LastModified": "some-string"}
        headers = media_mod._s3_static_headers(obj)
        assert headers["Last-Modified"] == "some-string"

    def test_base_headers_preserved(self):
        obj = {"ContentLength": 10}
        base = {"Cache-Control": "max-age=3600"}
        headers = media_mod._s3_static_headers(obj, base)
        assert headers["Cache-Control"] == "max-age=3600"
        assert headers["Content-Length"] == "10"

    def test_omits_none_fields(self):
        obj = {}
        headers = media_mod._s3_static_headers(obj)
        assert "Content-Length" not in headers
        assert "ETag" not in headers
        assert "Last-Modified" not in headers


# ---------------------------------------------------------------------------
# _iter_s3_body
# ---------------------------------------------------------------------------

class TestIterS3Body:
    def test_yields_chunks_and_closes(self):
        class _FakeBody:
            def __init__(self):
                self.closed = False
                self._chunks = [b"ab", b"cd", b""]
                self._idx = 0

            def read(self, size):
                chunk = self._chunks[self._idx]
                self._idx += 1
                return chunk

            def close(self):
                self.closed = True

        body = _FakeBody()
        chunks = list(media_mod._iter_s3_body(body, chunk_size=2))
        assert chunks == [b"ab", b"cd"]
        assert body.closed is True

    def test_closes_on_exception(self):
        class _FakeBody:
            def __init__(self):
                self.closed = False

            def read(self, size):
                raise RuntimeError("boom")

            def close(self):
                self.closed = True

        body = _FakeBody()
        with pytest.raises(RuntimeError, match="boom"):
            next(media_mod._iter_s3_body(body, chunk_size=2))
        assert body.closed is True

    def test_ignores_close_exception(self):
        class _FakeBody:
            def read(self, size):
                return b""

            def close(self):
                raise RuntimeError("close failed")

        body = _FakeBody()
        # Should not raise despite close() failing
        chunks = list(media_mod._iter_s3_body(body, chunk_size=2))
        assert chunks == []


# ---------------------------------------------------------------------------
# _read_bytes_from_s3
# ---------------------------------------------------------------------------

class TestReadBytesFromS3:
    def test_returns_bytes(self):
        def _get_obj(req, key, *, context):
            return {"Body": SimpleNamespace(read=lambda: b"hello")}

        result = media_mod._read_bytes_from_s3(
            None, "s1/cover.png", context="cover", get_object_from_s3=_get_obj
        )
        assert result == b"hello"

    def test_returns_none_when_object_missing(self):
        def _get_obj(req, key, *, context):
            return None

        result = media_mod._read_bytes_from_s3(
            None, "s1/cover.png", context="cover", get_object_from_s3=_get_obj
        )
        assert result is None


# ---------------------------------------------------------------------------
# _get_object_from_s3
# ---------------------------------------------------------------------------

class TestGetObjectFromS3:
    def test_returns_object(self):
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {"Body": b"x"}

        def _s3_client(req):
            return fake_s3

        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        result = media_mod._get_object_from_s3(
            None,
            "s1/cover.png",
            context="cover",
            settings_fn=_settings,
            s3_client_fn=_s3_client,
            is_s3_not_found_fn=lambda exc, s3: False,
            logger_=MagicMock(),
        )
        assert result == {"Body": b"x"}
        fake_s3.get_object.assert_called_once_with(Bucket="bucket", Key="s1/cover.png")

    def test_returns_none_on_not_found(self):
        class _NoSuchKey(Exception):
            pass

        fake_s3 = MagicMock()
        fake_s3.exceptions.NoSuchKey = _NoSuchKey
        fake_s3.get_object.side_effect = _NoSuchKey()

        def _s3_client(req):
            return fake_s3

        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        result = media_mod._get_object_from_s3(
            None,
            "s1/cover.png",
            context="cover",
            settings_fn=_settings,
            s3_client_fn=_s3_client,
            is_s3_not_found_fn=lambda exc, s3: True,
            logger_=MagicMock(),
        )
        assert result is None

    def test_raises_502_on_s3_error(self):
        fake_s3 = MagicMock()
        fake_s3.get_object.side_effect = Exception("network")

        def _s3_client(req):
            return fake_s3

        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        mock_logger = MagicMock()
        with pytest.raises(HTTPException) as ei:
            media_mod._get_object_from_s3(
                None,
                "s1/cover.png",
                context="cover",
                settings_fn=_settings,
                s3_client_fn=_s3_client,
                is_s3_not_found_fn=lambda exc, s3: False,
                logger_=mock_logger,
            )
        assert ei.value.status_code == 502
        mock_logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _read_json_from_s3
# ---------------------------------------------------------------------------

class TestReadJsonFromS3:
    def _make_s3(self, body_bytes: bytes | None = None, *, raise_exc: Exception | None = None):
        """Build a fake S3 client for _read_json_from_s3."""
        class _FakeBody:
            def __init__(self, data: bytes):
                self._data = data
            def read(self):
                return self._data

        class _FakeS3:
            def get_object(self, Bucket, Key):  # noqa: N803
                if raise_exc is not None:
                    raise raise_exc
                assert body_bytes is not None
                return {"Body": _FakeBody(body_bytes)}

        return _FakeS3()

    def test_returns_parsed_json(self):
        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        result = media_mod._read_json_from_s3(
            None,
            "s1/metadata.json",
            context="metadata",
            settings_fn=_settings,
            s3_client_fn=lambda req: self._make_s3(b'{"a": 1}'),
            is_s3_not_found_fn=lambda exc, s3: False,
            logger_=MagicMock(),
        )
        assert result == {"a": 1}

    def test_returns_none_when_not_found(self):
        class _NoSuchKey(Exception):
            pass

        class _FakeS3:
            exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)
            def get_object(self, Bucket, Key):  # noqa: N803
                raise _NoSuchKey()

        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        result = media_mod._read_json_from_s3(
            None,
            "s1/metadata.json",
            context="metadata",
            settings_fn=_settings,
            s3_client_fn=lambda req: _FakeS3(),
            is_s3_not_found_fn=lambda exc, s3: True,
            logger_=MagicMock(),
        )
        assert result is None

    def test_raises_500_on_corrupt_json(self):
        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        mock_logger = MagicMock()
        with pytest.raises(HTTPException) as ei:
            media_mod._read_json_from_s3(
                None,
                "s1/metadata.json",
                context="metadata",
                settings_fn=_settings,
                s3_client_fn=lambda req: self._make_s3(b"not json"),
                is_s3_not_found_fn=lambda exc, s3: False,
                logger_=mock_logger,
            )
        assert ei.value.status_code == 500
        assert "Malformed metadata" in ei.value.detail

    def test_raises_502_on_s3_error(self):
        def _settings(req):
            return SimpleNamespace(podcast_bucket="bucket")

        mock_logger = MagicMock()
        with pytest.raises(HTTPException) as ei:
            media_mod._read_json_from_s3(
                None,
                "s1/metadata.json",
                context="metadata",
                settings_fn=_settings,
                s3_client_fn=lambda req: self._make_s3(raise_exc=Exception("s3 down")),
                is_s3_not_found_fn=lambda exc, s3: False,
                logger_=mock_logger,
            )
        assert ei.value.status_code == 502


# ---------------------------------------------------------------------------
# _serve_static_media — disk mode
# ---------------------------------------------------------------------------

class TestServeStaticMediaDisk:
    def test_returns_file_content(self, tmp_path):
        series_dir = tmp_path / "s1"
        series_dir.mkdir()
        cover = series_dir / "cover.png"
        cover.write_bytes(b"\x89PNG fake")

        def _podcasts_dir(req):
            return tmp_path

        resp = media_mod._serve_static_media(
            None,
            "s1",
            "cover.png",
            media_type="image/png",
            context="cover",
            using_s3=lambda req: False,
            get_object_from_s3=None,
            iter_s3_body=None,
            s3_static_headers=None,
            read_bytes_from_s3=None,
            podcasts_dir=_podcasts_dir,
        )
        assert resp.status_code == 200
        assert resp.body == b"\x89PNG fake"
        assert resp.media_type == "image/png"

    def test_raises_404_when_file_missing(self, tmp_path):
        def _podcasts_dir(req):
            return tmp_path

        with pytest.raises(HTTPException) as ei:
            media_mod._serve_static_media(
                None,
                "s1",
                "cover.png",
                media_type="image/png",
                context="cover",
                using_s3=lambda req: False,
                get_object_from_s3=None,
                iter_s3_body=None,
                s3_static_headers=None,
                read_bytes_from_s3=None,
                podcasts_dir=_podcasts_dir,
            )
        assert ei.value.status_code == 404

    def test_applies_transform(self, tmp_path):
        series_dir = tmp_path / "s1"
        series_dir.mkdir()
        subtitle = series_dir / "subtitle.srt"
        subtitle.write_bytes(b"hello")

        def _podcasts_dir(req):
            return tmp_path

        resp = media_mod._serve_static_media(
            None,
            "s1",
            "subtitle.srt",
            media_type="text/plain",
            context="subtitle",
            transform=lambda b: b.upper(),
            using_s3=lambda req: False,
            get_object_from_s3=None,
            iter_s3_body=None,
            s3_static_headers=None,
            read_bytes_from_s3=None,
            podcasts_dir=_podcasts_dir,
        )
        assert resp.body == b"HELLO"


# ---------------------------------------------------------------------------
# _serve_static_media — S3 non-streaming mode
# ---------------------------------------------------------------------------

class TestServeStaticMediaS3:
    def test_returns_response_from_bytes(self):
        def _read_bytes(req, key, *, context):
            return b"s3 content"

        resp = media_mod._serve_static_media(
            None,
            "s1",
            "cover.png",
            media_type="image/png",
            context="cover",
            using_s3=lambda req: True,
            get_object_from_s3=None,
            iter_s3_body=None,
            s3_static_headers=None,
            read_bytes_from_s3=_read_bytes,
            podcasts_dir=None,
        )
        assert resp.status_code == 200
        assert resp.body == b"s3 content"
        assert resp.media_type == "image/png"

    def test_raises_404_when_s3_object_missing(self):
        def _read_bytes(req, key, *, context):
            return None

        with pytest.raises(HTTPException) as ei:
            media_mod._serve_static_media(
                None,
                "s1",
                "cover.png",
                media_type="image/png",
                context="cover",
                using_s3=lambda req: True,
                get_object_from_s3=None,
                iter_s3_body=None,
                s3_static_headers=None,
                read_bytes_from_s3=_read_bytes,
                podcasts_dir=None,
            )
        assert ei.value.status_code == 404

    def test_applies_transform_to_s3_bytes(self):
        def _read_bytes(req, key, *, context):
            return b"hello"

        resp = media_mod._serve_static_media(
            None,
            "s1",
            "subtitle.srt",
            media_type="text/plain",
            context="subtitle",
            transform=lambda b: b.upper(),
            using_s3=lambda req: True,
            get_object_from_s3=None,
            iter_s3_body=None,
            s3_static_headers=None,
            read_bytes_from_s3=_read_bytes,
            podcasts_dir=None,
        )
        assert resp.body == b"HELLO"


# ---------------------------------------------------------------------------
# _serve_static_media — S3 streaming mode
# ---------------------------------------------------------------------------

class TestServeStaticMediaS3Streaming:
    def test_returns_streaming_response(self):
        class _FakeBody:
            def read(self, size):
                return b""

            def close(self):
                pass

        def _get_obj(req, key, *, context):
            return {
                "Body": _FakeBody(),
                "ContentLength": 42,
                "ETag": '"abc"',
            }

        def _iter_body(body, chunk_size=65536):
            return iter([])

        resp = media_mod._serve_static_media(
            None,
            "s1",
            "cover.png",
            media_type="image/png",
            context="cover",
            stream_s3=True,
            using_s3=lambda req: True,
            get_object_from_s3=_get_obj,
            iter_s3_body=_iter_body,
            s3_static_headers=lambda obj, base: {"Content-Length": "42"},
            read_bytes_from_s3=None,
            podcasts_dir=None,
        )
        from fastapi.responses import StreamingResponse

        assert isinstance(resp, StreamingResponse)
        assert resp.headers["content-length"] == "42"

    def test_raises_404_when_streaming_object_missing(self):
        def _get_obj(req, key, *, context):
            return None

        with pytest.raises(HTTPException) as ei:
            media_mod._serve_static_media(
                None,
                "s1",
                "cover.png",
                media_type="image/png",
                context="cover",
                stream_s3=True,
                using_s3=lambda req: True,
                get_object_from_s3=_get_obj,
                iter_s3_body=None,
                s3_static_headers=None,
                read_bytes_from_s3=None,
                podcasts_dir=None,
            )
        assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# _serve_audio_from_s3
# ---------------------------------------------------------------------------

class TestServeAudioFromS3:
    def _request(self, bucket="bucket"):
        return SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    kg_settings=SimpleNamespace(
                        podcast_bucket=bucket,
                        podcast_bucket_region="ap-northeast-1",
                        podcast_bucket_endpoint_url=None,
                    )
                )
            )
        )

    def test_basic_audio_stream(self):
        class _FakeBody:
            def read(self, size):
                return b""

            def close(self):
                pass

        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": _FakeBody(),
            "ContentLength": 1024,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        resp = media_mod._serve_audio_from_s3(
            self._request(),
            "series_x",
            3,
            range_header=None,
            stem="audio",
            settings_fn=media_mod._settings,
            s3_client_fn=lambda req: fake_s3,
            audio_filename=lambda req, sid, ep, stem: "audio.m4a",
            media_type_for=media_mod._media_type_for,
            is_s3_not_found_fn=lambda exc, s3: False,
            iter_s3_body=lambda body, chunk_size=65536: media_mod._iter_s3_body(body, chunk_size),
            logger_=MagicMock(),
        )
        from fastapi.responses import StreamingResponse

        assert isinstance(resp, StreamingResponse)
        assert resp.headers["content-length"] == "1024"
        assert resp.headers["accept-ranges"] == "bytes"
        fake_s3.get_object.assert_called_once_with(
            Bucket="bucket", Key="series_x/ep_03/audio.m4a"
        )

    def test_range_request_passed_through(self):
        class _FakeBody:
            def read(self, size):
                return b""

            def close(self):
                pass

        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": _FakeBody(),
            "ContentLength": 100,
            "ContentRange": "bytes 0-99/1024",
            "ResponseMetadata": {"HTTPStatusCode": 206},
        }

        resp = media_mod._serve_audio_from_s3(
            self._request(),
            "series_x",
            1,
            range_header="bytes=0-99",
            stem="audio",
            settings_fn=media_mod._settings,
            s3_client_fn=lambda req: fake_s3,
            audio_filename=lambda req, sid, ep, stem: "audio.mp3",
            media_type_for=media_mod._media_type_for,
            is_s3_not_found_fn=lambda exc, s3: False,
            iter_s3_body=lambda body, chunk_size=65536: media_mod._iter_s3_body(body, chunk_size),
            logger_=MagicMock(),
        )
        assert resp.status_code == 206
        assert resp.headers["content-range"] == "bytes 0-99/1024"
        fake_s3.get_object.assert_called_once_with(
            Bucket="bucket", Key="series_x/ep_01/audio.mp3", Range="bytes=0-99"
        )

    def test_raises_404_on_audio_not_found(self):
        class _NoSuchKey(Exception):
            pass

        fake_s3 = MagicMock()
        fake_s3.exceptions.NoSuchKey = _NoSuchKey
        fake_s3.get_object.side_effect = _NoSuchKey()

        with pytest.raises(HTTPException) as ei:
            media_mod._serve_audio_from_s3(
                self._request(),
                "series_x",
                1,
                range_header=None,
                stem="audio",
                settings_fn=media_mod._settings,
                s3_client_fn=lambda req: fake_s3,
                audio_filename=lambda req, sid, ep, stem: "audio.m4a",
                media_type_for=media_mod._media_type_for,
                is_s3_not_found_fn=lambda exc, s3: True,
                iter_s3_body=lambda body, chunk_size=65536: media_mod._iter_s3_body(body, chunk_size),
                logger_=MagicMock(),
            )
        assert ei.value.status_code == 404

    def test_raises_416_on_range_not_satisfiable(self):
        class _FakeError(Exception):
            response = {"ResponseMetadata": {"HTTPStatusCode": 416}}

        fake_s3 = MagicMock()
        fake_s3.get_object.side_effect = _FakeError()

        with pytest.raises(HTTPException) as ei:
            media_mod._serve_audio_from_s3(
                self._request(),
                "series_x",
                1,
                range_header="bytes=9999-",
                stem="audio",
                settings_fn=media_mod._settings,
                s3_client_fn=lambda req: fake_s3,
                audio_filename=lambda req, sid, ep, stem: "audio.m4a",
                media_type_for=media_mod._media_type_for,
                is_s3_not_found_fn=lambda exc, s3: False,
                iter_s3_body=lambda body, chunk_size=65536: media_mod._iter_s3_body(body, chunk_size),
                logger_=MagicMock(),
            )
        assert ei.value.status_code == 416

    def test_raises_502_on_s3_error(self):
        fake_s3 = MagicMock()
        fake_s3.get_object.side_effect = Exception("timeout")

        mock_logger = MagicMock()
        with pytest.raises(HTTPException) as ei:
            media_mod._serve_audio_from_s3(
                self._request(),
                "series_x",
                1,
                range_header=None,
                stem="audio",
                settings_fn=media_mod._settings,
                s3_client_fn=lambda req: fake_s3,
                audio_filename=lambda req, sid, ep, stem: "audio.m4a",
                media_type_for=media_mod._media_type_for,
                is_s3_not_found_fn=lambda exc, s3: False,
                iter_s3_body=lambda body, chunk_size=65536: media_mod._iter_s3_body(body, chunk_size),
                logger_=mock_logger,
            )
        assert ei.value.status_code == 502
        mock_logger.error.assert_called_once()
