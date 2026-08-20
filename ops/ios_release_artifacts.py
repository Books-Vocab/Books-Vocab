#!/usr/bin/env -S uv run --python 3.13
"""Retain a bounded catalog of release-provenance iOS Simulator apps.

The App Store/TestFlight archive contains an iphoneos app, which cannot be
installed into an iOS Simulator.  This catalog therefore stores a Debug
iphonesimulator app built from the exact release commit.  It is a local,
rebuildable cache; the Git release tags remain the durable release record.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "kg.ios.release-artifacts.v1"
INSTALL_PROVENANCE_SCHEMA = "kg.ios.install-provenance.v1"
APP_NAME = "BooksAndVocab.app"
BUNDLE_ID = "com.Max0228.BooksBrowser"
DEFAULT_KEEP = 3
DEFAULT_CONFIGURATION = "Debug"
DEFAULT_PLATFORM = "iOS Simulator"
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ArtifactError(RuntimeError):
    """A release artifact contract cannot be satisfied."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    script_root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(script_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return script_root
    common_dir = Path(result.stdout.strip()).resolve()
    return common_dir.parent if common_dir.name == ".git" else script_root


def artifact_root(explicit: str | None = None) -> Path:
    configured = explicit or os.environ.get("KG_IOS_RELEASE_ARTIFACT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (_repo_root() / ".cache" / "ios-release-artifacts").resolve()


def _parse_keep(value: str | int | None) -> int:
    raw = os.environ.get("KG_IOS_RELEASE_ARTIFACT_KEEP", str(DEFAULT_KEEP)) if value is None else str(value)
    try:
        keep = int(raw)
    except ValueError as exc:
        raise ArtifactError(f"keep 必須是正整數：{raw}") from exc
    if keep <= 0:
        raise ArtifactError(f"keep 必須是正整數：{raw}")
    return keep


def _require_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ArtifactError(f"version 必須是 x.y.z：{version}")


def _require_build(build: str | int) -> str:
    text = str(build)
    if not text.isdigit():
        raise ArtifactError(f"build 必須是非負整數：{build}")
    return str(int(text))


def _require_commit(commit: str) -> str:
    normalized = commit.lower()
    if not COMMIT_RE.fullmatch(normalized):
        raise ArtifactError(f"commit 必須是 7–40 位小寫 hexadecimal SHA：{commit}")
    return normalized


def _catalog_path(root: Path) -> Path:
    return root / "catalog.json"


def _artifacts_root(root: Path) -> Path:
    return root / "artifacts"


def _empty_catalog(keep: int) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": 1,
        "keep": keep,
        "platform": DEFAULT_PLATFORM,
        "configuration": DEFAULT_CONFIGURATION,
        "records": [],
    }


def _load_catalog(root: Path, keep: int) -> dict[str, Any]:
    path = _catalog_path(root)
    if not path.exists():
        return _empty_catalog(keep)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"catalog 無法讀取：{path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ArtifactError(f"catalog schema 不相容：{path}")
    if not isinstance(payload.get("records"), list):
        raise ArtifactError(f"catalog.records 必須是 array：{path}")
    catalog_keep = payload.get("keep", keep)
    payload["keep"] = _parse_keep(catalog_keep)
    return payload


def _write_catalog(root: Path, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = _catalog_path(root)
    fd, temporary = tempfile.mkstemp(prefix=".catalog.", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@contextmanager
def _catalog_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_plist(app: Path) -> dict[str, Any]:
    path = app / "Info.plist"
    if not path.is_file():
        raise ArtifactError(f"缺少 app Info.plist：{path}")
    try:
        payload = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ArtifactError(f"Info.plist 無法解析：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactError(f"Info.plist 不是 dictionary：{path}")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"JSON 無法讀取：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactError(f"JSON 必須是 object：{path}")
    return payload


def _source_provenance_path(app: Path) -> Path:
    return Path(f"{app}.kg-provenance.json")


def _read_source_provenance(app: Path, commit: str) -> dict[str, Any]:
    sidecar = _source_provenance_path(app)
    if not sidecar.is_file():
        raise ArtifactError(f"缺少 iOS install provenance sidecar：{sidecar}")
    payload = _read_json(sidecar)
    if payload.get("schema") != INSTALL_PROVENANCE_SCHEMA:
        raise ArtifactError(f"provenance schema 不相容：{sidecar}")
    if payload.get("head") != commit:
        raise ArtifactError(
            f".app commit 不吻合：sidecar={payload.get('head', '<missing>')} expected={commit}"
        )
    destination = str(payload.get("destination", ""))
    if "platform=iOS Simulator" not in destination:
        raise ArtifactError(f"不是 Simulator .app：destination={destination or '<missing>'}")
    configuration = str(payload.get("configuration", ""))
    if configuration != DEFAULT_CONFIGURATION:
        raise ArtifactError(f"release screenshot .app 必須是 Debug：configuration={configuration}")
    return payload


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _app_digest(app: Path) -> str:
    digest = hashlib.sha256()
    entries = sorted(app.rglob("*"), key=lambda path: path.relative_to(app).as_posix())
    for path in entries:
        relative = path.relative_to(app).as_posix().encode("utf-8")
        if path.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(path).encode("utf-8") + b"\n")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\n")
        elif path.is_dir():
            digest.update(b"D\0" + relative + b"\n")
    return digest.hexdigest()


def _validate_app(app: Path, version: str, build: str, commit: str) -> tuple[dict[str, Any], str]:
    app = app.expanduser().resolve()
    if not app.is_dir() or app.name != APP_NAME:
        raise ArtifactError(f"找不到 BooksAndVocab.app：{app}")
    info = _read_plist(app)
    bundle_id = str(info.get("CFBundleIdentifier", ""))
    actual_version = str(info.get("CFBundleShortVersionString", ""))
    actual_build = str(info.get("CFBundleVersion", ""))
    if bundle_id != BUNDLE_ID:
        raise ArtifactError(f"bundle id 不吻合：{bundle_id or '<missing>'} != {BUNDLE_ID}")
    if actual_version != version:
        raise ArtifactError(f".app version 不吻合：{actual_version or '<missing>'} != {version}")
    if actual_build != build:
        raise ArtifactError(f".app build 不吻合：{actual_build or '<missing>'} != {build}")
    provenance = _read_source_provenance(app, commit)
    return provenance, _app_digest(app)


def _artifact_key(version: str, build: str, commit: str) -> str:
    return f"{version}+{build}-{commit}-simulator-debug"


def _artifact_paths(root: Path, key: str) -> tuple[Path, Path, str, str]:
    directory = _artifacts_root(root) / key
    return directory, directory / APP_NAME, directory / "provenance.json", f"artifacts/{key}/{APP_NAME}"


def _copy_artifact(
    root: Path,
    app: Path,
    version: str,
    build: str,
    commit: str,
    source_provenance: dict[str, Any],
    source_digest: str,
) -> tuple[str, str, dict[str, Any]]:
    key = _artifact_key(version, build, commit)
    directory, destination, metadata_path, relative_app = _artifact_paths(root, key)
    if directory.exists():
        if not destination.is_dir() or not metadata_path.is_file():
            raise ArtifactError(f"既有 artifact 不完整，拒絕覆寫：{directory}")
        metadata = _read_json(metadata_path)
        if metadata.get("commit") != commit or metadata.get("appDigest") != source_digest:
            raise ArtifactError(f"既有 artifact provenance 不吻合，拒絕覆寫：{directory}")
        return relative_app, metadata.get("provenancePath", f"artifacts/{key}/provenance.json"), metadata

    artifacts_root = _artifacts_root(root)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".capture-", dir=artifacts_root))
    try:
        temporary_app = temporary / APP_NAME
        shutil.copytree(app, temporary_app, symlinks=True)
        metadata = {
            "schema": SCHEMA,
            "artifactKey": key,
            "source": "simulator-build",
            "version": version,
            "build": build,
            "commit": commit,
            "platform": DEFAULT_PLATFORM,
            "configuration": DEFAULT_CONFIGURATION,
            "bundleId": BUNDLE_ID,
            "appDigest": source_digest,
            "sourceProvenance": source_provenance,
            "provenancePath": f"artifacts/{key}/provenance.json",
            "capturedAt": _utc_now(),
        }
        (temporary / "provenance.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.rename(temporary, directory)
        return relative_app, metadata["provenancePath"], metadata
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _record_id(source: str, version: str, build: str) -> str:
    return f"{source}:{version}+{build}"


def _find_artifact_record(records: list[dict[str, Any]], version: str, build: str, commit: str) -> dict[str, Any] | None:
    for record in records:
        if (
            record.get("version") == version
            and str(record.get("build")) == build
            and record.get("commit") == commit
            and record.get("artifactPath")
        ):
            return record
    return None


def _safe_artifact_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not _is_within(path, _artifacts_root(root)):
        raise ArtifactError(f"artifact path 跑出 artifacts root：{relative}")
    return path


def _prune_locked(root: Path, catalog: dict[str, Any], keep: int) -> list[dict[str, Any]]:
    records = list(catalog.get("records", []))
    kept = records[:keep]
    kept_paths = {record.get("artifactPath") for record in kept}
    removed = records[keep:]
    for record in removed:
        relative = record.get("artifactPath")
        if not relative or relative in kept_paths:
            continue
        artifact_path = _safe_artifact_path(root, relative)
        artifact_directory = artifact_path.parent
        if artifact_directory.exists():
            shutil.rmtree(artifact_directory)
    catalog["records"] = kept
    catalog["keep"] = keep
    return removed


def record_release(
    *,
    root: Path,
    source: str,
    version: str,
    build: str,
    commit: str,
    app: Path | None,
    source_ref: str,
    released_at: str | None,
    keep: int,
) -> dict[str, Any]:
    if source not in {"testflight", "appstore"}:
        raise ArtifactError(f"source 必須是 testflight 或 appstore：{source}")
    _require_version(version)
    build = _require_build(build)
    commit = _require_commit(commit)
    root = root.resolve()

    with _catalog_lock(root):
        catalog = _load_catalog(root, keep)
        existing_id = _record_id(source, version, build)
        existing = next((item for item in catalog["records"] if item.get("id") == existing_id), None)
        if existing is not None and existing.get("commit") != commit:
            raise ArtifactError(
                f"release identity 已存在但 commit 不同：{existing_id} -> {existing.get('commit')} != {commit}"
            )

        matching = _find_artifact_record(catalog["records"], version, build, commit)
        provenance: dict[str, Any] | None = None
        app_digest: str | None = None
        if matching is not None:
            artifact_path = str(matching["artifactPath"])
            artifact_provenance = str(matching.get("provenancePath", ""))
            if not _safe_artifact_path(root, artifact_path).is_dir():
                matching = None
        if matching is None:
            if app is None:
                raise ArtifactError(
                    f"找不到 {version}+{build} 的 simulator .app；先以 exact commit 建置後再 record --app <path>"
                )
            provenance, app_digest = _validate_app(app, version, build, commit)
            artifact_path, artifact_provenance, _metadata = _copy_artifact(
                root, app, version, build, commit, provenance, app_digest
            )
        else:
            artifact_path = str(matching["artifactPath"])
            artifact_provenance = str(matching.get("provenancePath", ""))
            metadata_path = _safe_artifact_path(root, artifact_provenance)
            if not metadata_path.is_file():
                raise ArtifactError(f"artifact provenance 不存在：{metadata_path}")
            metadata = _read_json(metadata_path)
            provenance = metadata.get("sourceProvenance") if isinstance(metadata.get("sourceProvenance"), dict) else None
            app_digest = metadata.get("appDigest")

        record = {
            "id": existing_id,
            "source": source,
            "version": version,
            "build": build,
            "commit": commit,
            "sourceRef": source_ref or (f"ios/{version}+{build}" if source == "testflight" else f"ios/{version}"),
            "releasedAt": released_at or _utc_now(),
            "recordedAt": _utc_now(),
            "platform": DEFAULT_PLATFORM,
            "configuration": DEFAULT_CONFIGURATION,
            "artifactPath": artifact_path,
            "provenancePath": artifact_provenance,
            "appDigest": app_digest,
        }
        catalog["records"] = [item for item in catalog["records"] if item.get("id") != existing_id]
        catalog["records"].insert(0, record)
        removed = _prune_locked(root, catalog, keep)
        _write_catalog(root, catalog)

    return {
        "schema": SCHEMA,
        "status": "ok",
        "action": "record",
        "root": str(root),
        "record": record,
        "kept": len(catalog["records"]),
        "removed": [item.get("id") for item in removed],
    }


def _decorate_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result["artifactAbsolutePath"] = str(_safe_artifact_path(root, str(record["artifactPath"])))
    result["provenanceAbsolutePath"] = str(_safe_artifact_path(root, str(record["provenancePath"])))
    result["artifactExists"] = Path(result["artifactAbsolutePath"]).is_dir()
    result["provenanceExists"] = Path(result["provenanceAbsolutePath"]).is_file()
    return result


def list_catalog(*, root: Path, keep: int) -> dict[str, Any]:
    with _catalog_lock(root):
        catalog = _load_catalog(root, keep)
        records = [_decorate_record(root, record) for record in catalog["records"]]
    return {
        "schema": SCHEMA,
        "status": "ok",
        "action": "list",
        "root": str(root.resolve()),
        "keep": catalog["keep"],
        "records": records,
    }


def resolve_artifact(
    *,
    root: Path,
    commit: str,
    source: str | None = None,
    version: str | None = None,
    build: str | None = None,
    keep: int,
) -> dict[str, Any]:
    commit = _require_commit(commit)
    if source is not None and source not in {"testflight", "appstore"}:
        raise ArtifactError(f"source 必須是 testflight 或 appstore：{source}")
    if version is not None:
        _require_version(version)
    if build is not None:
        build = _require_build(build)
    with _catalog_lock(root):
        catalog = _load_catalog(root, keep)
        candidates = [
            item
            for item in catalog["records"]
            if item.get("commit") == commit
            and (source is None or item.get("source") == source)
            and (version is None or item.get("version") == version)
            and (build is None or str(item.get("build")) == build)
        ]
        for item in candidates:
            artifact = _safe_artifact_path(root, str(item.get("artifactPath", "")))
            provenance = _safe_artifact_path(root, str(item.get("provenancePath", "")))
            if artifact.is_dir() and provenance.is_file():
                return {
                    "schema": SCHEMA,
                    "status": "hit",
                    "action": "resolve",
                    "root": str(root.resolve()),
                    "appPath": str(artifact),
                    "provenancePath": str(provenance),
                    "record": _decorate_record(root, item),
                }
    return {
        "schema": SCHEMA,
        "status": "miss",
        "action": "resolve",
        "root": str(root.resolve()),
        "commit": commit,
        "source": source,
        "version": version,
        "build": build,
    }


def validate_catalog(*, root: Path, keep: int, deep: bool) -> dict[str, Any]:
    with _catalog_lock(root):
        catalog = _load_catalog(root, keep)
        records = catalog["records"]
        if len(records) > catalog["keep"]:
            raise ArtifactError(f"catalog 保留數超過 keep：{len(records)} > {catalog['keep']}")
        ids: set[str] = set()
        checked: list[str] = []
        for record in records:
            record_id = str(record.get("id", ""))
            if not record_id or record_id in ids:
                raise ArtifactError(f"catalog 有重複或空 release id：{record_id or '<empty>'}")
            ids.add(record_id)
            artifact = _safe_artifact_path(root, str(record.get("artifactPath", "")))
            provenance = _safe_artifact_path(root, str(record.get("provenancePath", "")))
            if not artifact.is_dir() or not provenance.is_file():
                raise ArtifactError(f"artifact 缺失：{record_id}")
            metadata = _read_json(provenance)
            for key, expected in {
                "schema": SCHEMA,
                "version": record.get("version"),
                "build": str(record.get("build")),
                "commit": record.get("commit"),
                "platform": DEFAULT_PLATFORM,
                "configuration": DEFAULT_CONFIGURATION,
            }.items():
                if metadata.get(key) != expected:
                    raise ArtifactError(f"artifact provenance 不吻合：{record_id} field={key}")
            if deep:
                digest = _app_digest(artifact)
                if digest != metadata.get("appDigest") or digest != record.get("appDigest"):
                    raise ArtifactError(f"artifact digest 不吻合：{record_id}")
            checked.append(record_id)
    return {
        "schema": SCHEMA,
        "status": "ok",
        "action": "validate",
        "root": str(root.resolve()),
        "keep": catalog["keep"],
        "checked": checked,
        "deep": deep,
    }


def prune_catalog(*, root: Path, keep: int, apply: bool) -> dict[str, Any]:
    with _catalog_lock(root):
        catalog = _load_catalog(root, keep)
        before = [item.get("id") for item in catalog["records"]]
        if not apply:
            after = before[:keep]
            return {
                "schema": SCHEMA,
                "status": "dry-run",
                "action": "prune",
                "root": str(root.resolve()),
                "keep": keep,
                "kept": after,
                "wouldRemove": before[keep:],
            }
        removed = _prune_locked(root, catalog, keep)
        _write_catalog(root, catalog)
    return {
        "schema": SCHEMA,
        "status": "ok",
        "action": "prune",
        "root": str(root.resolve()),
        "keep": keep,
        "kept": [item.get("id") for item in catalog["records"]],
        "removed": [item.get("id") for item in removed],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keep latest TestFlight/App Store simulator .app release artifacts")
    parser.add_argument("--root", help="artifact root; default KG_IOS_RELEASE_ARTIFACT_ROOT or repo .cache")
    parser.add_argument("--keep", type=int, help=f"number of release records to retain (default {DEFAULT_KEEP})")
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    sub = parser.add_subparsers(dest="action", required=True)

    record = sub.add_parser("record", help="copy and retain one release record")
    record.add_argument("--source", required=True, choices=("testflight", "appstore"))
    record.add_argument("--version", required=True)
    record.add_argument("--build", required=True)
    record.add_argument("--commit", required=True)
    record.add_argument("--app", type=Path, help="exact Debug iphonesimulator BooksAndVocab.app")
    record.add_argument("--source-ref", default="")
    record.add_argument("--released-at", default="")

    resolve = sub.add_parser("resolve", help="resolve a retained .app by exact commit")
    resolve.add_argument("--commit", required=True)
    resolve.add_argument("--source", choices=("testflight", "appstore"))
    resolve.add_argument("--version")
    resolve.add_argument("--build")

    sub.add_parser("list", help="list retained records")
    validate = sub.add_parser("validate", help="validate catalog and artifact provenance")
    validate.add_argument("--deep", action="store_true", help="rehash every .app file")
    prune = sub.add_parser("prune", help="preview or apply retention cleanup")
    prune.add_argument("--apply", action="store_true", help="delete unreferenced old artifact directories")
    return parser


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    action = payload.get("action", "")
    status = payload.get("status", "")
    print(f"[ios][release-artifacts] status={status} action={action} root={payload.get('root', '')}")
    if action == "record":
        record = payload.get("record", {})
        print(
            f"[ios][release-artifacts] {record.get('source')} "
            f"{record.get('version')}+{record.get('build')} commit={record.get('commit')}"
        )
        print(f"[ios][release-artifacts] app={record.get('artifactPath')}")
        if payload.get("removed"):
            print(f"[ios][release-artifacts] removed={','.join(payload['removed'])}")
    elif action in {"list", "validate", "prune"}:
        for item in payload.get("records", payload.get("kept", [])):
            if isinstance(item, dict):
                print(f"[ios][release-artifacts] {item.get('id')} app={item.get('artifactAbsolutePath', item.get('artifactPath'))}")
            else:
                print(f"[ios][release-artifacts] {item}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        root = artifact_root(args.root)
        keep = _parse_keep(args.keep)
        if args.action == "record":
            payload = record_release(
                root=root,
                source=args.source,
                version=args.version,
                build=args.build,
                commit=args.commit,
                app=args.app,
                source_ref=args.source_ref,
                released_at=args.released_at or None,
                keep=keep,
            )
        elif args.action == "resolve":
            payload = resolve_artifact(
                root=root,
                commit=args.commit,
                source=args.source,
                version=args.version,
                build=args.build,
                keep=keep,
            )
        elif args.action == "list":
            payload = list_catalog(root=root, keep=keep)
        elif args.action == "validate":
            payload = validate_catalog(root=root, keep=keep, deep=args.deep)
        elif args.action == "prune":
            payload = prune_catalog(root=root, keep=keep, apply=args.apply)
        else:  # pragma: no cover - argparse enforces the choices.
            raise ArtifactError(f"unknown action: {args.action}")
        _emit(payload, args.json)
        return 0
    except ArtifactError as exc:
        if args.json:
            print(json.dumps({"schema": SCHEMA, "status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"✗ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
