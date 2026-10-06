#!/usr/bin/env -S uv run --python 3.13 --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["cryptography>=48,<49"]
# ///
"""Fixed Felix compute launcher: ``probe`` / ``submit`` / ``fetch`` / ``ack``.

One program, two roles, selected by the host it runs on:

* **Oscar (relay).**  ``ops/lib/xmachine_transport.py`` invokes this file with a
  literal argv.  The relay re-validates every value against the same closed
  patterns, then runs ONE fixed ssh command whose remote part carries no dynamic
  value.  The request (and, for ``submit``, a gzip tar of the clean capsule) goes
  over stdin, so no profile parameter, digest or job id is ever seen by a shell.
* **Felix (exec).**  ``exec`` reads that request, admits the host, verifies the
  closed profile / spec digest / request digest / tree digest, runs the profile
  argv in a network-less read-only container, signs a receipt with the
  Felix-held Ed25519 key and removes every artifact on the one-time ACK.

Stdout is always exactly one JSON object.  Failures are ``{"error":{"code":..}}``
with a stable named code and a non-zero exit.  Nothing here prints a key, a key
path, a Felix path, a PID or an address.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from lib import xmachine_transport as xt  # noqa: E402
from lib.compute_admission import AdmissionError, admit  # noqa: E402
from lib.compute_contract import (  # noqa: E402
    ContractError,
    load_profile_registry,
    resolve_profile,
)
from lib.compute_hosts import host_role  # noqa: E402
from lib.compute_job_lifecycle import JobLifecycle, LifecycleError  # noqa: E402
from lib.compute_receipt import ReceiptSigner  # noqa: E402

VERBS = xt.VERBS
REGISTRY_PATH = OPS_DIR / "compute_profiles.yml"

# Fixed transport: the remote command is a constant with no dynamic value.
SSH_TARGET = "chenliangyu@100.118.39.104"  # felix, tailnet address (host_topology.md)
SSH_BIN_DEFAULT = "/usr/bin/ssh"
# The launcher holds the receipt-signing key, so it must run reviewed code from
# an exact merged commit.  It lives in a dedicated, detached checkout on Felix
# (~/kg-compute, updated only by an operator to a merged main SHA) and never in
# the ~/kg-prod service tree, so installing or updating it cannot touch, and
# does not require releasing, the production backend.
REMOTE_COMMAND = (
    "~/.local/bin/uv run --python 3.13 --script "
    "~/kg-compute/ops/felix_compute_launcher.py exec"
)
RELAY_TIMEOUT_SECONDS = 840.0

STATE_DIR_DEFAULT = "~/.kg-compute"
KEY_FILE_DEFAULT = "~/.kg-compute/receipt-ed25519.pem"
HEALTH_URL_DEFAULT = "http://127.0.0.1:8000/api/system/info"
DEPLOY_LOCK_DEFAULT = "/tmp/kg-deploy.lock"
JOB_TTL_DEFAULT = 3600
LOG_LIMIT = 1024 * 1024
HEADER_LIMIT = 64 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
SANDBOX_POLICY = {
    "network": "none",
    "read_only_rootfs": True,
    "non_root": True,
    "cap_drop": ["ALL"],
    "no_new_privileges": True,
}
BUSY_PROCESSES = ("kg_backup.sh", "kg_reconcile.sh")


class LauncherError(ValueError):
    """Named, stable refusal; ``code`` is the only thing that crosses the wire."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# ------------------------------------------------------------------ identity


def _node() -> str:
    # KG_COMPUTE_TEST_NODE is a test seam: it only changes which host this
    # process believes it is; Oscar still rejects a receipt whose host id equals
    # its own, and only a registry-pinned key makes a receipt trusted at all.
    return os.environ.get("KG_COMPUTE_TEST_NODE") or platform.node()


def _felix_identity() -> dict[str, str]:
    node = _node()
    if host_role(node) != "felix":
        raise LauncherError("not-felix")
    return {"host_id": node, "host_role": "felix"}


def _state_dir() -> Path:
    return Path(
        os.path.expanduser(os.environ.get("KG_COMPUTE_STATE_DIR") or STATE_DIR_DEFAULT)
    )


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


# ----------------------------------------------------------------- key custody


def _key_path() -> Path:
    return Path(
        os.path.expanduser(
            os.environ.get("KG_FELIX_RECEIPT_KEY_FILE") or KEY_FILE_DEFAULT
        )
    )


def _load_signer() -> ReceiptSigner:
    """Load the Felix-held Ed25519 key or fail closed with a named code."""

    path = _key_path()
    try:
        info = path.lstat()
    except OSError as error:
        raise LauncherError("receipt-key-missing") from error
    if not stat.S_ISREG(info.st_mode):
        raise LauncherError("receipt-key-invalid")
    if info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise LauncherError("receipt-key-permissions")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ModuleNotFoundError as error:
        raise LauncherError("receipt-key-unsupported") from error
    try:
        private = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except Exception as error:  # never echo parser detail: it can quote key bytes
        raise LauncherError("receipt-key-invalid") from error
    if not isinstance(private, Ed25519PrivateKey):
        raise LauncherError("receipt-key-invalid")
    return ReceiptSigner(private, private.public_key())


def keygen() -> dict[str, Any]:
    """Create the Felix receipt key (once) and print ONLY the public key."""

    _felix_identity()
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ModuleNotFoundError as error:
        raise LauncherError("receipt-key-unsupported") from error
    path = _key_path()
    _private_dir(path.parent)
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise LauncherError("receipt-key-exists") from error
    with os.fdopen(fd, "wb") as stream:
        stream.write(pem)
        stream.flush()
        os.fsync(stream.fileno())
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {"public_key": base64.b64encode(raw).decode("ascii")}


# ------------------------------------------------------------- host admission


def _runtime() -> str:
    configured = os.environ.get("KG_COMPUTE_RUNTIME")
    return configured or shutil.which("docker") or "/usr/local/bin/docker"


def _process_running(name: str) -> bool:
    pgrep = shutil.which("pgrep")
    if pgrep is None:
        return True  # unknown is not idle
    try:
        found = subprocess.run(
            [pgrep, "-f", name], capture_output=True, check=False, shell=False
        )
    except OSError:
        return True
    return found.returncode != 1


def _production_healthy() -> bool:
    url = os.environ.get("KG_COMPUTE_HEALTH_URL") or HEALTH_URL_DEFAULT
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
            return response.status == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _runtime_ready() -> bool:
    try:
        done = subprocess.run(
            [_runtime(), "info"],
            capture_output=True,
            check=False,
            shell=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def _runner_verified(registry: dict[str, Any]) -> tuple[bool, float]:
    provenance = registry["runner_image_provenance"]
    started = time.monotonic()
    try:
        done = subprocess.run(
            [
                _runtime(),
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}",
                provenance["source"],
            ],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=30,
        )
        digests = json.loads(done.stdout) if done.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        digests = []
    elapsed = round(time.monotonic() - started, 3)
    pinned = "@" + provenance["digest"]
    ok = isinstance(digests, list) and any(
        isinstance(item, str) and item.endswith(pinned) for item in digests
    )
    return ok, elapsed


def _registry() -> dict[str, Any]:
    try:
        return load_profile_registry(REGISTRY_PATH)
    except ContractError as error:
        raise LauncherError("registry-invalid") from error


def _admission(identity: dict[str, str], healthy: bool) -> bool:
    policy = {
        "host_role": identity["host_role"],
        "host_id": identity["host_id"],
        "health": {
            "healthy": healthy,
            "deploy_lock": Path(
                os.environ.get("KG_COMPUTE_DEPLOY_LOCK") or DEPLOY_LOCK_DEFAULT
            ).exists(),
            "backup_active": _process_running(BUSY_PROCESSES[0]),
            "reconcile_active": _process_running(BUSY_PROCESSES[1]),
        },
        "sandbox": dict(SANDBOX_POLICY)
        if _runtime_ready()
        else {"network": "unavailable"},
    }
    try:
        admit(policy)
    except AdmissionError:
        return False
    return True


def probe(fields: dict[str, str]) -> dict[str, Any]:
    identity = _felix_identity()
    registry = _registry()
    lifecycle = _gc()
    del lifecycle
    healthy = _production_healthy()
    admitted = _admission(identity, healthy)
    verified, warmup = _runner_verified(registry)
    profile = registry["profiles"].get(fields.get("profile", ""))
    return {
        "reachable": True,
        "host_id": identity["host_id"],
        "host_role": "felix",
        "admitted": admitted,
        "runner_verified": verified,
        "runner_image_digest": registry["runner_image_provenance"]["digest"]
        if verified
        else None,
        "sandbox_ok": admitted and profile is not None,
        "sandbox_policy": profile["sandbox_policy"] if profile is not None else None,
        "production_healthy": healthy,
        "warmup_seconds": warmup,
        "transfer_seconds": None,  # not measurable Felix-side; Oscar owns that estimate
    }


# --------------------------------------------------------------- job lifecycle


def _ttl() -> int:
    try:
        return int(os.environ.get("KG_COMPUTE_JOB_TTL", JOB_TTL_DEFAULT))
    except ValueError:
        return JOB_TTL_DEFAULT


def _discard(path: Path) -> None:
    if not path.exists():
        return
    for item in (path, *path.rglob("*")):
        with contextlib.suppress(OSError):
            item.chmod(item.stat().st_mode | stat.S_IRWXU)
    shutil.rmtree(path, ignore_errors=True)


def _jobs_dir() -> Path:
    return _private_dir(_private_dir(_state_dir()) / "jobs")


def _gc() -> JobLifecycle:
    lifecycle = JobLifecycle(_state_dir() / "lifecycle.json", ttl_seconds=_ttl())
    _private_dir(_state_dir())
    for job_id in lifecycle.reap(now=int(time.time())):
        _discard(_jobs_dir() / job_id)
    for entry in _jobs_dir().iterdir():
        try:
            lifecycle.get(entry.name)
        except LifecycleError:
            _discard(entry)
    return lifecycle


def _atomic_text(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# ---------------------------------------------------------------- source capsule


def _tree_digest(root: Path) -> str:
    """Same bytes as ``lib.compute_capsule._digest`` without holding the tree in memory."""

    relatives = sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )
    digest = hashlib.sha256()
    for relative in relatives:
        encoded = relative.encode("utf-8")
        data = (root / relative).read_bytes()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _extract(stream: BinaryIO, destination: Path) -> None:
    """Materialize a gzip tar of regular files only; refuse anything else."""

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    total = 0
    try:
        archive = tarfile.open(fileobj=stream, mode="r|gz")
        for member in archive:
            parts = Path(member.name).parts
            if (
                not member.isreg()
                or not parts
                or member.name.startswith("/")
                or any(part in {"", ".", ".."} for part in parts)
                or member.size > MAX_FILE_BYTES
            ):
                raise LauncherError("capsule-invalid")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise LauncherError("capsule-too-large")
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = archive.extractfile(member)
            if source is None:
                raise LauncherError("capsule-invalid")
            with source, target.open("xb") as out:
                shutil.copyfileobj(source, out)
    except (tarfile.TarError, EOFError, OSError, FileExistsError) as error:
        raise LauncherError("capsule-invalid") from error
    for path in sorted(
        destination.rglob("*"), key=lambda p: len(p.parts), reverse=True
    ):
        path.chmod(0o444 if path.is_file() else 0o555)
    destination.chmod(0o555)


# --------------------------------------------------------------------- execute


def _run_container(
    spec: dict[str, Any], capsule: Path, registry: dict[str, Any], job_id: str
) -> tuple[int, str]:
    name = f"kg-compute-{job_id}"
    argv = [
        _runtime(),
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "2g",
        "--tmpfs",
        "/tmp:rw,nosuid,size=256m",
        "--mount",
        f"type=bind,src={capsule},dst=/work,readonly",
        "--workdir",
        "/work",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        registry["runner_image_provenance"]["source"],
        *spec["argv"],
    ]
    environment = {
        k: v for k, v in os.environ.items() if k != "KG_FELIX_RECEIPT_KEY_FILE"
    }
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            shell=False,
            stdin=subprocess.DEVNULL,
            env=environment,
            timeout=spec["timeout_seconds"],
        )
        code, raw = int(done.returncode), done.stdout + done.stderr
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [_runtime(), "rm", "-f", name],
                capture_output=True,
                check=False,
                shell=False,
                timeout=30,
            )
        code = 124
        raw = (error.stdout or b"") + (error.stderr or b"") + b"\nexecution timed out\n"
    except OSError as error:
        raise LauncherError("runtime-unavailable") from error
    log = raw.decode("utf-8", errors="replace")
    if len(log) > LOG_LIMIT:
        log = log[:LOG_LIMIT] + "\n[truncated]\n"
    return code, log


def submit(
    job_id: str, fields: dict[str, str], params: dict[str, str], stream: BinaryIO
) -> dict[str, Any]:
    identity = _felix_identity()
    signer = _load_signer()  # no key, no child: never run what cannot be attested
    for name in (
        "nonce",
        "request-digest",
        "commit",
        "tree-digest",
        "profile",
        "spec-digest",
    ):
        if name not in fields:
            raise LauncherError("field-missing")
    registry = _registry()
    profile = fields["profile"]
    if profile not in registry["profiles"]:
        raise LauncherError("profile-unknown")
    try:
        resolved = resolve_profile(profile, params, registry_path=REGISTRY_PATH)
    except ContractError as error:
        raise LauncherError("profile-params") from error
    if resolved["spec_digest"] != fields["spec-digest"]:
        raise LauncherError("spec-digest-mismatch")
    expected_request = xt.request_digest(
        job_id=job_id,
        nonce=fields["nonce"],
        profile=profile,
        spec_digest=resolved["spec_digest"],
        commit=fields["commit"],
        tree_digest=fields["tree-digest"],
    )
    if expected_request != fields["request-digest"]:
        raise LauncherError("request-digest-mismatch")
    verified, _ = _runner_verified(registry)
    if not verified or not _admission(identity, _production_healthy()):
        raise LauncherError("not-admitted")
    spec = resolved["spec"]
    lifecycle = _gc()
    jobs = _jobs_dir()
    with (jobs.parent / "exec.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LauncherError("host-busy") from error
        try:
            lifecycle.stage(job_id)
        except LifecycleError as error:
            raise LauncherError("job-duplicate") from error
        lifecycle.transition(job_id, "running")
        job_dir = jobs / job_id
        try:
            job_dir.mkdir(mode=0o700)
            capsule = job_dir / "capsule"
            _extract(stream, capsule)
            if _tree_digest(capsule) != fields["tree-digest"]:
                raise LauncherError("tree-digest-mismatch")
            returncode, log = _run_container(spec, capsule, registry, job_id)
            body = {
                "schema": xt.RECEIPT_SCHEMA,
                "job_id": job_id,
                "nonce": fields["nonce"],
                "request_digest": fields["request-digest"],
                "profile": profile,
                "spec_digest": resolved["spec_digest"],
                "runner_image_digest": spec["runner_image_digest"],
                "source": {
                    "commit_sha": fields["commit"],
                    "tree_sha256": fields["tree-digest"],
                },
                "host": identity,
                "issued_at": time.time(),
                "returncode": returncode,
                "log_digest": hashlib.sha256(log.encode()).hexdigest(),
                "artifact_digests": {},
            }
            receipt = signer.sign(body)
            _atomic_text(job_dir / "log.txt", log)
            _atomic_text(job_dir / "receipt.json", json.dumps(receipt, sort_keys=True))
            lifecycle.transition(job_id, "terminal")
        except BaseException:
            with contextlib.suppress(LifecycleError):
                lifecycle.transition(job_id, "failed")
            _discard(job_dir)
            raise
    return {"job_id": job_id, "state": "terminal"}


def _job(lifecycle: JobLifecycle, job_id: str) -> tuple[dict[str, Any], Path]:
    try:
        record = lifecycle.get(job_id)
    except LifecycleError as error:
        raise LauncherError("job-unknown") from error
    return record, _jobs_dir() / job_id


def fetch(job_id: str) -> dict[str, Any]:
    _felix_identity()
    lifecycle = _gc()
    record, job_dir = _job(lifecycle, job_id)
    state = record["state"]
    if state == "acked":
        raise LauncherError("job-acked")
    if state not in {"terminal", "fetched"}:
        raise LauncherError("job-state")
    try:
        receipt = json.loads((job_dir / "receipt.json").read_text(encoding="utf-8"))
        log = (job_dir / "log.txt").read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError("job-unknown") from error
    if state == "terminal":
        lifecycle.transition(job_id, "fetched")
    return {"receipt": receipt, "log": log}


def ack(job_id: str, fields: dict[str, str]) -> dict[str, Any]:
    _felix_identity()
    for name in ("ack-token", "ack-mac", "receipt-digest"):
        if name not in fields:
            raise LauncherError("field-missing")
    lifecycle = _gc()
    record, job_dir = _job(lifecycle, job_id)
    if record["state"] == "acked":
        raise LauncherError("ack-replay")
    if record["state"] != "fetched":
        raise LauncherError("ack-order")
    try:
        stored = json.loads((job_dir / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError("job-unknown") from error
    if stored.get("receipt_digest") != fields["receipt-digest"]:
        raise LauncherError("ack-digest-mismatch")
    lifecycle.transition(job_id, "acked")
    _discard(job_dir)
    return {
        "cleanup": "acked",
        "ack": {
            "token": fields["ack-token"],
            "job_id": job_id,
            "receipt_digest": fields["receipt-digest"],
            "mac": fields["ack-mac"],
        },
    }


# ------------------------------------------------------------------ exec mode


def _execute(stream: BinaryIO) -> dict[str, Any]:
    _felix_identity()
    line = stream.readline(HEADER_LIMIT + 1)
    if not line or len(line) > HEADER_LIMIT:
        raise LauncherError("request-invalid")
    try:
        header = json.loads(line)
    except json.JSONDecodeError as error:
        raise LauncherError("request-invalid") from error
    if not isinstance(header, dict) or set(header) != {
        "verb",
        "job_id",
        "fields",
        "params",
    }:
        raise LauncherError("request-invalid")
    verb, job_id = header["verb"], header["job_id"]
    fields, params = header["fields"], header["params"]
    if (
        not isinstance(fields, dict)
        or not isinstance(params, dict)
        or "capsule" in fields
    ):
        raise LauncherError("request-invalid")
    _validate(verb, job_id, fields, params)
    if verb == "probe":
        return probe(fields)
    if verb == "submit":
        return submit(job_id, fields, params, stream)
    if verb == "fetch":
        return fetch(job_id)
    return ack(job_id, fields)


def _validate(
    verb: Any, job_id: Any, fields: dict[str, str], params: dict[str, str]
) -> None:
    try:
        xt.build_argv(verb, job_id=job_id, fields=fields, params=params)
    except xt.TransportError as error:
        raise LauncherError(error.code) from error


# ----------------------------------------------------------------- relay mode


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: D401
        raise LauncherError("usage")


def _parse(verb: str, argv: list[str]) -> tuple[str, dict[str, str], dict[str, str]]:
    parser = _Parser(add_help=False, exit_on_error=False)
    parser.add_argument("--job-id", required=True)
    for name in xt._FIELDS:
        parser.add_argument(f"--{name}")
    parser.add_argument("--param", action="append", nargs=2, default=[])
    args = parser.parse_args(argv)
    fields = {
        name: getattr(args, name.replace("-", "_"))
        for name in xt._FIELDS
        if getattr(args, name.replace("-", "_")) is not None
    }
    params: dict[str, str] = {}
    for key, value in args.param:
        if key in params:
            raise LauncherError("param")
        params[key] = value
    _validate(verb, args.job_id, fields, params)
    return args.job_id, fields, params


def _pack_capsule(root: Path, sink: BinaryIO) -> None:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise LauncherError("capsule-invalid")
    entries: list[str] = []
    for current, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(current) / name
            if path.is_symlink():
                raise LauncherError("capsule-invalid")
        for name in names:
            path = Path(current) / name
            if not path.is_file():
                raise LauncherError("capsule-invalid")
            entries.append(path.relative_to(root).as_posix())
    if not entries:
        raise LauncherError("capsule-invalid")
    with tarfile.open(fileobj=sink, mode="w:gz") as archive:
        for relative in sorted(entries):
            path = root / relative
            info = tarfile.TarInfo(relative)
            info.size = path.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            with path.open("rb") as handle:
                archive.addfile(info, handle)


def _relay(
    verb: str, job_id: str, fields: dict[str, str], params: dict[str, str]
) -> dict[str, Any]:
    if host_role(_node()) == "felix":
        raise LauncherError("same-host")
    capsule = fields.pop("capsule", None)
    header = {"verb": verb, "job_id": job_id, "fields": fields, "params": params}
    ssh = os.environ.get("KG_COMPUTE_SSH") or SSH_BIN_DEFAULT
    argv = [
        ssh,
        "-T",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "BatchMode=yes",
        "-o",
        "ControlMaster=auto",
        "-o",
        f"ControlPath={Path.home()}/.ssh/cm-%r@%h:%p",
        "-o",
        "ControlPersist=30m",
        SSH_TARGET,
        REMOTE_COMMAND,
    ]
    with tempfile.TemporaryFile() as request:
        request.write(json.dumps(header, sort_keys=True).encode() + b"\n")
        if verb == "submit":
            if capsule is None:
                raise LauncherError("capsule-invalid")
            _pack_capsule(Path(capsule), request)
        request.seek(0)
        try:
            done = subprocess.run(
                argv,
                stdin=request,
                capture_output=True,
                check=False,
                shell=False,
                timeout=RELAY_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LauncherError("transport-unreachable") from error
    try:
        payload = json.loads(done.stdout)
    except (TypeError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        raise LauncherError(
            "transport-unreachable" if done.returncode == 255 else "launcher-output"
        )
    if done.returncode != 0:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        raise LauncherError(code if isinstance(code, str) else "launcher-output")
    return payload


# ------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        verb = arguments[0] if arguments else ""
        if verb in VERBS:
            job_id, fields, params = _parse(verb, arguments[1:])
            payload = _relay(verb, job_id, fields, params)
        elif verb == "exec":
            payload = _execute(sys.stdin.buffer)
        elif verb == "keygen":
            payload = keygen()
        else:
            raise LauncherError("usage")
    except LauncherError as error:
        print(json.dumps({"error": {"code": error.code}}))
        print(f"felix-launcher: {error.code}", file=sys.stderr)
        return 2
    except Exception:  # never leak internals (paths, tracebacks) over the wire
        print(json.dumps({"error": {"code": "internal"}}))
        print("felix-launcher: internal", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
