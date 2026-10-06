#!/usr/bin/env -S uv run --python 3.13 python
"""Bounded local execution for the shipped typed compute-profile registry.

The profile registry is the source of truth for command shape and safety.  This
entrypoint only plans or runs profiles against a clean local checkout; it never
connects to a remote host, invokes a shell, or performs a production write.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

OPS_DIR = Path(__file__).resolve().parent
DEFAULT_REPO = OPS_DIR.parent
DEFAULT_REGISTRY = OPS_DIR / "compute_profiles.yml"
SCHEMA = "kg.compute.cli.v1"
ERROR_EXIT = 2
EXECUTION_ERROR_EXIT = 127
TIMEOUT_EXIT = 124

if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from lib.compute_contract import (
    ContractError,
    load_profile_registry,
    resolve_profile,
)


class CliError(ValueError):
    """A named refusal at the CLI boundary."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def _error_code(error: Exception) -> str:
    if isinstance(error, CliError):
        return error.code
    message = str(error)
    return message.split(":", 1)[0]


def _git_state(repo: Path) -> dict[str, Any]:
    """Read local Git state without changing the checkout."""

    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise CliError("git-state", str(error)) from error
    if status.returncode != 0:
        raise CliError("git-state", status.stderr.strip() or "status failed")
    if head.returncode != 0 or not head.stdout.strip():
        raise CliError("git-state", head.stderr.strip() or "HEAD unavailable")
    output = status.stdout
    return {
        "clean": not bool(output),
        "head": head.stdout.strip(),
        "status": output.splitlines(),
    }


def _available_capabilities() -> set[str]:
    """Return only capabilities that this local runner can provide safely."""

    available = {name for name in ("bash", "git", "uv") if shutil.which(name)}
    if sys.version_info[:2] == (3, 13):
        available.add("python-3.13")
    # The shipped pytest profile resolves pytest through the literal
    # ``uv run --with pytest`` command; uv is its capability provider rather
    # than an ambient pytest executable on PATH.
    if "uv" in available and "python-3.13" in available:
        available.add("pytest")
    return available


def _parameters(args: argparse.Namespace) -> dict[str, str]:
    params: dict[str, str] = {}
    if args.test_path is not None:
        params["test_path"] = args.test_path
    for item in args.param:
        if "=" not in item:
            raise CliError("parameter", "expected NAME=VALUE")
        name, value = item.split("=", 1)
        if not name or name in params:
            raise CliError("parameter", f"duplicate or empty name: {name!r}")
        params[name] = value
    return params


def _resolve(
    args: argparse.Namespace, *, require_clean: bool
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    repo = args.repo.resolve()
    git = _git_state(repo)
    if require_clean and not git["clean"]:
        raise CliError("dirty-source", "run requires a clean committed checkout")
    capabilities = _available_capabilities()
    try:
        resolved = resolve_profile(
            args.profile,
            _parameters(args),
            source_dirty=not git["clean"] if require_clean else False,
            available_capabilities=capabilities,
            registry_path=args.registry,
        )
    except ContractError as error:
        raise CliError(_error_code(error), str(error)) from error
    return resolved, git, capabilities


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    resolved, git, capabilities = _resolve(args, require_clean=False)
    spec = resolved["spec"]
    missing = sorted(set(spec["required_capabilities"]) - capabilities)
    return {
        "schema": SCHEMA,
        "command": "plan",
        "ok": not missing,
        "verdict": "planned" if not missing else "blocked",
        "result": {
            "profile": resolved["profile"],
            "argv": list(resolved["argv"]),
            "shell": False,
            "spec_digest": resolved["spec_digest"],
            "source_root": str(args.repo.resolve()),
            "source_head": git["head"],
            "source_clean": git["clean"],
            "required_capabilities": list(spec["required_capabilities"]),
            "available_capabilities": sorted(capabilities),
            "missing_capabilities": missing,
            "timeout_seconds": spec["timeout_seconds"],
            "network_policy": spec["network_policy"],
            "remote_eligible": spec["remote_eligible"],
            "side_effects": list(spec["side_effects"]),
            "mutation_authority": False,
        },
    }


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    resolved, git, capabilities = _resolve(args, require_clean=True)
    spec = resolved["spec"]
    missing = sorted(set(spec["required_capabilities"]) - capabilities)
    if missing:
        raise CliError("missing-capability", ",".join(missing))
    argv = list(resolved["argv"])
    started = time.monotonic()
    environment = os.environ.copy()
    environment.update({"UV_NO_CACHE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        completed = subprocess.run(
            argv,
            cwd=str(args.repo.resolve()),
            capture_output=True,
            check=False,
            env=environment,
            shell=False,
            text=True,
            timeout=spec["timeout_seconds"],
        )
        returncode = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        returncode = TIMEOUT_EXIT
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + "\nexecution timed out"
    except OSError as error:
        raise CliError("execution", str(error)) from error
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    payload = {
        "schema": SCHEMA,
        "command": "run",
        "ok": returncode == 0,
        "verdict": "success" if returncode == 0 else "failed",
        "result": {
            "profile": resolved["profile"],
            "argv": argv,
            "shell": False,
            "spec_digest": resolved["spec_digest"],
            "source_head": git["head"],
            "source_clean": git["clean"],
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "timeout_seconds": spec["timeout_seconds"],
            "artifact_contract": spec["artifact_contract"],
            "mutation_authority": False,
        },
    }
    return payload, returncode if returncode != 0 else 0


def _status(args: argparse.Namespace) -> dict[str, Any]:
    try:
        registry = load_profile_registry(args.registry)
    except ContractError as error:
        raise CliError(_error_code(error), str(error)) from error
    git = _git_state(args.repo.resolve())
    capabilities = sorted(_available_capabilities())
    return {
        "schema": SCHEMA,
        "command": "status",
        "ok": True,
        "verdict": "observation",
        "result": {
            "registry": str(args.registry.resolve()),
            "registry_schema": registry["schema"],
            "registry_version": registry["version"],
            "profiles": sorted(registry["profiles"]),
            "source_head": git["head"],
            "source_clean": git["clean"],
            "available_capabilities": capabilities,
            "remote_execution": False,
            "production_authority": False,
            "mutation_authority": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="plan or run a bounded local compute profile"
    )
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("plan", "resolve a profile without executing it"),
        ("run", "execute one resolved profile in a clean local checkout"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("profile")
        command.add_argument("--param", action="append", default=[])
        command.add_argument("--test-path")
    commands.add_parser("status", help="observe registry and local runner state")
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            payload = _plan(args)
            _emit(payload)
            return 0 if payload["ok"] else ERROR_EXIT
        if args.command == "run":
            payload, returncode = _run(args)
            _emit(payload)
            return returncode
        payload = _status(args)
        _emit(payload)
        return 0
    except (CliError, ContractError) as error:
        _emit(
            {
                "schema": SCHEMA,
                "command": args.command,
                "ok": False,
                "verdict": "blocked",
                "error": {"code": _error_code(error), "message": str(error)},
            }
        )
        return ERROR_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
