#!/usr/bin/env -S uv run --python 3.13 python
"""Bounded execution for the shipped typed compute-profile registry.

The profile registry is the source of truth for command shape and safety.  This
entrypoint plans or runs profiles against a clean checkout.  ``--target`` is
``auto`` (default), ``local`` or ``felix``; the only remote path is the fixed
launcher in ``lib/xmachine_transport.py``.  Agents never name a host, address,
path, shell or argv: ssh, transfer, PIDs and cleanup stay inside that adapter.
Nothing here invokes a shell or performs a production write.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import platform
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

from lib import xmachine_transport as transport_lib
from lib.compute_capsule import CapsuleError, materialize_tracked_capsule
from lib.compute_contract import (
    ContractError,
    load_profile_registry,
    resolve_profile,
)
from lib.compute_receipt import OscarAckAuthority, ReceiptSigner
from lib.compute_router import TARGETS, RouterError, decide


class CliError(ValueError):
    """A named refusal at the CLI boundary."""

    def __init__(self, code: str, detail: str = "", reasons: list[str] | None = None) -> None:
        self.code = code
        self.reasons = reasons or []
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


# --------------------------------------------------------------------- routing
# Every function below is a seam: tests inject fakes; production wiring only
# observes (probe/load/history) and never lets the caller supply a host.


def _now() -> float:
    return time.time()


def _cache_root(args: argparse.Namespace) -> Path:
    return args.repo.resolve() / ".cache" / "compute"


def _local_load() -> dict[str, Any]:
    """Observe Oscar's load; unknown load stays ``None`` so auto stays local."""

    try:
        load = os.getloadavg()[0]
        cpus = os.cpu_count() or 1
    except (OSError, AttributeError):
        return {"busy": None, "slowdown": None, "host_id": platform.node()}
    ratio = load / cpus
    return {"busy": ratio >= 0.75, "slowdown": 1.0 + ratio, "host_id": platform.node()}


def _gate_history(profile: str) -> list[float] | None:
    """Duration samples (seconds) from existing gate history.

    No gate-history source exists in this tree yet (IMP-20260808-4bd1ef); a
    second time SoT must not be invented here, so auto stays local.
    """

    return None


def _receipt_signer(registry: dict[str, Any]) -> ReceiptSigner | None:
    pinned = registry.get("felix_receipt_public_key")
    if not isinstance(pinned, str) or not pinned:
        return None
    try:
        return ReceiptSigner.from_public_bytes(base64.b64decode(pinned, validate=True))
    except (binascii.Error, ValueError):
        return None


def _transport(args: argparse.Namespace, job_id: str) -> transport_lib.XmachineTransport:
    return transport_lib.XmachineTransport(
        runner=transport_lib.streamed_runner(job_id, args.repo.resolve())
    )


def _ack_authority(cache: Path) -> OscarAckAuthority:
    """Oscar-controller-only MAC key, persisted 0600 beside the replay ledger."""

    key_path = cache / "controller" / "ack.key"
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(os.urandom(32))
    return OscarAckAuthority(cache / "controller" / "ack-ledger.json", key=key_path.read_bytes())


def _probe_felix(
    args: argparse.Namespace, registry: dict[str, Any]
) -> dict[str, Any] | None:
    """Live admission probe; any failure is ``None`` (unknown), never an exception."""

    job_id = transport_lib.new_job_id()
    try:
        raw = _transport(args, job_id).probe(job_id)
    except transport_lib.TransportError:
        return None
    probe = {
        key: raw.get(key)
        for key in (
            "reachable", "host_id", "host_role", "admitted", "runner_verified",
            "sandbox_ok", "production_healthy", "warmup_seconds", "transfer_seconds",
        )
    }
    probe["observed_at"] = _now()
    probe["receipt_key_pinned"] = _receipt_signer(registry) is not None
    return probe


def _route(
    args: argparse.Namespace,
    *,
    resolved: dict[str, Any],
    registry: dict[str, Any],
    repo_state: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    profile = registry["profiles"][resolved["profile"]]
    remote_eligible = profile["remote_eligible"] is True
    local = {"clean": repo_state["clean"], "missing_capabilities": missing, **_local_load()}
    felix = None
    # Probe only when a remote answer is possible; local never touches transport.
    if args.target != "local" and remote_eligible:
        felix = _probe_felix(args, registry)
    try:
        return decide(
            requested=args.target,
            remote_eligible=remote_eligible,
            minimum_remote_seconds=profile.get("minimum_remote_seconds"),
            local=local,
            felix=felix,
            history=_gate_history(resolved["profile"]),
            now=_now(),
        )
    except RouterError as error:
        raise CliError("router-refused", str(error), error.reasons) from error


def _local_receipt(
    resolved: dict[str, Any], repo_state: dict[str, Any], returncode: int, log: str
) -> dict[str, Any]:
    """Same schema as the Felix receipt; unsigned because no trust boundary was crossed."""

    body = {
        "schema": transport_lib.RECEIPT_SCHEMA,
        "job_id": transport_lib.new_job_id(),
        "profile": resolved["profile"],
        "spec_digest": resolved["spec_digest"],
        "runner_image_digest": resolved["spec"]["runner_image_digest"],
        "source": {"commit_sha": repo_state["head"], "tree_sha256": None},
        "host": {"host_id": platform.node(), "host_role": "local"},
        "returncode": returncode,
        "log_digest": hashlib.sha256(log.encode()).hexdigest(),
        "artifact_digests": {},
    }
    body["receipt_digest"] = hashlib.sha256(transport_lib.canonical(body)).hexdigest()
    body["signature"] = None
    return body


def _run_felix(
    args: argparse.Namespace,
    *,
    resolved: dict[str, Any],
    registry: dict[str, Any],
    repo_state: dict[str, Any],
    decision: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Remote execution.  Once submit starts, failure is reported, never retried locally."""

    signer = _receipt_signer(registry)
    if signer is None:
        raise CliError("router-refused", "receipt-key-unpinned", ["receipt-key-unpinned"])
    cache = _cache_root(args)
    job_id = transport_lib.new_job_id()
    nonce = transport_lib.new_nonce()
    try:
        capsule = materialize_tracked_capsule(
            args.repo.resolve(), repo_state["head"], cache / job_id / "capsule"
        )
    except CapsuleError as error:
        raise CliError("source-capsule", str(error)) from error
    spec = resolved["spec"]
    digest = transport_lib.request_digest(
        job_id=job_id, nonce=nonce, profile=resolved["profile"],
        spec_digest=resolved["spec_digest"], commit=capsule.commit,
        tree_digest=capsule.tree_sha256,
    )
    transport = _transport(args, job_id)
    try:
        transport.submit(
            job_id,
            fields={
                "nonce": nonce, "request-digest": digest, "commit": capsule.commit,
                "tree-digest": capsule.tree_sha256, "profile": resolved["profile"],
                "spec-digest": resolved["spec_digest"],
                "capsule": str(capsule.materialized_root),
            },
            params=spec["parameters"],
        )
        fetched = transport.fetch(job_id)
        accepted = transport_lib.accept_receipt(
            fetched.get("receipt"), fetched.get("log"),
            transport=transport, signer=signer, authority=_ack_authority(cache),
            expected={
                "job_id": job_id, "nonce": nonce, "request_digest": digest,
                "profile": resolved["profile"], "spec_digest": resolved["spec_digest"],
                "runner_image_digest": spec["runner_image_digest"],
                "commit_sha": capsule.commit, "tree_sha256": capsule.tree_sha256,
            },
            caller_host_id=platform.node(), cache_root=cache, now=_now(),
        )
    except transport_lib.TransportError as error:
        raise CliError("felix-run", error.code) from error
    receipt = accepted["receipt"]
    returncode = receipt["returncode"]
    payload = {
        "schema": SCHEMA,
        "command": "run",
        "ok": returncode == 0,
        "verdict": "success" if returncode == 0 else "failed",
        "decision": decision,
        "result": {
            "profile": resolved["profile"],
            "argv": list(resolved["argv"]),
            "shell": False,
            "spec_digest": resolved["spec_digest"],
            "source_head": repo_state["head"],
            "source_clean": repo_state["clean"],
            "returncode": returncode,
            "stdout": accepted["log"],
            "stderr": "",
            "job_id": job_id,
            "receipt": receipt,
            "result_path": accepted["result_path"],
            "cleanup": accepted["cleanup"],
            "artifact_contract": spec["artifact_contract"],
            "mutation_authority": False,
        },
    }
    return payload, returncode if returncode != 0 else 0


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    resolved, git, capabilities = _resolve(args, require_clean=False)
    spec = resolved["spec"]
    missing = sorted(set(spec["required_capabilities"]) - capabilities)
    decision = _route(
        args,
        resolved=resolved,
        registry=load_profile_registry(args.registry),
        repo_state=git,
        missing=missing,
    )
    return {
        "schema": SCHEMA,
        "command": "plan",
        "ok": not missing,
        "verdict": "planned" if not missing else "blocked",
        "decision": decision,
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
    registry = load_profile_registry(args.registry)
    decision = _route(args, resolved=resolved, registry=registry, repo_state=git, missing=missing)
    if decision["target"] == "felix":
        return _run_felix(
            args, resolved=resolved, registry=registry, repo_state=git, decision=decision
        )
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
        "decision": decision,
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
            "receipt": _local_receipt(resolved, git, returncode, stdout + stderr),
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
    remote_profiles = sorted(
        name for name, profile in registry["profiles"].items() if profile["remote_eligible"]
    )
    felix = None
    if args.target != "local" and remote_profiles:
        felix = _probe_felix(args, registry)
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
            "target": args.target,
            "remote_profiles": remote_profiles,
            "receipt_key_pinned": _receipt_signer(registry) is not None,
            "felix_probe": felix,
            "remote_execution": bool(remote_profiles),
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
        ("plan", "resolve a profile and routing decision without executing it"),
        ("run", "execute one resolved profile on the routed target"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("profile")
        command.add_argument("--param", action="append", default=[])
        command.add_argument("--test-path")
        command.add_argument("--target", choices=TARGETS, default="auto")
    status = commands.add_parser("status", help="observe registry, runner and routing state")
    status.add_argument("--target", choices=TARGETS, default="auto")
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
                "error": {
                    "code": _error_code(error),
                    "message": str(error),
                    "reasons": getattr(error, "reasons", []),
                },
            }
        )
        return ERROR_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
