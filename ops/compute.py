#!/usr/bin/env -S uv run --python 3.13 --with cryptography>=48,<49 python
"""Bounded local/auto/Felix execution for typed compute profiles.

The profile registry is the source of truth for command shape and safety.  This
entrypoint only uses literal argv and live-observed admission facts; it
never invokes a shell, schedules an agent, or performs a production write.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import platform
import shutil
import statistics
import stat
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

from lib import compute_history as history_lib
from lib import xmachine_transport as transport_lib
from lib.compute_capsule import CapsuleError, materialize_tracked_capsule
from lib.compute_contract import (
    ContractError,
    load_profile_registry,
    resolve_profile,
)
from lib.compute_hosts import host_role
from lib.compute_receipt import OscarAckAuthority, ReceiptSigner
from lib.compute_router import choose_route, remote_failure

PROBE_MAX_AGE_SECONDS = 60.0
BUSY_LOAD_RATIO = 0.75


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
    # ``selftest`` has no typed flags: its closed profile declares no parameters.
    if getattr(args, "test_path", None) is not None:
        params["test_path"] = args.test_path
    for item in getattr(args, "param", []):
        if "=" not in item:
            raise CliError("parameter", "expected NAME=VALUE")
        name, value = item.split("=", 1)
        if not name or name in params:
            raise CliError("parameter", f"duplicate or empty name: {name!r}")
        params[name] = value
    return params


# ---------------------------------------------------------------- observation
# Every function in this block is a seam: tests inject fakes, production only
# observes.  The caller can never supply a host, probe result or admission.


def _now() -> float:
    return time.time()


def _cache_root(args: argparse.Namespace) -> Path:
    return args.repo.resolve() / ".cache" / "compute"


def _local_load() -> dict[str, Any]:
    """Observe Oscar's load; unknown load stays ``None`` so auto stays local."""

    try:
        ratio = os.getloadavg()[0] / (os.cpu_count() or 1)
    except (OSError, AttributeError):
        return {"busy": None, "slowdown": None}
    return {"busy": ratio >= BUSY_LOAD_RATIO, "slowdown": 1.0 + ratio}


def _gate_history(profile: str, cache: Path) -> list[float] | None:
    """Fresh local run durations (seconds) for ``profile``; ``None`` if sparse.

    Source: the append-only ``.cache/compute/history.ndjson`` written after
    verified successful runs.  Malformed, stale (>14 days) or too few (<3)
    samples yield ``None`` so ``auto`` stays on local.
    """

    return history_lib.local_durations(cache, profile, _now())


def _record_history(
    cache: Path,
    *,
    profile: str,
    mode: str,
    duration_seconds: float,
    transfer_seconds: float | None,
) -> None:
    """Best-effort: a history failure must never change a run's result."""

    try:
        history_lib.record(
            cache,
            profile=profile,
            mode=mode,
            duration_seconds=duration_seconds,
            transfer_seconds=transfer_seconds,
            now=_now(),
        )
    except Exception as error:  # noqa: BLE001 - recording is non-fatal by contract
        print(f"compute: history not recorded: {error}", file=sys.stderr)


def _receipt_signer(registry: dict[str, Any]) -> ReceiptSigner | None:
    pinned = registry.get("felix_receipt_public_key")
    if not isinstance(pinned, str) or not pinned:
        return None
    try:
        return ReceiptSigner.from_public_bytes(base64.b64decode(pinned, validate=True))
    except (binascii.Error, ValueError):
        return None


def _transport(
    args: argparse.Namespace, job_id: str
) -> transport_lib.XmachineTransport:
    return transport_lib.XmachineTransport(
        runner=transport_lib.streamed_runner(job_id, args.repo.resolve())
    )


def _ack_authority(cache: Path) -> OscarAckAuthority:
    """Oscar-controller-only MAC key, persisted 0600 beside the ACK ledger."""

    key_path = cache / "controller" / "ack.key"
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(os.urandom(32))
    return OscarAckAuthority(
        cache / "controller" / "ack-ledger.json", key=key_path.read_bytes()
    )


_PROBE_KEYS = (
    "reachable",
    "host_id",
    "host_role",
    "admitted",
    "runner_verified",
    "runner_image_digest",
    "sandbox_ok",
    "sandbox_policy",
    "production_healthy",
    "warmup_seconds",
    "transfer_seconds",
)


def _caller_identity() -> dict[str, str | None]:
    """Who is calling: hostname plus its role from the closed host table."""

    node = platform.node()
    return {"host_id": node, "host_role": host_role(node)}


def _probe_felix(
    args: argparse.Namespace, profile: str | None = None
) -> dict[str, Any] | None:
    """Live admission probe; any failure is ``None`` (unknown), never raised.

    ``profile`` lets Felix report the sandbox policy of that closed profile.
    """

    job_id = transport_lib.new_job_id()
    try:
        raw = _transport(args, job_id).probe(
            job_id, fields={"profile": profile} if profile else None
        )
    except transport_lib.TransportError:
        return None
    probe = {key: raw.get(key) for key in _PROBE_KEYS}
    probe["observed_at"] = _now()
    return probe


def _is_seconds(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    )


def _route_facts(
    probe: dict[str, Any] | None,
    *,
    spec: dict[str, Any],
    git: dict[str, Any],
    signer: ReceiptSigner | None,
) -> dict[str, Any]:
    """Reduce observations to strict booleans; only literal ``True`` passes."""

    probe = probe if isinstance(probe, dict) else {}
    observed = probe.get("observed_at")
    now = _now()
    host_id = probe.get("host_id")
    return {
        "live_admission": probe.get("reachable") is True
        and probe.get("host_role") == "felix"
        and probe.get("admitted") is True,
        "probe_fresh": _is_seconds(observed)
        and observed <= now + 1
        and now - observed <= PROBE_MAX_AGE_SECONDS,
        "cross_host": isinstance(host_id, str)
        and bool(host_id)
        and host_id != platform.node(),
        "production_healthy": probe.get("production_healthy") is True,
        "receipt_key_pinned": signer is not None,
        "remote_eligible": spec["remote_eligible"] is True,
        "source_clean": git["clean"] is True,
        "runner_verified": probe.get("runner_verified") is True
        and probe.get("runner_image_digest") == spec["runner_image_digest"],
        "sandbox_verified": probe.get("sandbox_ok") is True
        and probe.get("sandbox_policy") == spec["sandbox_policy"],
    }


def _costs(
    probe: dict[str, Any] | None, load: dict[str, Any], profile: str, cache: Path
) -> tuple[int | None, int | None]:
    """Predicted (local, felix) milliseconds from recorded run history only.

    Transfer time comes from the probe when it reports one, else from the
    median of recorded felix runs; any missing input yields ``(None, None)``.
    """

    samples = [s for s in (_gate_history(profile, cache) or []) if _is_seconds(s)]
    probe = probe if isinstance(probe, dict) else {}
    transfer = probe.get("transfer_seconds")
    if not _is_seconds(transfer):
        transfer = history_lib.felix_transfer_seconds(cache, profile, _now())
    slowdown = load.get("slowdown")
    if (
        not samples
        or not _is_seconds(slowdown)
        or not _is_seconds(probe.get("warmup_seconds"))
        or not _is_seconds(transfer)
    ):
        return None, None
    estimate = statistics.median(samples)
    return (
        int(estimate * slowdown * 1000),
        int((estimate + probe["warmup_seconds"] + transfer) * 1000),
    )


def _route(
    args: argparse.Namespace,
    *,
    spec: dict[str, Any],
    registry: dict[str, Any],
    git: dict[str, Any],
    profile: str,
) -> dict[str, Any]:
    probe = None
    # Probe only when a remote answer is possible; local never touches transport.
    if args.mode != "local" and spec["remote_eligible"] is True:
        probe = _probe_felix(args, profile)
    load = _local_load()
    local_cost, felix_cost = _costs(probe, load, profile, _cache_root(args))
    return choose_route(
        args.mode,
        **_route_facts(probe, spec=spec, git=git, signer=_receipt_signer(registry)),
        local_busy=load.get("busy"),
        local_cost_ms=local_cost,
        felix_cost_ms=felix_cost,
    )


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


def _registry(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return load_profile_registry(args.registry)
    except ContractError as error:
        raise CliError(_error_code(error), str(error)) from error


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    resolved, git, capabilities = _resolve(args, require_clean=False)
    spec = resolved["spec"]
    missing = sorted(set(spec["required_capabilities"]) - capabilities)
    route = _route(
        args,
        spec=spec,
        registry=_registry(args),
        git=git,
        profile=resolved["profile"],
    )
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
            "route": route,
        },
    }


def _run_local(
    args: argparse.Namespace,
    *,
    resolved: dict[str, Any],
    git: dict[str, Any],
    capabilities: set[str],
    route: dict[str, Any],
) -> tuple[dict[str, Any], int]:
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
    elapsed = time.monotonic() - started
    duration_ms = round(elapsed * 1000, 3)
    if returncode == 0:
        _record_history(
            _cache_root(args),
            profile=resolved["profile"],
            mode="local",
            duration_seconds=elapsed,
            transfer_seconds=None,
        )
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
            "route": route,
        },
    }
    return payload, returncode if returncode != 0 else 0


def _discard_capsule(root: Path) -> None:
    """Best-effort removal of the read-only source capsule (0555/0444 tree)."""

    if not root.exists():
        return
    for path in (root, *root.rglob("*")):
        try:
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        except OSError:
            pass
    shutil.rmtree(root, ignore_errors=True)


def _felix_failure(
    resolved: dict[str, Any], *, job_id: str, code: str
) -> tuple[dict[str, Any], int]:
    return {
        "schema": SCHEMA,
        "command": "run",
        "ok": False,
        "verdict": "failed",
        "result": {
            "profile": resolved["profile"],
            "job_id": job_id,
            "shell": False,
            "route": remote_failure(code, child_started=True),
            "failure_code": code,
            "mutation_authority": False,
        },
    }, ERROR_EXIT


def _felix_roundtrip(
    args: argparse.Namespace,
    *,
    resolved: dict[str, Any],
    git: dict[str, Any],
    signer: ReceiptSigner,
    job_id: str,
    transport: transport_lib.XmachineTransport,
) -> dict[str, Any]:
    """capsule -> submit -> fetch -> verified accept (+ one-time ACK).

    Returns the accepted result plus the Oscar-side source identity that was
    requested.  Raises ``TransportError`` (named) on any verification failure;
    the capsule is always discarded.
    """

    spec = resolved["spec"]
    cache = _cache_root(args)
    nonce = transport_lib.new_nonce()
    transfer_started = time.monotonic()
    try:
        capsule = materialize_tracked_capsule(
            args.repo.resolve(), git["head"], cache / job_id / "capsule"
        )
    except CapsuleError as error:
        raise CliError("source-capsule", str(error)) from error
    digest = transport_lib.request_digest(
        job_id=job_id,
        nonce=nonce,
        profile=resolved["profile"],
        spec_digest=resolved["spec_digest"],
        commit=capsule.commit,
        tree_digest=capsule.tree_sha256,
    )
    transfer_seconds: float | None = None
    try:
        transport.submit(
            job_id,
            fields={
                "nonce": nonce,
                "request-digest": digest,
                "commit": capsule.commit,
                "tree-digest": capsule.tree_sha256,
                "profile": resolved["profile"],
                "spec-digest": resolved["spec_digest"],
                "capsule": str(capsule.materialized_root),
            },
            params=spec["parameters"],
        )
        transfer_seconds = time.monotonic() - transfer_started
        fetched = transport.fetch(job_id)
        accepted = transport_lib.accept_receipt(
            fetched.get("receipt"),
            fetched.get("log"),
            transport=transport,
            signer=signer,
            authority=_ack_authority(cache),
            expected={
                "job_id": job_id,
                "nonce": nonce,
                "request_digest": digest,
                "profile": resolved["profile"],
                "spec_digest": resolved["spec_digest"],
                "runner_image_digest": spec["runner_image_digest"],
                "commit_sha": capsule.commit,
                "tree_sha256": capsule.tree_sha256,
            },
            caller_host_id=platform.node(),
            cache_root=cache,
            now=_now(),
        )
    finally:
        _discard_capsule(capsule.materialized_root)
    return {
        "accepted": accepted,
        "source": {"commit_sha": capsule.commit, "tree_sha256": capsule.tree_sha256},
        "transfer_seconds": transfer_seconds,
    }


def _run_felix(
    args: argparse.Namespace,
    *,
    resolved: dict[str, Any],
    registry: dict[str, Any],
    git: dict[str, Any],
    route: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Remote execution.  Once submit starts, failure is reported, never retried locally."""

    signer = _receipt_signer(registry)
    if signer is None:  # unreachable via routing; defence in depth
        raise CliError("felix-refused-receipt-key-unpinned")
    spec = resolved["spec"]
    job_id = transport_lib.new_job_id()
    started = time.monotonic()
    try:
        trip = _felix_roundtrip(
            args,
            resolved=resolved,
            git=git,
            signer=signer,
            job_id=job_id,
            transport=_transport(args, job_id),
        )
    except transport_lib.TransportError as error:
        return _felix_failure(resolved, job_id=job_id, code=error.code)
    accepted = trip["accepted"]
    body = accepted["receipt"]
    returncode = body["returncode"]
    if returncode == 0:  # verified receipt + success only
        _record_history(
            _cache_root(args),
            profile=resolved["profile"],
            mode="felix",
            duration_seconds=time.monotonic() - started,
            transfer_seconds=trip["transfer_seconds"],
        )
    return {
        "schema": SCHEMA,
        "command": "run",
        "ok": returncode == 0,
        "verdict": "success" if returncode == 0 else "failed",
        "result": {
            "profile": resolved["profile"],
            "argv": list(resolved["argv"]),
            "shell": False,
            "spec_digest": resolved["spec_digest"],
            "source_head": git["head"],
            "source_clean": git["clean"],
            "returncode": returncode,
            "stdout": accepted["log"],
            "stderr": "",
            "job_id": job_id,
            "receipt": {
                "receipt_digest": body["receipt_digest"],
                "source": body["source"],
                "returncode": returncode,
                "log_digest": body["log_digest"],
                "host_role": body["host"]["host_role"],
            },
            "verification": {
                "signature_verified": accepted["signature_verified"],
                "nonce_verified": accepted["nonce_verified"],
                "replay_checked": accepted["replay_checked"],
                "ack_verified": accepted["ack_verified"],
            },
            "result_path": accepted["result_path"],
            "cleanup": accepted["cleanup"],
            "artifact_contract": spec["artifact_contract"],
            "mutation_authority": False,
            "route": route,
        },
    }, returncode if returncode != 0 else 0


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    resolved, git, capabilities = _resolve(args, require_clean=args.mode == "local")
    registry = _registry(args)
    route = _route(
        args,
        spec=resolved["spec"],
        registry=registry,
        git=git,
        profile=resolved["profile"],
    )
    if route["selected"] is None:
        raise CliError(route["reason_code"])
    if route["selected"] == "felix":
        return _run_felix(
            args, resolved=resolved, registry=registry, git=git, route=route
        )
    if not git["clean"]:  # auto/local fallback must still run a clean checkout
        raise CliError("dirty-source", "run requires a clean committed checkout")
    return _run_local(
        args, resolved=resolved, git=git, capabilities=capabilities, route=route
    )


def _status(args: argparse.Namespace) -> dict[str, Any]:
    registry = _registry(args)
    git = _git_state(args.repo.resolve())
    capabilities = sorted(_available_capabilities())
    remote = sorted(
        name
        for name, profile in registry["profiles"].items()
        if profile["remote_eligible"] is True
    )
    felix_available = False
    if args.mode != "local" and remote:
        signer = _receipt_signer(registry)
        felix_available = any(
            choose_route(
                "felix",
                **_route_facts(
                    _probe_felix(args, name),
                    spec=registry["profiles"][name],
                    git=git,
                    signer=signer,
                ),
                local_busy=None,
                local_cost_ms=None,
                felix_cost_ms=None,
            )["selected"]
            == "felix"
            for name in remote
        )
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
            "remote_profiles": remote,
            "felix_available": felix_available,
            "source_head": git["head"],
            "source_clean": git["clean"],
            "available_capabilities": capabilities,
            "remote_execution": False,
            "production_authority": False,
            "mutation_authority": False,
        },
    }


SELFTEST_SCHEMA = "kg.compute.selftest.v1"
SELFTEST_PROFILES = ("source-identity",)


def _selftest_failure(code: str, **evidence: Any) -> tuple[dict[str, Any], int]:
    return {
        "schema": SELFTEST_SCHEMA,
        "command": "selftest",
        "ok": False,
        "verdict": "failed",
        "verified": False,
        "failure_code": code,
        **evidence,
    }, ERROR_EXIT


def _health(probe: dict[str, Any] | None) -> str:
    if not isinstance(probe, dict):
        return "unknown"
    return "healthy" if probe.get("production_healthy") is True else "unhealthy"


def _selftest(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Live cross-host proof; fails closed with a named code, never a false green.

    Only the closed ``source-identity`` profile may be proven.  The profile's
    ``remote_eligible`` flag is the only fact waived (selftest is how a pinned
    key and a launcher earn eligibility); every other route gate still applies.
    """

    if args.profile not in SELFTEST_PROFILES:
        return _selftest_failure("selftest-profile")
    caller = _caller_identity()
    evidence: dict[str, Any] = {"caller": caller}
    if caller.get("host_role") != "oscar":
        return _selftest_failure("selftest-caller-not-oscar", **evidence)
    try:
        resolved, git, _capabilities = _resolve(args, require_clean=True)
        registry = _registry(args)
    except (CliError, ContractError) as error:
        return _selftest_failure(_error_code(error), **evidence)
    spec = resolved["spec"]
    signer = _receipt_signer(registry)
    probe_before = _probe_felix(args, resolved["profile"])
    facts = _route_facts(probe_before, spec=spec, git=git, signer=signer)
    facts["remote_eligible"] = True
    route = choose_route(
        "felix", **facts, local_busy=None, local_cost_ms=None, felix_cost_ms=None
    )
    if route["selected"] != "felix" or signer is None:
        return _selftest_failure(route["reason_code"], **evidence)
    job_id = transport_lib.new_job_id()
    transport = _transport(args, job_id)
    evidence["job_id"] = job_id
    try:
        trip = _felix_roundtrip(
            args,
            resolved=resolved,
            git=git,
            signer=signer,
            job_id=job_id,
            transport=transport,
        )
    except transport_lib.TransportError as error:
        return _selftest_failure(error.code, **evidence)
    except CliError as error:
        return _selftest_failure(error.code, **evidence)
    accepted = trip["accepted"]
    body = accepted["receipt"]
    try:
        transport.fetch(job_id)
        residual = True  # Felix still serves the job after the one-time ACK
    except transport_lib.TransportError:
        residual = False
    probe_after = _probe_felix(args, resolved["profile"])
    try:
        sandbox_tree = json.loads(accepted["log"]).get("tree_sha256")
    except (TypeError, ValueError, AttributeError):
        sandbox_tree = None
    source = trip["source"]
    payload = {
        "schema": SELFTEST_SCHEMA,
        "command": "selftest",
        "caller": caller,
        "remote": {**body["host"], "source": body["source"]},
        "transport": {"kind": transport_lib.TRANSPORT_KIND},
        "source": source,
        "receipt": {
            "verifier": "oscar-independent",
            "signature_verified": accepted["signature_verified"],
            "nonce_verified": accepted["nonce_verified"],
            "replay_checked": accepted["replay_checked"],
            "ack_verified": accepted["ack_verified"],
            "receipt_digest": body["receipt_digest"],
            "returncode": body["returncode"],
        },
        "runner": {
            "verified": facts["runner_verified"],
            "image_digest": body["runner_image_digest"],
        },
        "sandbox": {"tree_sha256_matches": sandbox_tree == source["tree_sha256"]},
        "production": {"before": _health(probe_before), "after": _health(probe_after)},
        "cleanup": {
            "state": accepted["cleanup"]["state"],
            "fetch_after_ack_refused": not residual,
        },
        "job_id": job_id,
    }
    failure = next(
        (
            code
            for failed, code in (
                (body["returncode"] != 0, "remote-child-failed"),
                (body["host"]["host_id"] == caller["host_id"], "same-host"),
                (body["source"] != source, "receipt-source"),
                (
                    not payload["sandbox"]["tree_sha256_matches"],
                    "sandbox-tree-mismatch",
                ),
                (residual, "cleanup-residual"),
                (
                    payload["production"] != {"before": "healthy", "after": "healthy"},
                    "production-unhealthy",
                ),
            )
            if failed
        ),
        None,
    )
    payload["verified"] = failure is None
    payload["ok"] = failure is None
    payload["verdict"] = "verified" if failure is None else "failed"
    if failure is not None:
        payload["failure_code"] = failure
    return payload, 0 if failure is None else ERROR_EXIT


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
        command.add_argument(
            "--mode", choices=("local", "auto", "felix"), default="local"
        )
    status = commands.add_parser("status", help="observe registry and runner state")
    status.add_argument("--mode", choices=("local", "auto", "felix"), default="local")
    selftest = commands.add_parser(
        "selftest", help="prove a real cross-host Felix round trip (fails closed)"
    )
    selftest.add_argument("--target", choices=("felix",), required=True)
    selftest.add_argument("--profile", required=True)
    selftest.add_argument("--json", action="store_true")
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            payload = _plan(args)
            payload["ok"] = (
                payload["ok"] and payload["result"]["route"]["selected"] is not None
            )
            payload["verdict"] = "planned" if payload["ok"] else "blocked"
            _emit(payload)
            return 0 if payload["ok"] else ERROR_EXIT
        if args.command == "run":
            payload, returncode = _run(args)
            _emit(payload)
            return returncode
        if args.command == "selftest":
            payload, returncode = _selftest(args)
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
