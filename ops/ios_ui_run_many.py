#!/usr/bin/env -S uv run --python 3.13 python
"""Build once, run many exact iOS UI selectors, and emit durable evidence metadata.

This is deliberately a thin orchestration layer over the fail-closed single-run
evidence helper. It never invents a visual pass: contract validation happens in
the helper, while visual attestation remains an explicit later step.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable
import uuid


SCHEMA = "kg.ios.ui-run-many.v1"
CLEANUP_SCHEMA = "kg.ios.ui-run-cleanup.v1"
SELECTOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\/test[A-Za-z0-9_]+$")
DATASET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
REQUIREMENT_RE = re.compile(r"^P(?:[1-9]|1[0-5])$")
FAILURE_TTL_SECONDS = 24 * 60 * 60


class RunManyError(ValueError):
    pass


def _object(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunManyError(f"{owner} must be an object")
    return value


def load_methods(path: Path) -> list[dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunManyError(f"cannot read methods file {path}: {error}") from error
    if isinstance(raw, dict):
        raw = raw.get("runs")
    if not isinstance(raw, list) or not raw:
        raise RunManyError("methods file must contain a non-empty list or {runs: [...]}")
    result: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        item = _object(item, f"runs[{index}]")
        selector = item.get("selector")
        dataset_id = item.get("datasetID")
        requirement_id = item.get("requirementID")
        cluster_id = item.get("clusterID")
        if not isinstance(selector, str) or not SELECTOR_RE.fullmatch(selector):
            raise RunManyError(f"runs[{index}].selector must be an exact XCTest selector")
        if not isinstance(dataset_id, str) or not DATASET_RE.fullmatch(dataset_id):
            raise RunManyError(f"runs[{index}].datasetID is unsafe")
        if not isinstance(requirement_id, str) or not REQUIREMENT_RE.fullmatch(requirement_id):
            raise RunManyError(f"runs[{index}].requirementID must be P1-P15")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            raise RunManyError(f"runs[{index}].clusterID must be non-empty")
        result.append(
            {
                "selector": selector,
                "datasetID": dataset_id,
                "requirementID": requirement_id,
                "clusterID": cluster_id,
            }
        )
    return result


def deduplicate_methods(methods: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Collapse shared selectors while retaining every requirement mapping."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in methods:
        key = (item["selector"], item["datasetID"])
        current = grouped.setdefault(
            key,
            {
                "selector": item["selector"],
                "datasetID": item["datasetID"],
                "requirementIDs": [],
                "clusterIDs": [],
            },
        )
        if item["requirementID"] not in current["requirementIDs"]:
            current["requirementIDs"].append(item["requirementID"])
        if item["clusterID"] not in current["clusterIDs"]:
            current["clusterIDs"].append(item["clusterID"])
    return list(grouped.values())


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _pid_alive(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _global_ios_consumers(*, exclude_pid: int | None = None) -> list[str]:
    """Return active runner/build consumers; cleanup must fail closed on any."""
    try:
        result = subprocess.run(
            ["pgrep", "-af", "xcodebuild|ios_test\\.sh|run_ui_evidence\\.sh|ios_ui_run_many\\.py"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return ["process inspection unavailable"]
    consumers: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=1)
        try:
            pid = int(fields[0])
        except (IndexError, ValueError):
            pid = None
        if exclude_pid is not None and pid == exclude_pid:
            continue
        if line.strip():
            consumers.append(line)
    return consumers


def _active_lock_holders() -> list[dict[str, Any]]:
    """Inspect only the known iOS locks; never remove them during cleanup."""
    lock_paths = [Path("/tmp/kg-ios-build.lock"), Path("/tmp/kg-ios-ui-video.lock")]
    lock_paths.extend(sorted(Path("/tmp").glob("kg-ios-test-device-*.lock")))
    holders: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in lock_paths:
        path = path.resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            holders.append({"path": str(path), "status": "unreadable", "error": str(error)})
            continue
        try:
            pid = int(raw)
        except ValueError:
            holders.append({"path": str(path), "status": "invalid", "value": raw})
            continue
        holders.append(
            {
                "path": str(path),
                "pid": pid,
                "alive": _pid_alive(pid),
                "status": "active" if _pid_alive(pid) else "orphaned",
            }
        )
    return [item for item in holders if item.get("status") in {"active", "invalid", "unreadable"}]


def _allocated_bytes(path: Path) -> int | None:
    """Return allocated bytes for one explicit path, using bounded `du -sk`."""
    try:
        result = subprocess.run(
            ["du", "-sk", str(path)],
            text=True,
            capture_output=True,
            check=True,
        )
        return int(result.stdout.split()[0]) * 1024
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def _free_bytes() -> int | None:
    """Read free bytes for `/` without recursively scanning the filesystem."""
    try:
        result = subprocess.run(["df", "-k", "/"], text=True, capture_output=True, check=True)
        fields = result.stdout.splitlines()[-1].split()
        return int(fields[3]) * 1024
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def classify_bundle(bundle: Path, upstream_returncode: int) -> str:
    if upstream_returncode != 0:
        return "failed"
    verdict = _read_json(bundle / "verdict.json")
    contract = _read_json(bundle / "artifacts" / "ui-evidence-contract.json")
    if not verdict or verdict.get("status") != "ok" or str(verdict.get("exit")) != "0":
        return "failed_contract"
    if not contract or contract.get("valid") is not True:
        return "failed_contract"
    return "passed_unattested"


def _run_streaming(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    phase: str,
    log_path: Path | None = None,
    manifest_path: Path | None = None,
) -> int:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
    )
    assert process.stdout is not None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("wb")
    else:
        log_handle = None
    poller = selectors.DefaultSelector()
    poller.register(process.stdout, selectors.EVENT_READ)
    pending = b""
    last_heartbeat = started
    last_line = ""
    if manifest_path is not None:
        manifest = _read_json(manifest_path) or {}
        manifest["activePID"] = process.pid
        manifest["activePhase"] = phase
        _write_json_atomic(manifest_path, manifest)
    print(f"[run-many] phase={phase} pid={process.pid} alive=true elapsed=0s", flush=True)
    try:
        while True:
            events = poller.select(timeout=1.0)
            for key, _ in events:
                chunk = key.fileobj.read1(8192) if hasattr(key.fileobj, "read1") else key.fileobj.read(8192)
                if not chunk:
                    poller.unregister(key.fileobj)
                    continue
                if log_handle is not None:
                    log_handle.write(chunk)
                    log_handle.flush()
                pending += chunk
                while b"\n" in pending:
                    raw, pending = pending.split(b"\n", 1)
                    last_line = raw.decode("utf-8", errors="replace").strip()
                    if last_line:
                        print(last_line, flush=True)
            returncode = process.poll()
            now = time.monotonic()
            if now - last_heartbeat >= 20:
                print(
                    f"[run-many] phase={phase} pid={process.pid} alive={returncode is None} "
                    f"elapsed={int(now - started)}s last={last_line[-180:]}",
                    flush=True,
                )
                last_heartbeat = now
            if returncode is not None:
                if pending.strip():
                    tail = pending.decode("utf-8", errors="replace").strip()
                    if log_handle is not None:
                        log_handle.write(pending)
                        log_handle.flush()
                    print(tail, flush=True)
                print(
                    f"[run-many] phase={phase} pid={process.pid} alive=false "
                    f"elapsed={int(now - started)}s exit={returncode}",
                    flush=True,
                )
                return returncode
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        if log_handle is not None:
            log_handle.close()
        if manifest_path is not None:
            manifest = _read_json(manifest_path) or {}
            manifest["activePID"] = None
            manifest["activePhase"] = None
            _write_json_atomic(manifest_path, manifest)


def _canonical_device(value: str) -> str:
    if not re.fullmatch(r"[0-9A-Fa-f-]{36}", value):
        raise RunManyError(f"device must be a canonical UUID: {value!r}")
    return value.upper()


def _publish_bundle(bundle: Path, publish_root: Path, selector: str) -> Path:
    publish_root.mkdir(parents=True, exist_ok=True)
    # Preserve the helper run ID as the directory basename: matrix provenance
    # intentionally binds evidenceRoot.name to verdict.runId.
    destination = publish_root / bundle.name
    if destination.exists():
        raise RunManyError(f"refusing to overwrite existing evidence bundle: {destination}")
    shutil.copytree(bundle, destination)
    source_prefix = str(bundle.resolve())
    destination_prefix = str(destination.resolve())
    # Stable bundles are portable report artifacts. Rewrite only textual
    # metadata; binaries remain byte-for-byte copies. This keeps the helper's
    # absolute provenance internally consistent after publication.
    for path in destination.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".txt", ".html"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if source_prefix in text:
            path.write_text(text.replace(source_prefix, destination_prefix), encoding="utf-8")
    return destination


def cleanup_runs(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Preview or reclaim only expired failed/abandoned run staging content."""
    staging_root = args.staging_root.resolve()
    if not staging_root.is_dir():
        raise RunManyError(f"--staging-root must be an existing directory: {staging_root}")
    manifest_paths = sorted(staging_root.glob("*/run-manifest.json"))
    if len(manifest_paths) > args.max_runs:
        raise RunManyError(
            f"refusing to inspect more than {args.max_runs} direct run manifests; "
            "bound the cleanup root or raise --max-runs explicitly"
        )
    now = _now()
    global_consumers = _global_ios_consumers(exclude_pid=os.getpid())
    lock_holders = _active_lock_holders()
    disk_before = _free_bytes()
    candidates: list[dict[str, Any]] = []
    for manifest_path in manifest_paths:
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        status = manifest.get("status")
        if status not in {"failure", "abandoned"}:
            continue
        expires_at = _parse_time(manifest.get("expiresAt"))
        if expires_at is None or expires_at > now:
            continue
        run_root = manifest_path.parent.resolve()
        if not _inside(run_root, staging_root):
            raise RunManyError(f"manifest escaped staging root: {manifest_path}")
        recorded_pids: list[int] = []
        for key in ("pid", "activePID"):
            value = manifest.get(key)
            if isinstance(value, int) and value > 0 and value not in recorded_pids:
                recorded_pids.append(value)
        live_pids = [pid for pid in recorded_pids if _pid_alive(pid)]
        publish_root_value = manifest.get("publishRoot")
        publish_root: Path | None = None
        if isinstance(publish_root_value, str) and publish_root_value:
            publish_root = Path(publish_root_value).resolve()
            if not _inside(publish_root, run_root) or publish_root == run_root:
                raise RunManyError(f"manifest publishRoot escaped run staging root: {manifest_path}")
        removable: list[Path] = []
        for target in (run_root / "prepare", run_root / "raw", run_root / "logs", publish_root):
            if target is not None and target.exists() and target not in removable:
                if not _inside(target, run_root) or target == run_root:
                    raise RunManyError(f"unsafe cleanup target: {target}")
                removable.append(target)
        allocated_before = _allocated_bytes(run_root)
        blockers: list[str] = []
        if live_pids:
            blockers.append(f"recorded-live-pids:{','.join(map(str, live_pids))}")
        if global_consumers:
            blockers.append("global-ios-consumer-active")
        if lock_holders:
            blockers.append("known-lock-active-or-unreadable")
        candidates.append(
            {
                "manifest": str(manifest_path),
                "runID": manifest.get("runID"),
                "status": status,
                "expiresAt": manifest.get("expiresAt"),
                "stagingRoot": str(run_root),
                "recordedPIDs": recorded_pids,
                "livePIDs": live_pids,
                "removable": [str(path) for path in removable],
                "allocatedBytesBefore": allocated_before,
                "blockers": blockers,
                "action": "blocked" if blockers else ("delete" if args.commit else "preview-delete"),
            }
        )

    deleted: list[dict[str, Any]] = []
    if args.commit:
        for candidate in candidates:
            if candidate["blockers"]:
                continue
            run_root = Path(candidate["stagingRoot"])
            for target_text in candidate["removable"]:
                target = Path(target_text).resolve()
                if not _inside(target, run_root) or target == run_root:
                    raise RunManyError(f"cleanup target changed or escaped run root: {target}")
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    raise RunManyError(f"refusing to remove non-directory cleanup target: {target}")
            receipt = {
                "schema": CLEANUP_SCHEMA,
                "runID": candidate["runID"],
                "status": "reclaimed",
                "reclaimedAt": _iso(_now()),
                "manifest": candidate["manifest"],
                "preserved": [
                    str(run_root / "run-manifest.json"),
                    str(run_root / "methods.json"),
                    str(run_root / "summary.json"),
                ],
                "removed": candidate["removable"],
                "diskFreeBytesBefore": disk_before,
                "diskFreeBytesAfter": _free_bytes(),
            }
            _write_json_atomic(run_root / "cleanup-receipt.json", receipt)
            manifest = _read_json(run_root / "run-manifest.json") or {}
            manifest["cleanup"] = {
                "status": "reclaimed",
                "at": receipt["reclaimedAt"],
                "receipt": str(run_root / "cleanup-receipt.json"),
                "removed": candidate["removable"],
            }
            _write_json_atomic(run_root / "run-manifest.json", manifest)
            candidate["action"] = "reclaimed"
            candidate["allocatedBytesAfter"] = _allocated_bytes(run_root)
            candidate["reclaimedBytes"] = (
                max(0, (candidate["allocatedBytesBefore"] or 0) - (candidate["allocatedBytesAfter"] or 0))
                if candidate["allocatedBytesBefore"] is not None
                else None
            )
            deleted.append(candidate)

    payload = {
        "schema": CLEANUP_SCHEMA,
        "status": "committed" if args.commit else "preview",
        "stagingRoot": str(staging_root),
        "observedAt": _iso(now),
        "manifestCount": len(manifest_paths),
        "candidateCount": len(candidates),
        "commit": bool(args.commit),
        "diskFreeBytesBefore": disk_before,
        "diskFreeBytesAfter": _free_bytes() if args.commit else disk_before,
        "globalConsumers": global_consumers,
        "lockHolders": lock_holders,
        "candidates": candidates,
        "reclaimed": deleted,
    }
    blocked = any(candidate["blockers"] for candidate in candidates)
    return payload, 75 if args.commit and blocked else 0


def run_batch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = args.root.resolve()
    helper = args.helper.resolve()
    methods_path = args.methods_file.resolve()
    methods = deduplicate_methods(load_methods(methods_path))
    if not root.is_dir() or not helper.is_file():
        raise RunManyError("root and helper must exist")
    if args.device:
        device = _canonical_device(args.device)
    else:
        raise RunManyError("an explicit canonical --device is required; lease is not implicit")
    try:
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunManyError(f"cannot establish source provenance: {error}") from error
    if dirty:
        raise RunManyError("run-many requires a clean source tree")
    staging_root = args.output_dir.resolve()
    if staging_root.exists() and any(staging_root.iterdir()):
        raise RunManyError(f"refusing to reuse non-empty run staging directory: {staging_root}")
    staging_root.mkdir(parents=True, exist_ok=True)
    publish_root = (args.publish_root.resolve() if args.publish_root else staging_root / "bundles")
    if not _inside(publish_root, staging_root):
        raise RunManyError("--publish-root must be inside --output-dir so one run owns all artifacts")
    publish_root.mkdir(parents=True, exist_ok=True)
    raw_root = staging_root / "raw"
    log_root = staging_root / "logs"
    raw_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    summary_path = args.summary_out.resolve()
    if not _inside(summary_path, staging_root):
        raise RunManyError("--summary-out must be inside --output-dir so one run owns all artifacts")
    methods_snapshot = staging_root / "methods.json"
    shutil.copy2(methods_path, methods_snapshot)
    started_at = _now()
    run_id = f"ui-batch-{started_at.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    manifest_path = staging_root / "run-manifest.json"
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    manifest: dict[str, Any] = {
        "schema": "kg.ios.ui-run-manifest.v1",
        "runID": run_id,
        "status": "running",
        "verdict": "running",
        "owner": os.environ.get("USER", "unknown"),
        "pid": os.getpid(),
        "activePID": None,
        "activePhase": None,
        "worktree": str(root),
        "branch": branch,
        "sourceCommit": source_commit,
        "sourceTreeDirty": dirty,
        "device": device,
        "startedAt": _iso(started_at),
        "stagingRoot": str(staging_root),
        "publishRoot": str(publish_root),
        "methodsFile": str(methods_snapshot),
        "methodsSHA256": _sha256(methods_snapshot),
        "failureTTLSeconds": FAILURE_TTL_SECONDS,
        "expiresAt": _iso(started_at + timedelta(seconds=FAILURE_TTL_SECONDS)),
        "executions": [],
    }
    _write_json_atomic(manifest_path, manifest)

    env = os.environ.copy()
    env.setdefault("KG_IOS_TEST_MAX_EXECUTION_TIME_ALLOWANCE", "420")
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "runID": run_id,
        "createdAt": _iso(started_at),
        "owner": manifest["owner"],
        "pid": os.getpid(),
        "worktree": str(root),
        "branch": branch,
        "sourceCommit": source_commit,
        "sourceTreeDirty": dirty,
        "device": device,
        "datasetIDs": sorted({item["datasetID"] for item in methods}),
        "buildOnce": True,
        "runMany": True,
        "stagingRoot": str(staging_root),
        "publishRoot": str(publish_root),
        "runManifest": str(manifest_path),
        "methodsFile": str(methods_snapshot),
        "methodsSHA256": manifest["methodsSHA256"],
        "prepareCache": {"status": "running"},
        "executions": [],
    }
    env["KG_IOS_BATCH_RUN_ID"] = run_id
    env["KG_IOS_ARTIFACT_ROOT"] = str(staging_root / "prepare")
    env["KG_IOS_TEST_RUN_ID"] = f"{run_id}-prepare"

    def persist_summary() -> None:
        _write_json_atomic(summary_path, summary)

    persist_summary()
    prepare = [
        str(root / "ops" / "ios_ops.sh"),
        "test", "--ui", "--prepare-cache", "--ui-launch-profile", "ui-smoke",
        "--configuration", args.configuration, "--device", device, "--json",
    ]
    try:
        prepare_rc = _run_streaming(
            prepare,
            cwd=root,
            env=env,
            phase="prepare-cache",
            log_path=log_root / "prepare.log",
            manifest_path=manifest_path,
        )
        summary["prepareCache"] = {"status": "passed" if prepare_rc == 0 else "failed", "exit": prepare_rc}
        persist_summary()
        if prepare_rc != 0:
            summary["status"] = "failed"
            summary["finishedAt"] = _iso(_now())
            persist_summary()
            manifest["status"] = "failure"
            manifest["verdict"] = "failed"
            manifest["finishedAt"] = summary["finishedAt"]
            manifest["reason"] = "prepare-cache-failed"
            _write_json_atomic(manifest_path, manifest)
            return summary, 65

        overall = 0
        for index, item in enumerate(methods, start=1):
            slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", item["selector"])
            output_path = raw_root / f"{index:02d}-{slug}.json"
            command = [
                str(helper), "--dataset", item["datasetID"], "--method", item["selector"],
                "--device", device, "--configuration", args.configuration,
                "--ui-launch-profile", "ui-smoke", "--evidence-root", str(publish_root),
                "--json-out", str(output_path),
            ]
            started = time.monotonic()
            execution_env = env.copy()
            execution_env["KG_IOS_EXECUTION_ID"] = f"{run_id}-{index:02d}"
            execution_env["KG_IOS_TEST_RUN_ID"] = execution_env["KG_IOS_EXECUTION_ID"]
            rc = _run_streaming(
                command,
                cwd=root,
                env=execution_env,
                phase=f"run-{index}/{len(methods)}:{item['selector']}",
                log_path=log_root / f"{index:02d}-{slug}.log",
                manifest_path=manifest_path,
            )
            metadata = _read_json(output_path) or {}
            helper_metadata = metadata.get("helper") if isinstance(metadata.get("helper"), dict) else {}
            bundle_text = (
                metadata.get("bundle")
                or metadata.get("bundleRoot")
                or helper_metadata.get("bundleRoot")
            )
            bundle = Path(bundle_text).resolve() if isinstance(bundle_text, str) else None
            status = classify_bundle(bundle, rc) if bundle else "failed"
            if status != "passed_unattested":
                overall = max(overall, 1 if rc != 0 else 70)
            execution = {
                **item,
                "exit": rc,
                "status": status,
                "durationSeconds": round(time.monotonic() - started, 1),
                "jsonOut": str(output_path),
                "log": str(log_root / f"{index:02d}-{slug}.log"),
                "bundleRoot": str(bundle) if bundle else None,
                "sourceCommit": source_commit,
                "batchRunID": run_id,
                "executionID": execution_env["KG_IOS_EXECUTION_ID"],
            }
            summary["executions"].append(execution)
            manifest["executions"] = summary["executions"]
            _write_json_atomic(manifest_path, manifest)
            persist_summary()
        summary["status"] = "passed_unattested" if overall == 0 else "failed"
        summary["finishedAt"] = _iso(_now())
        persist_summary()
        manifest["status"] = "success" if overall == 0 else "failure"
        manifest["verdict"] = summary["status"]
        manifest["finishedAt"] = summary["finishedAt"]
        manifest["executions"] = summary["executions"]
        _write_json_atomic(manifest_path, manifest)
        return summary, overall
    except KeyboardInterrupt:
        summary["status"] = "abandoned"
        summary["reason"] = "interrupted"
        summary["finishedAt"] = _iso(_now())
        persist_summary()
        manifest["status"] = "abandoned"
        manifest["verdict"] = "abandoned"
        manifest["reason"] = "interrupted"
        manifest["finishedAt"] = summary["finishedAt"]
        _write_json_atomic(manifest_path, manifest)
        return summary, 130
    except BaseException as error:
        summary["status"] = "failed"
        summary["reason"] = f"runner-error:{type(error).__name__}"
        summary["finishedAt"] = _iso(_now())
        persist_summary()
        manifest["status"] = "failure"
        manifest["verdict"] = "failed"
        manifest["reason"] = summary["reason"]
        manifest["finishedAt"] = summary["finishedAt"]
        _write_json_atomic(manifest_path, manifest)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--root", type=Path, default=Path.cwd())
    run_parser.add_argument("--helper", type=Path, required=True)
    run_parser.add_argument("--methods-file", type=Path, required=True)
    run_parser.add_argument("--device", required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--publish-root", type=Path)
    run_parser.add_argument("--summary-out", type=Path, required=True)
    run_parser.add_argument("--configuration", default="Debug")
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--staging-root", type=Path, required=True)
    cleanup_parser.add_argument("--max-runs", type=int, default=200)
    cleanup_parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "run":
            summary, exit_code = run_batch(args)
            args.summary_out.parent.mkdir(parents=True, exist_ok=True)
            args.summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            summary, exit_code = cleanup_runs(args)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return exit_code
    except (OSError, RunManyError, subprocess.CalledProcessError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 65


if __name__ == "__main__":
    raise SystemExit(main())
