"""Decode OpenAI-style multimodal message content into files the Claude CLI can Read.

The Claude Code CLI has no native image-input channel in ``-p`` mode, but its
Read tool renders image files visually.  This module flattens any list-form
message ``content`` into a plain string, writing embedded images to disk so the
prompt can reference them by path for the CLI to Read.

Only base64-encoded ``data:`` URLs are accepted.  Remote http(s) image URLs are
deliberately rejected: fetching them server-side would expose the gateway host
(which sits next to the production API and host credentials) to SSRF, and a
DNS-rebinding-safe fetcher is out of scope here.
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import Any

MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 15 MB per image (decoded)
MAX_IMAGES = 20                     # per request


class ImageError(ValueError):
    """Raised when a multimodal image block cannot be decoded."""


# --- format detection -------------------------------------------------------

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def _sniff_ext(data: bytes) -> str:
    """Return a file extension from image magic bytes, or raise ImageError."""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ImageError("unsupported image format (expected PNG, JPEG, GIF or WebP)")


# --- URL resolution ---------------------------------------------------------

def _decode_data_url(url: str) -> bytes:
    """Decode a ``data:<mime>;base64,<payload>`` URL into raw bytes."""
    if "," not in url:
        raise ImageError("malformed data URL (missing comma separator)")
    header, payload = url.split(",", 1)
    if ";base64" not in header:
        raise ImageError("only base64-encoded data URLs are supported")
    # Reject before decoding: base64 inflates ~4:3, so cap the encoded length
    # to avoid allocating a huge buffer for an over-limit image.
    if len(payload) > MAX_IMAGE_BYTES * 4 // 3 + 16:
        raise ImageError(
            f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB size limit"
        )
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageError(f"invalid base64 image data: {exc}") from exc


def _resolve_image(url: str) -> bytes:
    """Resolve an image_url value to validated raw bytes (data: URLs only)."""
    if not url.startswith("data:"):
        raise ImageError(
            "image_url must be a base64-encoded data: URL "
            "(remote http(s) image URLs are not supported)"
        )
    data = _decode_data_url(url)
    if not data:
        raise ImageError("empty image data")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB size limit"
        )
    return data


# --- message normalization --------------------------------------------------

def _get(msg: Any, key: str) -> Any:
    return msg.get(key) if isinstance(msg, dict) else getattr(msg, key, None)


def _set(msg: Any, key: str, value: Any) -> None:
    if isinstance(msg, dict):
        msg[key] = value
    else:
        setattr(msg, key, value)


def normalize_messages(messages: list[Any], image_dir: str) -> int:
    """Flatten list-form message content to plain strings, in place.

    Each ``image_url`` block is decoded, written into *image_dir* as
    ``image_N.<ext>``, and replaced by a text reference instructing Claude to
    Read the file.  ``text`` blocks are concatenated.  Plain-string content is
    left untouched.

    Returns the number of images written.  Raises ImageError on any malformed
    image or storage failure.
    """
    image_count = 0
    for msg in messages:
        content = _get(msg, "content")
        if not isinstance(content, list):
            continue
        text_parts: list[str] = []
        image_files: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text")
                if text:
                    text_parts.append(str(text))
            elif btype == "image_url":
                raw = block.get("image_url")
                url = raw.get("url") if isinstance(raw, dict) else raw
                if not url or not isinstance(url, str):
                    raise ImageError("image_url block missing a 'url' string")
                if image_count >= MAX_IMAGES:
                    raise ImageError(f"too many images (limit {MAX_IMAGES})")
                data = _resolve_image(url)
                ext = _sniff_ext(data)
                image_count += 1
                fname = f"image_{image_count}.{ext}"
                try:
                    with open(os.path.join(image_dir, fname), "wb") as fh:
                        fh.write(data)
                except OSError as exc:
                    raise ImageError(f"failed to store image: {exc}") from exc
                image_files.append(fname)
            # unknown block types are ignored
        flattened = " ".join(p for p in text_parts if p).strip()
        if image_files:
            listing = ", ".join(image_files)
            flattened = (
                f"{flattened}\n\n"
                f"[The user attached {len(image_files)} image file(s) "
                f"in the current directory: {listing}. "
                f"Use the Read tool to view each file before answering.]"
            ).strip()
        _set(msg, "content", flattened)
    return image_count
