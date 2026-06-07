#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import argparse
import json
from pathlib import Path


VALID_STATUSES = {"shortlist", "review", "reject", ""}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_paths(root: Path) -> tuple[Path, Path]:
    manifest_path = root / "review_manifest.json"
    state_path = root / "review_state.json"
    return manifest_path, state_path


def cmd_summary(root: Path) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    payload = {
        "status": "ok",
        "manifest": str(manifest_path),
        "state": str(state_path),
        "totalImages": manifest["totalImages"],
        "stateEntries": len(state["entries"]),
        "promiseCounts": manifest["promiseCounts"],
        "stateCounts": manifest.get("stateCounts", {}),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_show(root: Path, asset_id: str) -> int:
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    item = next((entry for entry in manifest["items"] if entry["assetID"] == asset_id), None)
    if item is None:
        print(json.dumps({"status": "error", "error": "asset-not-found", "assetID": asset_id}, ensure_ascii=False))
        return 1
    payload = {
        "status": "ok",
        "asset": item,
        "state": state["entries"].get(asset_id, {}),
        "permalink": f"file://{root / 'review.html'}#asset-{asset_id}",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_mark(root: Path, asset_id: str, status: str, note: str | None) -> int:
    if status not in VALID_STATUSES:
        print(json.dumps({"status": "error", "error": "invalid-status", "allowed": sorted(VALID_STATUSES)}, ensure_ascii=False))
        return 2
    manifest_path, state_path = resolve_paths(root)
    manifest = load_json(manifest_path)
    state = load_json(state_path)
    item = next((entry for entry in manifest["items"] if entry["assetID"] == asset_id), None)
    if item is None:
        print(json.dumps({"status": "error", "error": "asset-not-found", "assetID": asset_id}, ensure_ascii=False))
        return 1
    entry = state["entries"].setdefault(asset_id, {})
    entry.update({
        "status": status,
        "note": note if note is not None else entry.get("note", ""),
        "promise": item["promise"],
        "category": item["category"],
        "title": item["title"],
        "device": item["device"],
        "appearance": item["appearance"],
        "relPath": item["relPath"],
    })
    write_json(state_path, state)
    print(json.dumps({"status": "ok", "assetID": asset_id, "reviewStatus": status, "note": entry["note"]}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and update catalog review state sidecars.")
    parser.add_argument("root", type=Path, help="Directory containing review_manifest.json and review_state.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary")

    show = subparsers.add_parser("show")
    show.add_argument("asset_id")

    mark = subparsers.add_parser("mark")
    mark.add_argument("asset_id")
    mark.add_argument("--status", default="review")
    mark.add_argument("--note", default=None)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "summary":
        return cmd_summary(root)
    if args.command == "show":
        return cmd_show(root, args.asset_id)
    if args.command == "mark":
        return cmd_mark(root, args.asset_id, args.status, args.note)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
