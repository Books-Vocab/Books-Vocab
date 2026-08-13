#!/usr/bin/env -S uv run --python 3.13 python
"""Build once, run many exact iOS UI selectors, and emit durable evidence metadata.

This is deliberately a thin orchestration layer over the fail-closed single-run
evidence helper. It never invents a visual pass: contract validation happens in
the helper, while visual attestation remains an explicit later step.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable


SCHEMA = "kg.ios.ui-run-many.v1"
SELECTOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\/test[A-Za-z0-9_]+$")
DATASET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
REQUIREMENT_RE = re.compile(r"^P(?:[1-9]|1[0-5])$")


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


def _run_streaming(command: list[str], *, cwd: Path, env: dict[str, str], phase: str) -> int:
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
    poller = selectors.DefaultSelector()
    poller.register(process.stdout, selectors.EVENT_READ)
    pending = b""
    last_heartbeat = started
    last_line = ""
    print(f"[run-many] phase={phase} pid={process.pid} alive=true elapsed=0s", flush=True)
    while True:
        events = poller.select(timeout=1.0)
        for key, _ in events:
            chunk = key.fileobj.read1(8192) if hasattr(key.fileobj, "read1") else key.fileobj.read(8192)
            if not chunk:
                poller.unregister(key.fileobj)
                continue
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
                print(pending.decode("utf-8", errors="replace").strip(), flush=True)
            print(
                f"[run-many] phase={phase} pid={process.pid} alive=false "
                f"elapsed={int(now - started)}s exit={returncode}",
                flush=True,
            )
            return returncode


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


def run_batch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = args.root.resolve()
    helper = args.helper.resolve()
    methods = deduplicate_methods(load_methods(args.methods_file.resolve()))
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
    env = os.environ.copy()
    env.setdefault("KG_IOS_TEST_MAX_EXECUTION_TIME_ALLOWANCE", "420")
    prepare = [
        str(root / "ops" / "ios_ops.sh"),
        "test", "--ui", "--prepare-cache", "--ui-launch-profile", "ui-smoke",
        "--configuration", args.configuration, "--device", device, "--json",
    ]
    prepare_rc = _run_streaming(prepare, cwd=root, env=env, phase="prepare-cache")
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceCommit": source_commit,
        "sourceTreeDirty": dirty,
        "device": device,
        "datasetIDs": sorted({item["datasetID"] for item in methods}),
        "buildOnce": True,
        "runMany": True,
        "prepareCache": {"status": "passed" if prepare_rc == 0 else "failed", "exit": prepare_rc},
        "executions": [],
    }
    if prepare_rc != 0:
        return summary, 65
    overall = 0
    for index, item in enumerate(methods, start=1):
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", item["selector"])
        output_path = args.output_dir.resolve() / f"{index:02d}-{slug}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(helper), "--dataset", item["datasetID"], "--method", item["selector"],
            "--device", device, "--json-out", str(output_path),
        ]
        started = time.monotonic()
        rc = _run_streaming(command, cwd=root, env=env, phase=f"run-{index}/{len(methods)}:{item['selector']}")
        metadata = _read_json(output_path) or {}
        helper_metadata = metadata.get("helper") if isinstance(metadata.get("helper"), dict) else {}
        bundle_text = (
            metadata.get("bundle")
            or metadata.get("bundleRoot")
            or helper_metadata.get("bundleRoot")
        )
        bundle = Path(bundle_text).resolve() if isinstance(bundle_text, str) else None
        published = None
        if bundle and bundle.is_dir() and args.publish_root:
            published = _publish_bundle(bundle, args.publish_root.resolve(), item["selector"])
        status = classify_bundle(bundle, rc) if bundle else "failed"
        if status != "passed_unattested":
            overall = max(overall, 1 if rc != 0 else 70)
        summary["executions"].append(
            {
                **item,
                "exit": rc,
                "status": status,
                "durationSeconds": round(time.monotonic() - started, 1),
                "jsonOut": str(output_path),
                "bundleRoot": str(published or bundle) if (published or bundle) else None,
                "sourceCommit": source_commit,
            }
        )
    summary["status"] = "passed_unattested" if overall == 0 else "failed"
    return summary, overall


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--methods-file", type=Path, required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--publish-root", type=Path)
    parser.add_argument("--summary-out", type=Path, required=True)
    parser.add_argument("--configuration", default="Debug")
    args = parser.parse_args()
    try:
        summary, exit_code = run_batch(args)
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return exit_code
    except (OSError, RunManyError, subprocess.CalledProcessError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 65


if __name__ == "__main__":
    raise SystemExit(main())
