"""Tests for src.utils.multimodal — OpenAI multimodal content normalization."""

import base64
import os

import pytest

from src.utils.multimodal import (
    ImageError,
    _decode_data_url,
    _sniff_ext,
    normalize_messages,
)

# A minimal valid 1x1 PNG.
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4"
    "2mNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)


def _data_url(raw: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


class TestSniffExt:
    """Magic-byte format detection."""

    def test_png(self):
        assert _sniff_ext(PNG_1x1) == "png"

    def test_jpeg(self):
        assert _sniff_ext(b"\xff\xd8\xff\xe0\x00\x10JFIF") == "jpg"

    def test_gif(self):
        assert _sniff_ext(b"GIF89a\x01\x00\x01\x00") == "gif"

    def test_webp(self):
        assert _sniff_ext(b"RIFF\x24\x00\x00\x00WEBPVP8 ") == "webp"

    def test_unknown_raises(self):
        with pytest.raises(ImageError):
            _sniff_ext(b"this is plainly not an image")


class TestDecodeDataUrl:
    """data: URL base64 decoding."""

    def test_valid(self):
        assert _decode_data_url(_data_url(PNG_1x1)) == PNG_1x1

    def test_missing_base64_marker(self):
        with pytest.raises(ImageError):
            _decode_data_url("data:image/png,rawnotbase64")

    def test_missing_comma(self):
        with pytest.raises(ImageError):
            _decode_data_url("data:image/png;base64")

    def test_invalid_base64(self):
        with pytest.raises(ImageError):
            _decode_data_url("data:image/png;base64,!!!not-base64!!!")

    def test_oversize_payload_rejected_before_decode(self, monkeypatch):
        """An over-limit base64 payload is rejected without being decoded."""
        monkeypatch.setattr("src.utils.multimodal.MAX_IMAGE_BYTES", 100)
        huge = "data:image/png;base64," + ("A" * 1000)
        with pytest.raises(ImageError, match="size limit"):
            _decode_data_url(huge)


class TestNormalizeMessages:
    """Flattening list-form content and extracting images to disk."""

    def test_plain_string_untouched(self, tmp_path):
        msgs = [{"role": "user", "content": "hello"}]
        assert normalize_messages(msgs, str(tmp_path)) == 0
        assert msgs[0]["content"] == "hello"
        assert os.listdir(tmp_path) == []

    def test_text_only_list_flattened(self, tmp_path):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi there"}]}]
        assert normalize_messages(msgs, str(tmp_path)) == 0
        assert msgs[0]["content"] == "hi there"

    def test_image_block_written_and_referenced(self, tmp_path):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": _data_url(PNG_1x1)}},
                ],
            }
        ]
        assert normalize_messages(msgs, str(tmp_path)) == 1
        assert os.listdir(tmp_path) == ["image_1.png"]
        assert (tmp_path / "image_1.png").read_bytes() == PNG_1x1
        content = msgs[0]["content"]
        assert "what is this?" in content
        assert "image_1.png" in content
        assert "Read" in content

    def test_multiple_images_numbered(self, tmp_path):
        url = _data_url(PNG_1x1)
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
        assert normalize_messages(msgs, str(tmp_path)) == 2
        assert sorted(os.listdir(tmp_path)) == ["image_1.png", "image_2.png"]

    def test_image_url_as_plain_string(self, tmp_path):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": _data_url(PNG_1x1)},
                ],
            }
        ]
        assert normalize_messages(msgs, str(tmp_path)) == 1

    def test_unsupported_scheme_raises(self, tmp_path):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "ftp://x/y.png"}},
                ],
            }
        ]
        with pytest.raises(ImageError):
            normalize_messages(msgs, str(tmp_path))

    @pytest.mark.parametrize("url", ["http://example.com/x.png",
                                     "https://example.com/x.png"])
    def test_remote_http_url_rejected(self, tmp_path, url):
        """Remote http(s) image URLs are rejected (SSRF guard)."""
        msgs = [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": url}}]}
        ]
        with pytest.raises(ImageError, match="data: URL"):
            normalize_messages(msgs, str(tmp_path))

    def test_missing_url_raises(self, tmp_path):
        msgs = [
            {"role": "user", "content": [{"type": "image_url", "image_url": {}}]}
        ]
        with pytest.raises(ImageError):
            normalize_messages(msgs, str(tmp_path))

    def test_object_attribute_content(self, tmp_path):
        """Works on objects exposing .content (e.g. pydantic ChatMessage)."""

        class Msg:
            def __init__(self):
                self.role = "user"
                self.content = [{"type": "text", "text": "x"}]

        m = Msg()
        normalize_messages([m], str(tmp_path))
        assert m.content == "x"
