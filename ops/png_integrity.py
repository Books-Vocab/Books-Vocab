"""Minimal structural PNG validation shared by UI evidence readers.

The evidence contract hashes bytes, but a hash alone does not prove that the
bytes are an actual screenshot.  Validate the PNG signature, IHDR, chunk CRCs,
and IEND without requiring Pillow so fail-closed checks work in every runner.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_metadata(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 33 or data[:8] != PNG_SIGNATURE:
        raise ValueError(f"not a PNG: {path}")

    offset = 8
    idat_data = bytearray()
    seen_idat_end = False
    color_type = bit_depth = None
    saw_ihdr = False
    saw_plte = False
    saw_idat = False
    saw_iend = False
    width = height = 0
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError(f"truncated PNG chunk header: {path}")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError(f"truncated PNG chunk {chunk_type!r}: {path}")
        chunk_data = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"PNG chunk CRC mismatch {chunk_type!r}: {path}")

        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13:
                raise ValueError(f"PNG must contain exactly one 13-byte IHDR: {path}")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width <= 0 or height <= 0:
                raise ValueError(f"PNG has invalid dimensions {width}x{height}: {path}")
            if compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise ValueError(f"PNG has invalid IHDR encoding fields: {path}")
            valid_bit_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if color_type not in valid_bit_depths or bit_depth not in valid_bit_depths[color_type]:
                raise ValueError(f"PNG has invalid IHDR color fields: {path}")
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if not saw_ihdr or saw_iend:
                raise ValueError(f"PNG IDAT is out of order: {path}")
            if seen_idat_end:
                raise ValueError(f"PNG IDAT chunks are not consecutive: {path}")
            idat_data.extend(chunk_data)
            saw_idat = True
        elif chunk_type == b"PLTE":
            saw_plte = True
            if saw_idat:
                seen_idat_end = True
        elif chunk_type == b"IEND":
            if length != 0 or not saw_ihdr or not saw_idat or saw_iend:
                raise ValueError(f"PNG has invalid IEND: {path}")
            saw_iend = True
            if end != len(data):
                raise ValueError(f"PNG contains trailing bytes after IEND: {path}")
        elif saw_idat:
            seen_idat_end = True
        elif saw_iend:
            raise ValueError(f"PNG contains chunks after IEND: {path}")
        if chunk_type[:1].isupper() and chunk_type not in {b"IHDR", b"IDAT", b"IEND", b"PLTE", b"tRNS"}:
            raise ValueError(f"PNG contains unsupported critical chunk {chunk_type!r}: {path}")
        offset = end

    if not saw_ihdr or not saw_idat or not saw_iend or offset != len(data):
        raise ValueError(f"PNG is structurally incomplete: {path}")
    if color_type == 3 and not saw_plte:
        raise ValueError(f"indexed-color PNG is missing required PLTE: {path}")
    try:
        decoded = zlib.decompress(bytes(idat_data))
    except zlib.error as error:
        raise ValueError(f"PNG IDAT stream is invalid: {path}") from error
    if not decoded:
        raise ValueError(f"PNG IDAT stream is empty: {path}")
    if interlace == 0:
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        row_bytes = (width * channels * bit_depth + 7) // 8
        expected_size = height * (row_bytes + 1)
        if len(decoded) != expected_size:
            raise ValueError(
                f"PNG scanline stream has wrong size: expected {expected_size}, got {len(decoded)}: {path}"
            )
        if any(decoded[row * (row_bytes + 1)] > 4 for row in range(height)):
            raise ValueError(f"PNG contains an invalid scanline filter: {path}")
    return {
        "width": width,
        "height": height,
        "byteSize": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
