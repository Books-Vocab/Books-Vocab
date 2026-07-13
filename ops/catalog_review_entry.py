#!/usr/bin/env -S uv run --python 3.13 python
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import shlex
import shutil
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))
from catalog_appearance_proof import load_and_validate_appearance_proof


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = ROOT / "build" / "snapshots"
RUN_RECEIPT_KEYS = {
    "schema",
    "status",
    "sourceCommit",
    "datasetID",
    "datasetSHA256",
    "fixedClock",
    "testExit",
    "copyExit",
    "validationStatus",
    "reviewStatus",
    "appearanceStatus",
}


def resolve_review_html(root: Path) -> Path:
    # Filename SoT lives in catalog_review_sync.REVIEW_HTML_NAME; this script
    # stays import-free by design (standalone uv entrypoint), so it mirrors the
    # same resolution: prefer UIreview.html, fall back to the pre-rename
    # review.html that older blessed roots still carry.
    preferred = root / "UIreview.html"
    legacy = root / "review.html"
    if not preferred.exists() and legacy.exists():
        return legacy
    return preferred


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run_receipt(path: Path, *, appearance: dict | None) -> dict:
    if not path.is_file():
        return {"status": "block", "issues": ["run-receipt-missing"]}
    try:
        receipt = load_manifest(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "block", "issues": ["run-receipt-invalid"]}
    issues: list[str] = []
    if not isinstance(receipt, dict) or set(receipt) != RUN_RECEIPT_KEYS:
        issues.append("run-receipt-shape")
    if receipt.get("schema") != "kg.ios.catalog.run_receipt.v1":
        issues.append("run-receipt-schema")
    if (
        receipt.get("status") != "pass"
        or receipt.get("testExit") != 0
        or receipt.get("copyExit") != 0
        or receipt.get("validationStatus") not in {"ok", "warn"}
        or receipt.get("reviewStatus") != "ok"
        or receipt.get("appearanceStatus") != "pass"
    ):
        issues.append("run-receipt-verdict")
    if not isinstance(appearance, dict):
        issues.append("run-receipt-appearance-missing")
    else:
        for key in ("sourceCommit", "datasetID", "datasetSHA256", "fixedClock"):
            if receipt.get(key) != appearance.get(key):
                issues.append(f"run-receipt-{key}")
    return {"status": "pass" if not issues else "block", "issues": issues}


def collect_review_artifacts(snapshot_root: Path = SNAPSHOT_ROOT) -> list[dict]:
    # build/snapshots also hosts bypass artifacts (gallery-admin-preview carries
    # a usable manifest, catalog-converged-final exists too). Only
    # catalog-full-<UTC> roots are review artifacts; the prefix also makes
    # lexicographic order == chronological order for choose_blessed_artifact.
    artifacts: list[dict] = []
    for manifest_path in sorted(snapshot_root.glob("catalog-full-*/review_manifest.json")):
        manifest = load_manifest(manifest_path)
        total_images = manifest.get("totalImages", 0)
        appearance_path = manifest_path.parent / "catalog_appearance.json"
        appearance_proof = load_and_validate_appearance_proof(appearance_path)
        try:
            appearance_document = load_manifest(appearance_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            appearance_document = None
        run_receipt = validate_run_receipt(
            manifest_path.parent / "catalog_run_receipt.json",
            appearance=appearance_document,
        )
        artifacts.append({
            "name": manifest_path.parent.name,
            "root": manifest_path.parent,
            "manifest": manifest,
            "totalImages": total_images,
            "promiseCounts": manifest.get("promiseCounts", {}),
            "stateCounts": manifest.get("stateCounts", {}),
            "categories": len({item["category"] for item in manifest.get("items", [])}),
            "clusters": len({item["clusterID"] for item in manifest.get("items", [])}),
            "heroCandidates": sum(1 for item in manifest.get("items", []) if item.get("heroCandidate")),
            "newSincePr878": sum(1 for item in manifest.get("items", []) if item.get("newSincePr878")),
            "appearanceProof": appearance_proof,
            "runReceipt": run_receipt,
            "isUsable": (
                total_images > 0
                and appearance_proof["status"] == "pass"
                and run_receipt["status"] == "pass"
            ),
        })
    return artifacts


def choose_blessed_artifact(artifacts: list[dict]) -> dict:
    if not artifacts:
        raise SystemExit("No review artifacts found under build/snapshots")
    candidates = [item for item in artifacts if item["isUsable"]]
    if not candidates:
        raise SystemExit("No usable review artifacts found under build/snapshots")
    return max(
        candidates,
        key=lambda item: (
            item["name"],
        ),
    )


def prune_stale_artifacts(snapshot_root: Path = SNAPSHOT_ROOT, *, dry_run: bool) -> list[dict]:
    artifacts = collect_review_artifacts(snapshot_root)
    removed: list[dict] = []
    for artifact in artifacts:
        if artifact["isUsable"]:
            continue
        removed.append({
            "name": artifact["name"],
            "root": str(artifact["root"]),
            "totalImages": artifact["totalImages"],
        })
        if not dry_run:
            shutil.rmtree(artifact["root"], ignore_errors=True)
    return removed


def prune_superseded_artifacts(snapshot_root: Path = SNAPSHOT_ROOT, *, dry_run: bool) -> dict:
    artifacts = collect_review_artifacts(snapshot_root)
    blessed = choose_blessed_artifact(artifacts)
    removed: list[dict] = []
    kept: list[dict] = []
    for artifact in artifacts:
        entry = {
            "name": artifact["name"],
            "root": str(artifact["root"]),
            "totalImages": artifact["totalImages"],
            "isUsable": artifact["isUsable"],
        }
        if artifact["name"] == blessed["name"]:
            kept.append(entry)
            continue
        if artifact["isUsable"]:
            removed.append(entry)
            if not dry_run:
                shutil.rmtree(artifact["root"], ignore_errors=True)
        else:
            kept.append(entry)
    return {
        "blessed": {
            "name": blessed["name"],
            "root": str(blessed["root"]),
            "totalImages": blessed["totalImages"],
        },
        "removed": removed,
        "kept": kept,
    }


def extract_directory_from_command(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if token == "--directory" and index + 1 < len(tokens):
            return tokens[index + 1]
    return None


def detect_listener_pid(port: int) -> int | None:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return int(pids[0]) if pids else None


def inspect_listener(port: int) -> dict | None:
    pid = detect_listener_pid(port)
    if pid is None:
        return None
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    command = result.stdout.strip()
    return {
        "pid": pid,
        "command": command,
        "directory": extract_directory_from_command(command),
    }


def wait_for_port(port: int, *, timeout_seconds: float = 3.0) -> bool:
    deadline = timeout_seconds
    step = 0.05
    waited = 0.0
    while waited < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(step)
            try:
                sock.connect(("127.0.0.1", port))
                return True
            except OSError:
                pass
        waited += step
    return False


def wait_for_listener_directory(port: int, expected_directory: str, *, timeout_seconds: float = 3.0) -> dict | None:
    deadline = timeout_seconds
    step = 0.05
    waited = 0.0
    while waited < deadline:
        listener = inspect_listener(port)
        if listener and listener["directory"] == expected_directory:
            return listener
        waited += step
    return None


def cmd_current(_: argparse.Namespace) -> int:
    artifacts = collect_review_artifacts()
    blessed = choose_blessed_artifact(artifacts)
    usable_count = sum(1 for item in artifacts if item["isUsable"])
    stale_artifacts = [
        {
            "name": item["name"],
            "root": str(item["root"]),
            "totalImages": item["totalImages"],
        }
        for item in artifacts
        if not item["isUsable"]
    ]
    listener = inspect_listener(8787)
    blessed_root = str(blessed["root"])
    status = "ok" if blessed["isUsable"] else "needs-regeneration"
    payload = {
        "status": status,
        "artifactCount": len(artifacts),
        "usableArtifactCount": usable_count,
        "staleArtifactCount": len(stale_artifacts),
        "supersededArtifactCount": max(usable_count - 1, 0),
        "blessed": {
            "name": blessed["name"],
            "root": blessed_root,
            "reviewHtml": str(resolve_review_html(blessed["root"])),
            "reviewManifest": str(blessed["root"] / "review_manifest.json"),
            "totalImages": blessed["totalImages"],
            "promiseCounts": blessed["promiseCounts"],
            "stateCounts": blessed["stateCounts"],
            "categories": blessed["categories"],
            "clusters": blessed["clusters"],
            "heroCandidates": blessed["heroCandidates"],
            "newSincePr878": blessed["newSincePr878"],
            "isUsable": blessed["isUsable"],
        },
        "staleArtifacts": stale_artifacts,
        "activeServer8787": (
            None if listener is None else {
                **listener,
                "matchesBlessed": listener["directory"] == blessed_root,
            }
        ),
        "artifacts": [
            {
                "name": item["name"],
                "root": str(item["root"]),
                "totalImages": item["totalImages"],
                "continueCount": item["promiseCounts"].get("Continue"),
                "weakCount": item["promiseCounts"].get("Weak"),
                "isUsable": item["isUsable"],
            }
            for item in artifacts
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if status == "ok" else 1


def cmd_prune(args: argparse.Namespace) -> int:
    removed = prune_stale_artifacts(dry_run=args.dry_run)
    payload = {
        "status": "ok",
        "dryRun": args.dry_run,
        "removedCount": len(removed),
        "removed": removed,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_prune_superseded(args: argparse.Namespace) -> int:
    result = prune_superseded_artifacts(dry_run=args.dry_run)
    payload = {
        "status": "ok",
        "dryRun": args.dry_run,
        "blessed": result["blessed"],
        "removedCount": len(result["removed"]),
        "removed": result["removed"],
        "kept": result["kept"],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    artifacts = collect_review_artifacts()
    blessed = choose_blessed_artifact(artifacts)
    if not blessed["isUsable"]:
        print(json.dumps({
            "status": "needs-regeneration",
            "error": "no-usable-review-artifact",
            "blessedCandidate": {
                "name": blessed["name"],
                "root": str(blessed["root"]),
                "totalImages": blessed["totalImages"],
            },
        }, ensure_ascii=False))
        return 1
    existing_pid = detect_listener_pid(args.port)
    replaced_pid = None
    if existing_pid is not None:
        os.kill(existing_pid, signal.SIGTERM)
        replaced_pid = existing_pid
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(args.port),
            "--directory",
            str(blessed["root"]),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=ROOT,
    )
    listener = wait_for_listener_directory(args.port, str(blessed["root"]))
    if listener is None:
        raise SystemExit(f"Failed to start blessed review server on port {args.port}")
    payload = {
        "status": "ok",
        "port": args.port,
        "pid": listener["pid"],
        "spawnedPid": process.pid,
        "replacedPid": replaced_pid,
        "blessed": {
            "name": blessed["name"],
            "root": str(blessed["root"]),
            "reviewHtml": str(resolve_review_html(blessed["root"])),
            "url": f"http://127.0.0.1:{args.port}/{resolve_review_html(blessed['root']).name}",
            "totalImages": blessed["totalImages"],
        },
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve and serve the blessed catalog review artifact.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("current")

    serve = subparsers.add_parser("serve")
    serve.add_argument("--port", type=int, default=8787)

    prune = subparsers.add_parser("prune-stale")
    prune.add_argument("--dry-run", action="store_true")

    prune_superseded = subparsers.add_parser("prune-superseded")
    prune_superseded.add_argument("--dry-run", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "current":
        return cmd_current(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "prune-stale":
        return cmd_prune(args)
    if args.command == "prune-superseded":
        return cmd_prune_superseded(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
