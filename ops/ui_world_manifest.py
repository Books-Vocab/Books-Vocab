#!/usr/bin/env -S uv run --python 3.13 python
"""Validate UI World v2 manifest files before a tool launches the app."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCHEMA = "kg.fixture.dataset.v2"
FIXTURE_TOP_LEVEL_KEYS = {
    "schema",
    "datasetID",
    "assets",
    "preferences",
    "auth",
    "entitlements",
    "settings",
    "bookshelf",
    "todayReview",
    "notebook",
    "podcast",
    "runtimePodcast",
    "reader",
    "vocabulary",
    "reviewDeck",
    "syncPresenter",
}
ASSET_BUCKETS = {"books", "audio", "images", "subtitles", "text"}
ASSET_REQUIRED_KEYS = {"sourcePath", "sha256", "installAs", "byteSize", "contentType"}


class UIWorldManifestError(ValueError):
    pass


def _ensure_str(raw: Any, *, field: str, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise UIWorldManifestError(f"{label} {field} 必須是非空字串")
    return raw


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_install_as(value: str, *, field: str, label: str) -> None:
    path = Path(value)
    parts = path.parts
    if path.is_absolute() or value in {"", ".", ".."} or any(part in {"", ".", ".."} for part in parts):
        raise UIWorldManifestError(f"{label} {field}.installAs 必須是安全相對路徑")
    if "/" not in value:
        raise UIWorldManifestError(f"{label} {field}.installAs 必須含安裝目錄")


def validate_fixture_dataset_file(path: Path, *, label: str = "UI World dataset") -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UIWorldManifestError(f"{label} 不是可讀 JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UIWorldManifestError(f"{label} top-level 必須是 object: {path}")
    if data.get("schema") != FIXTURE_SCHEMA:
        raise UIWorldManifestError(f"{label} schema 必須是 {FIXTURE_SCHEMA}: {path}")
    keys = set(data)
    if keys != FIXTURE_TOP_LEVEL_KEYS:
        extra = sorted(keys - FIXTURE_TOP_LEVEL_KEYS)
        missing = sorted(FIXTURE_TOP_LEVEL_KEYS - keys)
        raise UIWorldManifestError(
            f"{label} top-level keys 不符合 UI World v2: extra={extra} missing={missing}"
        )
    dataset_id = data.get("datasetID")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise UIWorldManifestError(f"{label} datasetID 必須是非空字串: {path}")

    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise UIWorldManifestError(f"{label} assets 必須是 object: {path}")
    asset_keys = set(assets)
    if asset_keys != ASSET_BUCKETS:
        extra = sorted(asset_keys - ASSET_BUCKETS)
        missing = sorted(ASSET_BUCKETS - asset_keys)
        raise UIWorldManifestError(
            f"{label} assets buckets 不符合 UI World v2: extra={extra} missing={missing}"
        )
    for bucket in sorted(ASSET_BUCKETS):
        entries = assets[bucket]
        if not isinstance(entries, dict):
            raise UIWorldManifestError(f"{label} assets.{bucket} 必須是 object: {path}")
        for asset_id, asset in sorted(entries.items()):
            asset_label = f"assets.{bucket}.{asset_id}"
            if not isinstance(asset_id, str) or not asset_id:
                raise UIWorldManifestError(f"{label} {asset_label} key 必須是非空字串")
            if not isinstance(asset, dict):
                raise UIWorldManifestError(f"{label} {asset_label} 必須是 object")
            keys = set(asset)
            missing = sorted(ASSET_REQUIRED_KEYS - keys)
            extra = sorted(keys - ASSET_REQUIRED_KEYS)
            if missing or extra:
                raise UIWorldManifestError(
                    f"{label} {asset_label} keys 不符合 UI World v2: extra={extra} missing={missing}"
                )
            source_path = _resolve_path(_ensure_str(asset.get("sourcePath"), field=f"{asset_label}.sourcePath", label=label))
            install_as = _ensure_str(asset.get("installAs"), field=f"{asset_label}.installAs", label=label)
            content_type = _ensure_str(asset.get("contentType"), field=f"{asset_label}.contentType", label=label)
            expected_hash = _ensure_str(asset.get("sha256"), field=f"{asset_label}.sha256", label=label)
            expected_size = asset.get("byteSize")
            _validate_install_as(install_as, field=asset_label, label=label)
            if "/" not in content_type:
                raise UIWorldManifestError(f"{label} {asset_label}.contentType 必須是 MIME type")
            if len(expected_hash) != 64 or any(ch not in "0123456789abcdef" for ch in expected_hash):
                raise UIWorldManifestError(f"{label} {asset_label}.sha256 必須是 64 字元小寫 hex")
            if not isinstance(expected_size, int) or expected_size <= 0:
                raise UIWorldManifestError(f"{label} {asset_label}.byteSize 必須是正整數")
            if not source_path.is_file():
                raise UIWorldManifestError(f"{label} {asset_label}.sourcePath 不存在: {source_path}")
            actual_size = source_path.stat().st_size
            if actual_size != expected_size:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.byteSize mismatch: expected {expected_size}, got {actual_size}"
                )
            actual_hash = _sha256_hex(source_path)
            if actual_hash != expected_hash:
                raise UIWorldManifestError(
                    f"{label} {asset_label}.sha256 mismatch: expected {expected_hash}, got {actual_hash}"
                )
    return dataset_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    validate = sub.add_parser("validate", help="validate one UI World v2 dataset")
    validate.add_argument("path", type=Path)
    validate.add_argument("--label", default="UI World dataset")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        try:
            dataset_id = validate_fixture_dataset_file(args.path, label=args.label)
        except UIWorldManifestError as exc:
            print(str(exc), file=sys.stderr)
            return 64
        print(dataset_id)
        return 0
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
