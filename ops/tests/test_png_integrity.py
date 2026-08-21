from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load():
    ops = ROOT / "ops"
    if str(ops) not in sys.path:
        sys.path.insert(0, str(ops))
    spec = importlib.util.spec_from_file_location("png_integrity", ops / "png_integrity.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _indexed_png(*, include_plte: bool) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 3, 0, 0, 0)
    chunks = [_chunk(b"IHDR", ihdr)]
    if include_plte:
        chunks.append(_chunk(b"PLTE", b"\x00\x00\x00"))
    chunks.extend(
        [
            _chunk(b"IDAT", zlib.compress(b"\x00\x00")),
            _chunk(b"IEND", b""),
        ]
    )
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def test_png_metadata_rejects_indexed_color_without_plte(tmp_path):
    mod = _load()
    path = tmp_path / "indexed-without-plte.png"
    path.write_bytes(_indexed_png(include_plte=False))

    with pytest.raises(ValueError, match="PLTE"):
        mod.png_metadata(path)


def test_png_metadata_accepts_indexed_color_with_plte(tmp_path):
    mod = _load()
    path = tmp_path / "indexed-with-plte.png"
    path.write_bytes(_indexed_png(include_plte=True))

    metadata = mod.png_metadata(path)

    assert metadata["width"] == 1
    assert metadata["height"] == 1
