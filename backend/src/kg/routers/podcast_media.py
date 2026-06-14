from __future__ import annotations

import json
import logging
from collections.abc import Callable
from email.utils import formatdate
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..podcast_access import FULL_AUDIO_STEM
from ..settings import KGSettings

logger = logging.getLogger(__name__)

_S3_AUDIO_FMT_CACHE: dict[tuple[str | None, str], str] = {}


class S3SettingsProvider(Protocol):
    def __call__(self, request: Request) -> KGSettings:
        ...


class S3ClientProvider(Protocol):
    def __call__(self, request: Request) -> Any:
        ...


class IsS3NotFound(Protocol):
    def __call__(self, exc: Exception, s3: Any) -> bool:
        ...


class ReadJsonFromS3(Protocol):
    def __call__(self, request: Request, key: str, *, context: str) -> Any:
        ...


class AudioFormatResolver(Protocol):
    def __call__(self, request: Request, series_id: str) -> str:
        ...


class GetObjectFromS3(Protocol):
    def __call__(self, request: Request, key: str, *, context: str) -> dict[str, Any] | None:
        ...


class IterS3Body(Protocol):
    def __call__(self, body: Any, chunk_size: int) -> Any:
        ...


class AudioFilenameBuilder(Protocol):
    def __call__(self, request: Request, series_id: str, ep_num: int, *, stem: str = FULL_AUDIO_STEM) -> str:
        ...


class LoggerProtocol(Protocol):
    def error(self, *args: Any, **kwargs: Any) -> None:
        ...


class ReadBytesFromS3(Protocol):
    def __call__(self, request: Request, key: str, *, context: str) -> bytes | None:
        ...


class StaticHeadersBuilder(Protocol):
    def __call__(self, obj: dict[str, Any], base_headers: dict[str, str] | None = None) -> dict[str, str]:
        ...


def _podcasts_dir(request: Request | None = None) -> Path:
    if request is not None:
        return request.app.state.kg_settings.podcasts_dir
    from ..settings import load_settings

    return load_settings().podcasts_dir


def _settings(request: Request) -> KGSettings:
    return request.app.state.kg_settings


def _using_s3(request: Request) -> bool:
    return bool(_settings(request).podcast_bucket)


@lru_cache(maxsize=4)
def _s3_client_cached(region: str, endpoint_url: str | None):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(
            signature_version="s3v4",
            max_pool_connections=32,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _s3_client(request: Request):
    cfg = _settings(request)
    return _s3_client_cached(cfg.podcast_bucket_region, cfg.podcast_bucket_endpoint_url)


def _is_s3_not_found(exc: Exception, s3) -> bool:
    if isinstance(exc, s3.exceptions.NoSuchKey):
        return True
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return code in ("NoSuchKey", "404")


def _s3_audio_format(
    request: Request,
    series_id: str,
    *,
    settings_fn: S3SettingsProvider,
    read_json_from_s3: ReadJsonFromS3,
    s3_client_fn: S3ClientProvider,
    is_s3_not_found_fn: IsS3NotFound,
    logger_: LoggerProtocol,
    cache: dict[tuple[str | None, str], str],
) -> str:
    cfg = settings_fn(request)
    cache_key = (cfg.podcast_bucket, series_id)
    cached = cache.get(cache_key)
    if cached:
        return cached

    fmt: str | None = None
    meta = read_json_from_s3(request, f"{series_id}/metadata.json", context="metadata")
    if isinstance(meta, dict):
        raw = meta.get("audioFormat")
        if isinstance(raw, str) and raw in ("m4a", "mp3"):
            fmt = raw

    if fmt is None:
        s3 = s3_client_fn(request)
        for cand in ("m4a", "mp3"):
            try:
                s3.head_object(Bucket=cfg.podcast_bucket, Key=f"{series_id}/ep_01/audio.{cand}")
                fmt = cand
                break
            except Exception as exc:  # noqa: BLE001
                if is_s3_not_found_fn(exc, s3):
                    continue
                logger_.error(
                    "Podcast audio-format probe failed for %s/ep_01/audio.%s: %s",
                    series_id,
                    cand,
                    exc,
                )
                raise HTTPException(status_code=502, detail="Storage error resolving audio format") from exc

    fmt = fmt or "m4a"
    cache[cache_key] = fmt
    return fmt


def _audio_filename(
    request: Request,
    series_id: str,
    ep_num: int,
    *,
    stem: str = FULL_AUDIO_STEM,
    using_s3: Callable[[Request], bool],
    s3_audio_format: AudioFormatResolver,
    podcasts_dir: Callable[[Request], Path],
) -> str:
    if using_s3(request):
        return f"{stem}.{s3_audio_format(request, series_id)}"
    base = podcasts_dir(request) / series_id / f"ep_{ep_num:02d}"
    for name in (f"{stem}.m4a", f"{stem}.mp3"):
        if (base / name).exists():
            return name
    return f"{stem}.m4a"


def _media_type_for(filename: str) -> str:
    return "audio/mp4" if filename.endswith(".m4a") else "audio/mpeg"


def _read_json_file(path: Path, *, context: str, logger_: LoggerProtocol) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger_.error("Podcast %s corrupt at %s: %s", context, path, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Malformed {context}") from exc


def _read_json_from_s3(
    request: Request,
    key: str,
    *,
    context: str,
    settings_fn: S3SettingsProvider,
    s3_client_fn: S3ClientProvider,
    is_s3_not_found_fn: IsS3NotFound,
    logger_: LoggerProtocol,
) -> Any:
    cfg = settings_fn(request)
    s3 = s3_client_fn(request)
    try:
        obj = s3.get_object(Bucket=cfg.podcast_bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if is_s3_not_found_fn(exc, s3):
            logger_.debug("Podcast %s not found at s3 key %s; using fallback", context, key)
            return None
        logger_.error(
            "Podcast %s S3 read failed for s3://%s/%s: %s",
            context,
            cfg.podcast_bucket,
            key,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Storage error reading {context}") from exc
    body = obj["Body"].read()
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        logger_.error(
            "Podcast %s corrupt in s3://%s/%s: %s",
            context,
            cfg.podcast_bucket,
            key,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Malformed {context}") from exc


def _get_object_from_s3(
    request: Request,
    key: str,
    *,
    context: str,
    settings_fn: S3SettingsProvider,
    s3_client_fn: S3ClientProvider,
    is_s3_not_found_fn: IsS3NotFound,
    logger_: LoggerProtocol,
) -> dict[str, Any] | None:
    s3 = s3_client_fn(request)
    try:
        return s3.get_object(Bucket=settings_fn(request).podcast_bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if is_s3_not_found_fn(exc, s3):
            logger_.debug("Podcast %s not found at s3 key %s; using fallback", context, key)
            return None
        logger_.error("S3 GetObject failed for %s: %s", key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Storage error fetching {context}") from exc


def _read_bytes_from_s3(
    request: Request,
    key: str,
    *,
    context: str,
    get_object_from_s3: GetObjectFromS3,
) -> bytes | None:
    obj = get_object_from_s3(request, key, context=context)
    if obj is None:
        return None
    return obj["Body"].read()


def _s3_static_headers(obj: dict, base_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(base_headers or {})
    content_length = obj.get("ContentLength")
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    if etag := obj.get("ETag"):
        headers["ETag"] = str(etag)
    if last_modified := obj.get("LastModified"):
        if hasattr(last_modified, "timestamp"):
            headers["Last-Modified"] = formatdate(last_modified.timestamp(), usegmt=True)
        else:
            headers["Last-Modified"] = str(last_modified)
    return headers


def _iter_s3_body(body, chunk_size: int):
    try:
        while True:
            buf = body.read(chunk_size)
            if not buf:
                break
            yield buf
    finally:
        try:
            body.close()
        except Exception:  # noqa: BLE001
            logger.warning("podcast media body close failed", exc_info=True)


def _serve_static_media(
    request: Request,
    series_id: str,
    rel_key: str,
    *,
    media_type: str,
    context: str,
    headers: dict[str, str] | None = None,
    transform: Callable[[bytes], bytes | str] = lambda b: b,
    stream_s3: bool = False,
    using_s3: Callable[[Request], bool],
    get_object_from_s3: GetObjectFromS3,
    iter_s3_body: IterS3Body,
    s3_static_headers: StaticHeadersBuilder,
    read_bytes_from_s3: ReadBytesFromS3,
    podcasts_dir: Callable[[Request], Path],
) -> Response | StreamingResponse:
    if using_s3(request) and stream_s3:
        obj = get_object_from_s3(request, f"{series_id}/{rel_key}", context=context)
        if obj is None:
            raise HTTPException(status_code=404, detail=f"{context.capitalize()} not found")
        return StreamingResponse(
            iter_s3_body(obj["Body"]),
            media_type=media_type,
            headers=s3_static_headers(obj, headers),
        )

    if using_s3(request):
        raw = read_bytes_from_s3(request, f"{series_id}/{rel_key}", context=context)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"{context.capitalize()} not found")
        return Response(content=transform(raw), media_type=media_type, headers=headers)

    disk_file = podcasts_dir(request) / series_id / rel_key
    if not disk_file.exists():
        raise HTTPException(status_code=404, detail=f"{context.capitalize()} not found")
    return Response(content=transform(disk_file.read_bytes()), media_type=media_type, headers=headers)


def _serve_audio_from_s3(
    request: Request,
    series_id: str,
    ep_num: int,
    range_header: str | None,
    *,
    stem: str,
    settings_fn: S3SettingsProvider,
    s3_client_fn: S3ClientProvider,
    audio_filename: AudioFilenameBuilder,
    media_type_for: Callable[[str], str],
    is_s3_not_found_fn: IsS3NotFound,
    iter_s3_body: IterS3Body,
    logger_: LoggerProtocol,
) -> StreamingResponse:
    cfg = settings_fn(request)
    s3 = s3_client_fn(request)
    filename = audio_filename(request, series_id, ep_num, stem=stem)
    key = f"{series_id}/ep_{ep_num:02d}/{filename}"
    media_type = media_type_for(filename)

    get_kwargs = {"Bucket": cfg.podcast_bucket, "Key": key}
    if range_header:
        get_kwargs["Range"] = range_header

    try:
        obj = s3.get_object(**get_kwargs)
    except Exception as exc:  # noqa: BLE001
        http_status = (
            int(getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if hasattr(exc, "response")
            else 0
        )
        if is_s3_not_found_fn(exc, s3) or http_status == 404:
            raise HTTPException(status_code=404, detail="Audio not found") from None
        if http_status == 416:
            raise HTTPException(status_code=416, detail="Range not satisfiable") from None
        logger_.error("S3 GetObject failed for %s: %s", key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Storage error fetching audio") from exc

    body = obj["Body"]
    status_code = obj.get("ResponseMetadata", {}).get("HTTPStatusCode", 200)
    content_length = obj.get("ContentLength")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-transform",
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    if "ContentRange" in obj:
        headers["Content-Range"] = obj["ContentRange"]
    return StreamingResponse(
        iter_s3_body(body),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )
