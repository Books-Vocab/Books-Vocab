#!/usr/bin/env -S /Users/chenliangyu/.local/bin/uv run --python 3.13 python
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = ROOT / "build" / "snapshots"


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_review_artifacts(snapshot_root: Path = SNAPSHOT_ROOT) -> list[dict]:
    artifacts: list[dict] = []
    for manifest_path in sorted(snapshot_root.glob("*/review_manifest.json")):
        manifest = load_manifest(manifest_path)
        artifacts.append({
            "name": manifest_path.parent.name,
            "root": manifest_path.parent,
            "manifest": manifest,
            "totalImages": manifest.get("totalImages", 0),
            "promiseCounts": manifest.get("promiseCounts", {}),
            "stateCounts": manifest.get("stateCounts", {}),
            "categories": len({item["category"] for item in manifest.get("items", [])}),
            "clusters": len({item["clusterID"] for item in manifest.get("items", [])}),
            "heroCandidates": sum(1 for item in manifest.get("items", []) if item.get("heroCandidate")),
            "newSincePr878": sum(1 for item in manifest.get("items", []) if item.get("newSincePr878")),
        })
    return artifacts


def choose_blessed_artifact(artifacts: list[dict]) -> dict:
    if not artifacts:
        raise SystemExit("No review artifacts found under build/snapshots")
    return max(
        artifacts,
        key=lambda item: (
            item["totalImages"],
            item["name"],
        ),
    )


def detect_listener_pid(port: int) -> int | None:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return int(pids[0]) if pids else None


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


def cmd_current(_: argparse.Namespace) -> int:
    artifacts = collect_review_artifacts()
    blessed = choose_blessed_artifact(artifacts)
    payload = {
        "status": "ok",
        "artifactCount": len(artifacts),
        "blessed": {
            "name": blessed["name"],
            "root": str(blessed["root"]),
            "reviewHtml": str(blessed["root"] / "review.html"),
            "reviewManifest": str(blessed["root"] / "review_manifest.json"),
            "totalImages": blessed["totalImages"],
            "promiseCounts": blessed["promiseCounts"],
            "stateCounts": blessed["stateCounts"],
            "categories": blessed["categories"],
            "clusters": blessed["clusters"],
            "heroCandidates": blessed["heroCandidates"],
            "newSincePr878": blessed["newSincePr878"],
        },
        "artifacts": [
            {
                "name": item["name"],
                "root": str(item["root"]),
                "totalImages": item["totalImages"],
                "continueCount": item["promiseCounts"].get("Continue"),
                "weakCount": item["promiseCounts"].get("Weak"),
            }
            for item in artifacts
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    artifacts = collect_review_artifacts()
    blessed = choose_blessed_artifact(artifacts)
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
    if not wait_for_port(args.port):
        raise SystemExit(f"Failed to start review server on port {args.port}")
    payload = {
        "status": "ok",
        "port": args.port,
        "pid": process.pid,
        "replacedPid": replaced_pid,
        "blessed": {
            "name": blessed["name"],
            "root": str(blessed["root"]),
            "reviewHtml": str(blessed["root"] / "review.html"),
            "url": f"http://127.0.0.1:{args.port}/review.html",
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

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "current":
        return cmd_current(args)
    if args.command == "serve":
        return cmd_serve(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
