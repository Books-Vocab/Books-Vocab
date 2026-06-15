#!/usr/bin/env -S uv run --python 3.13 python
"""Validate UI World v2 manifest files before a tool launches the app."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

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
PREFERENCES_KEYS = {"userDefaults", "ubiquitousKeyValueStore"}
RUNTIME_PODCAST_DOWNLOAD_KEYS = {
    "audioAssetRef",
    "subtitleAssetRef",
    "localAudioPath",
    "localSubtitlePath",
}
BOOKSHELF_SEED_KEYS = {"books", "referenceDate"}
BOOKSHELF_BOOK_KEYS = {
    "title",
    "author",
    "fileName",
    "format",
    "bookAssetRef",
    "progression",
    "preferredNotebookId",
    "dateAdded",
    "dateLastRead",
}
AUTH_REQUIRED_KEYS = {
    "isLoggedIn",
    "userId",
    "token",
    "keychainTokenState",
    "displayName",
    "email",
    "authError",
    "isAuthenticating",
    "provider",
    "providerUserId",
}
BOOK_FORMAT_CONTENT_TYPES = {
    "epub": "application/epub+zip",
    "pdf": "application/pdf",
    "md": "text/markdown",
}


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


def _require_mapping(raw: Any, *, field: str, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise UIWorldManifestError(f"{label} {field} 必須是 object")
    return raw


def _require_list(raw: Any, *, field: str, label: str) -> list[Any]:
    if not isinstance(raw, list):
        raise UIWorldManifestError(f"{label} {field} 必須是 array")
    return raw


def _require_ref(ref: Any, *, prefix: str, refs: set[str], owner: str, label: str) -> str:
    value = _ensure_str(ref, field=owner, label=label).strip()
    if not value.startswith(prefix):
        raise UIWorldManifestError(f"{label} {owner} must reference {prefix}*, got {value}")
    if value not in refs:
        raise UIWorldManifestError(f"{label} {owner} references missing {value}")
    return value


def _validate_exact_keys(value: Mapping[str, Any], *, expected: set[str], owner: str, label: str) -> None:
    keys = set(value)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise UIWorldManifestError(f"{label} {owner} keys 不符合 UI World v2: extra={extra} missing={missing}")


def _validate_download_local_path(
    raw: Any,
    *,
    expected_install_as: str | None,
    owner: str,
    label: str,
) -> None:
    if expected_install_as is None:
        if raw is not None:
            raise UIWorldManifestError(f"{label} {owner} must be null when subtitleAssetRef is null")
        return
    local_path = _ensure_str(raw, field=owner, label=label).strip()
    _validate_install_as(local_path, field=owner, label=label)
    if local_path != expected_install_as:
        raise UIWorldManifestError(
            f"{label} {owner} must match asset installAs {expected_install_as}, got {local_path}"
        )


def _validate_optional_progression(raw: Any, *, owner: str, label: str) -> None:
    if raw is None:
        return
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise UIWorldManifestError(f"{label} {owner} must be null or a number between 0 and 1")
    if raw < 0 or raw > 1:
        raise UIWorldManifestError(f"{label} {owner} must be between 0 and 1, got {raw}")


def _parse_iso8601(raw: Any, *, owner: str, label: str) -> datetime:
    value = _ensure_str(raw, field=owner, label=label).strip()
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise UIWorldManifestError(f"{label} {owner} must be ISO8601, got {value}") from exc


def _validate_optional_iso8601(raw: Any, *, owner: str, label: str) -> datetime | None:
    if raw is None:
        return None
    return _parse_iso8601(raw, owner=owner, label=label)


def _validate_auth_state(data: dict[str, Any], *, label: str) -> None:
    for fixture_id, seed in _require_mapping(data.get("auth"), field="auth", label=label).items():
        seed_obj = _require_mapping(seed, field=f"auth.{fixture_id}", label=label)
        owner = f"auth.{fixture_id}"
        keys = set(seed_obj)
        missing = sorted(AUTH_REQUIRED_KEYS - keys)
        extra = sorted(keys - AUTH_REQUIRED_KEYS)
        if missing or extra:
            raise UIWorldManifestError(
                f"{label} {owner} keys 不符合 UI World v2: extra={extra} missing={missing}"
            )
        is_logged_in = seed_obj.get("isLoggedIn")
        if not isinstance(is_logged_in, bool):
            raise UIWorldManifestError(f"{label} {owner}.isLoggedIn 必須是 bool")
        token_state = _ensure_str(seed_obj.get("keychainTokenState"), field=f"{owner}.keychainTokenState", label=label)
        token = seed_obj.get("token")
        user_id = seed_obj.get("userId")

        if is_logged_in:
            _ensure_str(user_id, field=f"{owner}.userId", label=label)
            if seed_obj.get("isAuthenticating") is True:
                raise UIWorldManifestError(f"{label} {owner} logged-in seed must not also be authenticating")
            if seed_obj.get("authError") is not None:
                raise UIWorldManifestError(f"{label} {owner} logged-in seed must not carry authError")

        if token_state == "available":
            if is_logged_in is not True:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=available requires isLoggedIn=true")
            _ensure_str(token, field=f"{owner}.token", label=label)
        elif token_state == "readFailed":
            if is_logged_in is not True:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=readFailed requires isLoggedIn=true")
            _ensure_str(user_id, field=f"{owner}.userId", label=label)
            if token is not None:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=readFailed must not expose a readable token")
        elif token_state == "absent":
            if is_logged_in:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=absent requires isLoggedIn=false")
            if token is not None:
                raise UIWorldManifestError(f"{label} {owner} keychainTokenState=absent must not include token")
        else:
            raise UIWorldManifestError(f"{label} {owner}.keychainTokenState 不支援: {token_state}")


def _validate_preferences(data: dict[str, Any], *, label: str) -> None:
    preferences = _require_mapping(data.get("preferences"), field="preferences", label=label)
    keys = set(preferences)
    missing = sorted(PREFERENCES_KEYS - keys)
    extra = sorted(keys - PREFERENCES_KEYS)
    if missing or extra:
        raise UIWorldManifestError(
            f"{label} preferences keys 不符合 UI World v2: extra={extra} missing={missing}"
        )

    for domain in sorted(PREFERENCES_KEYS):
        entries = _require_mapping(preferences.get(domain), field=f"preferences.{domain}", label=label)
        for key, value in sorted(entries.items()):
            if not isinstance(key, str) or not key.strip():
                raise UIWorldManifestError(f"{label} preferences.{domain} contains an empty key")
            if not isinstance(value, (str, int, float, bool)) or value is None:
                raise UIWorldManifestError(
                    f"{label} preferences.{domain}.{key} value 必須是 string、number 或 bool"
                )


def _all_notebook_ids(data: dict[str, Any], *, label: str) -> set[str]:
    notebook_ids: set[str] = set()
    for fixture_id, seed in _require_mapping(
        data.get("notebook"),
        field="notebook",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"notebook.{fixture_id}", label=label)
        for index, notebook in enumerate(
            _require_list(
                seed_obj.get("notebooks"),
                field=f"notebook.{fixture_id}.notebooks",
                label=label,
            )
        ):
            notebook_obj = _require_mapping(
                notebook,
                field=f"notebook.{fixture_id}.notebooks[{index}]",
                label=label,
            )
            remote_id = _ensure_str(
                notebook_obj.get("remoteId"),
                field=f"notebook.{fixture_id}.notebooks[{index}].remoteId",
                label=label,
            ).strip()
            notebook_ids.add(remote_id)
    return notebook_ids


def _require_notebook_ref(ref: Any, *, notebook_ids: set[str], owner: str, label: str) -> str:
    value = _ensure_str(ref, field=owner, label=label).strip()
    if value not in notebook_ids:
        raise UIWorldManifestError(f"{label} {owner} references missing notebook {value}")
    return value


def _validate_book_asset_alignment(
    *,
    ref: str,
    asset: dict[str, Any],
    file_name: Any,
    book_format: Any,
    owner: str,
    label: str,
) -> None:
    file_name_value = _ensure_str(file_name, field=f"{owner}.fileName", label=label).strip()
    format_value = _ensure_str(book_format, field=f"{owner}.format", label=label).strip()
    expected_install = f"Books/{file_name_value}"
    if asset.get("installAs") != expected_install:
        raise UIWorldManifestError(
            f"{label} {owner} {ref} installAs must be {expected_install}, got {asset.get('installAs')}"
        )
    expected_content_type = BOOK_FORMAT_CONTENT_TYPES.get(format_value)
    if expected_content_type is None:
        raise UIWorldManifestError(f"{label} {owner}.format 不支援: {format_value}")
    content_type = _ensure_str(asset.get("contentType"), field=f"{owner}.contentType", label=label)
    if not content_type.startswith(expected_content_type):
        raise UIWorldManifestError(
            f"{label} {owner} {ref} contentType must start with {expected_content_type}, got {content_type}"
        )


def _validate_cross_references(data: dict[str, Any], *, label: str) -> None:
    assets = _require_mapping(data.get("assets"), field="assets", label=label)
    asset_refs = {
        f"{bucket}.{asset_id}"
        for bucket, entries in assets.items()
        if isinstance(entries, dict)
        for asset_id in entries
    }
    auth_refs = {
        f"auth.{key}"
        for key in _require_mapping(data.get("auth"), field="auth", label=label)
    }
    entitlements_refs = {
        f"entitlements.{key}"
        for key in _require_mapping(data.get("entitlements"), field="entitlements", label=label)
    }
    notebook_ids = _all_notebook_ids(data, label=label)

    for fixture_id, seed in _require_mapping(
        data.get("settings"),
        field="settings",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"settings.{fixture_id}", label=label)
        auth_ref = _require_ref(
            seed_obj.get("authFixtureRef"),
            prefix="auth.",
            refs=auth_refs,
            owner=f"settings.{fixture_id}.authFixtureRef",
            label=label,
        )
        auth_key = auth_ref.removeprefix("auth.")
        auth_seed = _require_mapping(data["auth"][auth_key], field=auth_ref, label=label)
        auth_state = _require_mapping(
            seed_obj.get("auth"),
            field=f"settings.{fixture_id}.auth",
            label=label,
        )
        if auth_state.get("isLoggedIn") != auth_seed.get("isLoggedIn"):
            raise UIWorldManifestError(
                f"{label} settings.{fixture_id}.auth.isLoggedIn must match {auth_ref}.isLoggedIn"
            )
        if auth_state.get("authError") != auth_seed.get("authError"):
            raise UIWorldManifestError(
                f"{label} settings.{fixture_id}.auth.authError must match {auth_ref}.authError"
            )
        if auth_state.get("isLoggedIn"):
            for field in ("email", "displayName"):
                if auth_state.get(field) != auth_seed.get(field):
                    raise UIWorldManifestError(
                        f"{label} settings.{fixture_id}.auth.{field} must match {auth_ref}.{field}"
                    )

        entitlements_ref = seed_obj.get("entitlementsFixtureRef")
        if entitlements_ref is None:
            if seed_obj.get("subscription") is not None:
                raise UIWorldManifestError(
                    f"{label} settings.{fixture_id} without entitlementsFixtureRef must not declare subscription UI state"
                )
        else:
            ent_ref = _require_ref(
                entitlements_ref,
                prefix="entitlements.",
                refs=entitlements_refs,
                owner=f"settings.{fixture_id}.entitlementsFixtureRef",
                label=label,
            )
            subscription = seed_obj.get("subscription")
            if isinstance(subscription, dict) and not subscription.get("isRefreshing", False):
                ent_key = ent_ref.removeprefix("entitlements.")
                ent_seed = _require_mapping(
                    data["entitlements"][ent_key],
                    field=ent_ref,
                    label=label,
                )
                pro = _require_mapping(ent_seed.get("pro"), field=f"{ent_ref}.pro", label=label)
                if subscription.get("isActive") != pro.get("is_active"):
                    raise UIWorldManifestError(
                        f"{label} settings.{fixture_id}.subscription.isActive must match {ent_ref}.pro.is_active"
                    )

    for fixture_id, seed in _require_mapping(
        data.get("runtimePodcast"),
        field="runtimePodcast",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"runtimePodcast.{fixture_id}", label=label)
        _require_ref(
            seed_obj.get("audioAssetRef"),
            prefix="audio.",
            refs=asset_refs,
            owner=f"runtimePodcast.{fixture_id}.audioAssetRef",
            label=label,
        )
        _require_ref(
            seed_obj.get("subtitleAssetRef"),
            prefix="subtitles.",
            refs=asset_refs,
            owner=f"runtimePodcast.{fixture_id}.subtitleAssetRef",
            label=label,
        )
        preferred_notebook = seed_obj.get("preferredNotebookId")
        if preferred_notebook is not None and str(preferred_notebook).strip():
            _require_notebook_ref(
                preferred_notebook,
                notebook_ids=notebook_ids,
                owner=f"runtimePodcast.{fixture_id}.preferredNotebookId",
                label=label,
            )
        for index, episode in enumerate(
            _require_list(
                seed_obj.get("episodes"),
                field=f"runtimePodcast.{fixture_id}.episodes",
                label=label,
            )
        ):
            episode_obj = _require_mapping(
                episode,
                field=f"runtimePodcast.{fixture_id}.episodes[{index}]",
                label=label,
            )
            download = episode_obj.get("download")
            if download is None:
                continue
            download_obj = _require_mapping(
                download,
                field=f"runtimePodcast.{fixture_id}.episodes[{index}].download",
                label=label,
            )
            download_owner = f"runtimePodcast.{fixture_id}.episodes[{index}].download"
            _validate_exact_keys(
                download_obj,
                expected=RUNTIME_PODCAST_DOWNLOAD_KEYS,
                owner=download_owner,
                label=label,
            )
            audio_ref = _require_ref(
                download_obj.get("audioAssetRef"),
                prefix="audio.",
                refs=asset_refs,
                owner=f"{download_owner}.audioAssetRef",
                label=label,
            )
            audio_asset = _require_mapping(
                assets["audio"][audio_ref.removeprefix("audio.")],
                field=audio_ref,
                label=label,
            )
            _validate_download_local_path(
                download_obj.get("localAudioPath"),
                expected_install_as=_ensure_str(
                    audio_asset.get("installAs"),
                    field=f"{audio_ref}.installAs",
                    label=label,
                ),
                owner=f"{download_owner}.localAudioPath",
                label=label,
            )
            subtitle_ref = download_obj.get("subtitleAssetRef")
            if subtitle_ref is not None:
                subtitle_ref = _require_ref(
                    subtitle_ref,
                    prefix="subtitles.",
                    refs=asset_refs,
                    owner=f"{download_owner}.subtitleAssetRef",
                    label=label,
                )
                subtitle_asset = _require_mapping(
                    assets["subtitles"][subtitle_ref.removeprefix("subtitles.")],
                    field=subtitle_ref,
                    label=label,
                )
                expected_subtitle_path: str | None = _ensure_str(
                    subtitle_asset.get("installAs"),
                    field=f"{subtitle_ref}.installAs",
                    label=label,
                )
            else:
                expected_subtitle_path = None
            _validate_download_local_path(
                download_obj.get("localSubtitlePath"),
                expected_install_as=expected_subtitle_path,
                owner=f"{download_owner}.localSubtitlePath",
                label=label,
            )

    for fixture_id, seed in _require_mapping(data.get("reader"), field="reader", label=label).items():
        seed_obj = _require_mapping(seed, field=f"reader.{fixture_id}", label=label)
        _require_ref(
            seed_obj.get("textAssetRef"),
            prefix="text.",
            refs=asset_refs,
            owner=f"reader.{fixture_id}.textAssetRef",
            label=label,
        )
        ref = _require_ref(
            seed_obj.get("bookAssetRef"),
            prefix="books.",
            refs=asset_refs,
            owner=f"reader.{fixture_id}.bookAssetRef",
            label=label,
        )
        _validate_book_asset_alignment(
            ref=ref,
            asset=assets["books"][ref.removeprefix("books.")],
            file_name=seed_obj.get("bookFileName"),
            book_format="epub",
            owner=f"reader.{fixture_id}",
            label=label,
        )

    for fixture_id, seed in _require_mapping(
        data.get("bookshelf"),
        field="bookshelf",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"bookshelf.{fixture_id}", label=label)
        _validate_exact_keys(
            seed_obj,
            expected=BOOKSHELF_SEED_KEYS,
            owner=f"bookshelf.{fixture_id}",
            label=label,
        )
        _parse_iso8601(
            seed_obj.get("referenceDate"),
            owner=f"bookshelf.{fixture_id}.referenceDate",
            label=label,
        )
        for index, book in enumerate(
            _require_list(
                seed_obj.get("books"),
                field=f"bookshelf.{fixture_id}.books",
                label=label,
            )
        ):
            book_obj = _require_mapping(
                book,
                field=f"bookshelf.{fixture_id}.books[{index}]",
                label=label,
            )
            owner = f"bookshelf.{fixture_id}.books[{index}]"
            _validate_exact_keys(book_obj, expected=BOOKSHELF_BOOK_KEYS, owner=owner, label=label)
            _ensure_str(book_obj.get("title"), field=f"{owner}.title", label=label)
            if not isinstance(book_obj.get("author"), str):
                raise UIWorldManifestError(f"{label} {owner}.author 必須是 string")
            _validate_optional_progression(book_obj.get("progression"), owner=f"{owner}.progression", label=label)
            date_added = _parse_iso8601(book_obj.get("dateAdded"), owner=f"{owner}.dateAdded", label=label)
            date_last_read = _validate_optional_iso8601(
                book_obj.get("dateLastRead"),
                owner=f"{owner}.dateLastRead",
                label=label,
            )
            if date_last_read is not None and date_last_read < date_added:
                raise UIWorldManifestError(f"{label} {owner}.dateLastRead must not be earlier than dateAdded")
            ref = _require_ref(
                book_obj.get("bookAssetRef"),
                prefix="books.",
                refs=asset_refs,
                owner=f"{owner}.bookAssetRef",
                label=label,
            )
            _validate_book_asset_alignment(
                ref=ref,
                asset=assets["books"][ref.removeprefix("books.")],
                file_name=book_obj.get("fileName"),
                book_format=book_obj.get("format"),
                owner=owner,
                label=label,
            )
            preferred_notebook = book_obj.get("preferredNotebookId")
            if preferred_notebook is not None and str(preferred_notebook).strip():
                _require_notebook_ref(
                    preferred_notebook,
                    notebook_ids=notebook_ids,
                    owner=f"{owner}.preferredNotebookId",
                    label=label,
                )

    for fixture_id, seed in _require_mapping(
        data.get("notebook"),
        field="notebook",
        label=label,
    ).items():
        seed_obj = _require_mapping(seed, field=f"notebook.{fixture_id}", label=label)
        for collection in ("notebooks", "editStates"):
            for index, item in enumerate(
                _require_list(
                    seed_obj.get(collection),
                    field=f"notebook.{fixture_id}.{collection}",
                    label=label,
                )
            ):
                item_obj = _require_mapping(
                    item,
                    field=f"notebook.{fixture_id}.{collection}[{index}]",
                    label=label,
                )
                if item_obj.get("coverImageAssetRef") is not None:
                    _require_ref(
                        item_obj.get("coverImageAssetRef"),
                        prefix="images.",
                        refs=asset_refs,
                        owner=f"notebook.{fixture_id}.{collection}[{index}].coverImageAssetRef",
                        label=label,
                    )


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
    _validate_preferences(data, label=label)
    _validate_auth_state(data, label=label)
    _validate_cross_references(data, label=label)
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
