#!/usr/bin/env -S uv run --python 3.13
"""Offline-testable local/remote .env drift checker.

The shell entrypoint supplies paths and the server identity; this module owns
parsing and comparison so it can be tested without sourcing a production shell
dispatch or embedding a second Python program in it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


HOST_SPECIFIC = {
    "APP_STORE_ROOT_CA_PATH": ("certs", "{container_root}/certs"),
    "APP_STORE_CONNECT_PRIVATE_KEY_PATH": ("certs", "{container_root}/certs"),
}


def parse_env_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def _read_local(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"✗ 本地 .env 不存在：{path}")
    return parse_env_text(path.read_text(encoding="utf-8"))


def _read_remote(path: str, server: str) -> dict[str, str]:
    ssh_bin = os.environ.get("KG_SSH_BIN", "ssh")
    proc = subprocess.run(
        [ssh_bin, "-T", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes", server, f"cat {path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"✗ 無法讀取遠端 .env：{proc.stderr.strip()}")
    return parse_env_text(proc.stdout)


def compare_envs(
    local: dict[str, str],
    remote: dict[str, str],
    *,
    local_dir: Path,
    container_root: str,
) -> list[tuple[str, str, str, str]]:
    mismatches: list[tuple[str, str, str, str]] = []
    for key in sorted(set(local) & set(remote)):
        lv, rv = local[key], remote[key]
        if key in HOST_SPECIFIC:
            local_base = local_dir / HOST_SPECIFIC[key][0]
            remote_base = HOST_SPECIFIC[key][1].format(container_root=container_root)
            if not lv.startswith(str(local_base) + "/"):
                mismatches.append((key, lv, rv, f"本地值應位於 {local_base}/ 下"))
                continue
            if not rv.startswith(remote_base + "/"):
                mismatches.append((key, lv, rv, f"遠端值應位於 {remote_base}/ 下"))
                continue
            if Path(lv).name != Path(rv).name:
                mismatches.append((key, lv, rv, "本地與遠端指向的檔名不同"))
        elif lv != rv:
            mismatches.append((key, lv, rv, "值不同"))
    return mismatches


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print("usage: env_drift.py LOCAL_ENV REMOTE_ENV LOCAL_DIR CONTAINER_ROOT SERVER", file=sys.stderr)
        return 64
    local_path, remote_path, local_dir, container_root, server = argv[1:]
    local = _read_local(Path(local_path))
    remote = _read_remote(remote_path, server)
    missing_remote = sorted(set(local) - set(remote))
    missing_local = sorted(set(remote) - set(local))
    mismatches = compare_envs(local, remote, local_dir=Path(local_dir).resolve(), container_root=container_root)
    if missing_remote or missing_local or mismatches:
        if missing_remote:
            print("✗ 遠端缺少以下 key:")
            for key in missing_remote:
                print(f"  - {key}")
        if missing_local:
            print("✗ 本地缺少以下 key:")
            for key in missing_local:
                print(f"  - {key}")
        if mismatches:
            print("✗ 本地/遠端 .env 存在不一致:")
            for key, lv, rv, reason in mismatches:
                print(f"  - {key}: {reason}")
                print(f"      local : {lv}")
                print(f"      remote: {rv}")
        return 1
    print("✓ 本地/遠端 .env 已一致（host-specific path key 已正規化檢查）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
