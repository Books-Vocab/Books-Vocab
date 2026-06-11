from __future__ import annotations

import json
from pathlib import Path

from catalog_review_sync import (
    LEGACY_REVIEW_HTML_NAME,
    REVIEW_HTML_NAME,
    hydrate_manifest,
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_paths(root: Path) -> tuple[Path, Path]:
    manifest_path = root / "review_manifest.json"
    state_path = root / "review_state.json"
    return manifest_path, state_path


def review_html_path(root: Path) -> Path:
    # Roots generated before the 2026-06 rename only carry review.html; resolve
    # reads (permalinks / serve / mark rewrite) to the file that actually exists.
    preferred = root / REVIEW_HTML_NAME
    legacy = root / LEGACY_REVIEW_HTML_NAME
    if not preferred.exists() and legacy.exists():
        return legacy
    return preferred


def build_artifact_refs(root: Path) -> dict[str, str]:
    manifest_path, state_path = resolve_paths(root)
    html_path = review_html_path(root)
    return {
        "manifest": str(manifest_path),
        "state": str(state_path),
        "html": str(html_path),
    }


def build_permalink(root: Path, asset_id: str) -> str:
    return f"file://{review_html_path(root)}#asset-{asset_id}"


def load_review_context(root: Path) -> tuple[dict, dict]:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    return hydrate_manifest(manifest, state), state


def load_review_artifacts(root: Path, *, hydrate: bool, include_html: bool) -> dict:
    manifest_path, state_path = resolve_paths(root)
    payload = {
        "manifest_path": manifest_path,
        "state_path": state_path,
        "manifest": load_json(manifest_path),
        "state": load_json(state_path),
    }
    if hydrate:
        payload["manifest"] = hydrate_manifest(payload["manifest"], payload["state"])
    if include_html:
        html_path = review_html_path(root)
        payload["html_path"] = html_path
        payload["html_text"] = html_path.read_text(encoding="utf-8")
    return payload
