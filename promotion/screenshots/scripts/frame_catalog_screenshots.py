#!/usr/bin/env -S uv run python
"""Frame raw catalog screenshots via WithFrame and write reusable iPhone PNGs."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
import sys
import uuid
from pathlib import Path
from urllib import request


UPLOAD_URL = "https://shot.withfra.me/new"
FRAME_COLOR = "black"
S3_URL_PATTERN = re.compile(r'https://withframe\.s3[^"]+')
PAGE_URL_PATTERN = re.compile(r"https://withfra\.me/s/[^\s\"']+")


def _multipart_body(field_name: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"----CodexFrame{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return body, boundary


def _upload_screenshot(path: Path) -> str:
    body, boundary = _multipart_body("file", path.name, path.read_bytes())
    req = request.Request(
        UPLOAD_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        payload = response.read().decode("utf-8", errors="replace")
    match = PAGE_URL_PATTERN.search(payload)
    if not match:
        raise SystemExit(f"WithFrame upload failed for {path}: no session page returned")
    return match.group(0)


def _download_framed_png(page_url: str) -> bytes:
    color_url = f"{page_url}?color={FRAME_COLOR}"
    with request.urlopen(color_url, timeout=60) as response:
        html_text = response.read().decode("utf-8", errors="replace")
    urls = sorted({html.unescape(match.group(0)) for match in S3_URL_PATTERN.finditer(html_text)})
    if not urls:
        raise SystemExit(f"WithFrame page {color_url} did not expose any S3 frame URL")
    framed_url = urls[0]
    with request.urlopen(framed_url, timeout=60) as response:
        return response.read()


def _load_shots(path: Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit("shots json 必須是 array")
    return raw


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    shots = _load_shots(args.shots_json)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        raw_path = Path(str(shot["rawPath"]))
        source_stem = str(shot["sourceStem"])
        page_url = _upload_screenshot(raw_path)
        framed_png = _download_framed_png(page_url)
        target = args.output_dir / f"{source_stem}.png"
        target.write_bytes(framed_png)
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
