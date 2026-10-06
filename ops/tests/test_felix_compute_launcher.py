"""End-to-end tests: Oscar transport <-> the real Felix launcher program.

The launcher is executed as a real subprocess (relay mode, then a fake ``ssh``
that runs the same program in exec mode with a pretend Felix node name), so the
argv contract, the stdin protocol, the Ed25519 receipt and the one-time ACK are
all exercised end to end.  No real ssh, docker, network or Felix is touched.
Keys are generated per test run and never leave the temporary directory.
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import compute  # noqa: E402
from lib import xmachine_transport as xt  # noqa: E402
from lib.compute_capsule import CapsuleError, materialize_tracked_capsule  # noqa: E402
from lib.compute_contract import ContractError, load_profile_registry, resolve_profile  # noqa: E402
from lib.compute_hosts import host_role  # noqa: E402
from lib.compute_receipt import OscarAckAuthority, ReceiptSigner  # noqa: E402

pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

LAUNCHER = OPS / "felix_compute_launcher.py"
REGISTRY = OPS / "compute_profiles.yml"
FELIX_NODE = "chenliangyus-MacBook-Air"
PROFILE = "source-identity"
SECRET_MARKER = "BEGIN PRIVATE KEY"


# --------------------------------------------------------------------- fakes


FAKE_DOCKER = """#!{python}
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "inspect"]:
    print(json.dumps(["ghcr.io/astral-sh/uv@" + os.environ["FAKE_DOCKER_DIGEST"]]))
    sys.exit(0)
if args[:1] == ["info"]:
    sys.exit(0)
if args[:1] == ["run"]:
    mount = next(x for x in args if x.startswith("type=bind"))
    src = dict(p.split("=", 1) for p in mount.split(",") if "=" in p)["src"]
    index = next(i for i, x in enumerate(args) if "@sha256:" in x)
    command = args[index + 1 :]
    if command[0] == "python":
        command[0] = sys.executable
    sys.exit(subprocess.run(command, cwd=src).returncode)
if args[:1] in (["rm"], ["kill"]):
    sys.exit(0)
sys.exit(1)
"""

FAKE_SSH = """#!{python}
import json, os, subprocess, sys
with open(os.environ["FAKE_SSH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
env = dict(os.environ, KG_COMPUTE_TEST_NODE=os.environ["FAKE_FELIX_NODE"])
sys.exit(subprocess.run([sys.executable, os.environ["FAKE_LAUNCHER"], "exec"], env=env).returncode)
"""


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"version":"test"}')

    def log_message(self, *args):
        return


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "source"
    (repo / "ops").mkdir(parents=True)
    shutil.copy(OPS / "source_identity.py", repo / "ops" / "source_identity.py")
    (repo / "ops" / "compute_profiles.yml").write_text(REGISTRY.read_text())
    (repo / ".gitignore").write_text(".cache/\n")
    (repo / "README.md").write_text("fixture\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return repo, _git(repo, "rev-parse", "HEAD")


def _write_key(path: Path, mode: int = 0o600) -> ReceiptSigner:
    private = Ed25519PrivateKey.generate()
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(path, mode)
    return ReceiptSigner(None, private.public_key())


class Rig(SimpleNamespace):
    def run(self, argv, env=None):
        return subprocess.run(
            [sys.executable, *argv],
            env=env or self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def runner(self, argv):
        return self.run(argv)

    @property
    def transport(self):
        return xt.XmachineTransport(runner=self.runner, launcher=LAUNCHER)

    def docker_calls(self):
        if not self.docker_log.exists():
            return []
        return [json.loads(line) for line in self.docker_log.read_text().splitlines()]

    def ssh_calls(self):
        if not self.ssh_log.exists():
            return []
        return [json.loads(line) for line in self.ssh_log.read_text().splitlines()]


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("KG_COMPUTE", "KG_FELIX")):
            monkeypatch.delenv(name)
    registry = json.loads(REGISTRY.read_text())
    server = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER.format(python=sys.executable))
    ssh = tmp_path / "ssh"
    ssh.write_text(FAKE_SSH.format(python=sys.executable))
    for tool in (docker, ssh):
        tool.chmod(0o755)
    key_file = tmp_path / "keys" / "receipt.pem"
    key_file.parent.mkdir()
    signer = _write_key(key_file)
    repo, commit = _make_repo(tmp_path)
    state = tmp_path / "felix-state"
    env = dict(os.environ)
    env.update(
        {
            "KG_COMPUTE_STATE_DIR": str(state),
            "KG_FELIX_RECEIPT_KEY_FILE": str(key_file),
            "KG_COMPUTE_RUNTIME": str(docker),
            "KG_COMPUTE_SSH": str(ssh),
            "KG_COMPUTE_HEALTH_URL": f"http://127.0.0.1:{server.server_port}/api/system/info",
            "KG_COMPUTE_DEPLOY_LOCK": str(tmp_path / "no-such-lock"),
            "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
            "FAKE_DOCKER_DIGEST": registry["runner_image_provenance"]["digest"],
            "FAKE_SSH_LOG": str(tmp_path / "ssh.log"),
            "FAKE_FELIX_NODE": FELIX_NODE,
            "FAKE_LAUNCHER": str(LAUNCHER),
        }
    )
    value = Rig(
        env=env,
        tmp=tmp_path,
        repo=repo,
        commit=commit,
        state=state,
        key_file=key_file,
        signer=signer,
        pinned=ReceiptSigner.from_public_bytes(signer.public_bytes()),
        docker_log=tmp_path / "docker.log",
        ssh_log=tmp_path / "ssh.log",
        server=server,
    )
    yield value
    server.shutdown()
    for root, dirs, files in os.walk(tmp_path):
        for name in dirs + files:
            entry = Path(root) / name
            if entry.is_symlink():
                continue
            try:
                os.chmod(entry, 0o755)
            except OSError:
                pass


def _expected(rig, job, nonce, digest, capsule, spec):
    return {
        "job_id": job,
        "nonce": nonce,
        "request_digest": digest,
        "profile": PROFILE,
        "spec_digest": spec["spec_digest"],
        "runner_image_digest": spec["spec"]["runner_image_digest"],
        "commit_sha": capsule.commit,
        "tree_sha256": capsule.tree_sha256,
    }


def _prepare(rig, **override):
    spec = resolve_profile(PROFILE, {}, registry_path=REGISTRY)
    capsule = materialize_tracked_capsule(
        rig.repo,
        rig.commit,
        rig.tmp / f"capsule-{len(list(rig.tmp.glob('capsule-*')))}",
    )
    job, nonce = xt.new_job_id(), xt.new_nonce()
    digest = xt.request_digest(
        job_id=job,
        nonce=nonce,
        profile=PROFILE,
        spec_digest=spec["spec_digest"],
        commit=capsule.commit,
        tree_digest=capsule.tree_sha256,
    )
    fields = {
        "nonce": nonce,
        "request-digest": digest,
        "commit": capsule.commit,
        "tree-digest": capsule.tree_sha256,
        "profile": PROFILE,
        "spec-digest": spec["spec_digest"],
        "capsule": str(capsule.materialized_root),
    }
    fields.update(override)
    return job, fields, _expected(rig, job, nonce, digest, capsule, spec), capsule


def _error_code(completed):
    assert completed.returncode != 0
    return json.loads(completed.stdout)["error"]["code"]


def _raw(rig, verb, job, fields=None, env=None):
    argv = xt.build_argv(verb, job_id=job, fields=fields, launcher=LAUNCHER)
    return rig.run(argv, env=env)


def _no_leaks(rig, *outputs):
    blob = "\n".join(outputs)
    assert SECRET_MARKER not in blob
    assert str(rig.key_file) not in blob
    assert str(rig.state) not in blob
    assert str(rig.tmp) not in blob


# -------------------------------------------------------- registry / profile


def test_shipped_registry_has_closed_source_identity_profile_and_a_valid_pinned_key():
    registry = load_profile_registry(REGISTRY)
    profile = registry["profiles"][PROFILE]
    # Remote eligibility was proven by the live Felix selftest (see #1988).
    assert profile["remote_eligible"] is True
    assert profile["parameters"] == {}
    assert profile["sandbox_policy"] == "repo-readonly"
    # The Felix-held receipt key is pinned through git review: standard base64
    # of exactly one raw 32-byte Ed25519 public key.
    pinned = registry["felix_receipt_public_key"]
    assert len(base64.b64decode(pinned, validate=True)) == 32
    assert resolve_profile(PROFILE, {}, registry_path=REGISTRY)["argv"][0] == "python"
    with pytest.raises(ContractError, match="extra-parameter"):
        resolve_profile(PROFILE, {"x": "y"}, registry_path=REGISTRY)


def test_host_roles_are_a_closed_table():
    assert host_role("MacBook-Air-7.local") == "oscar"
    assert host_role("chenliangyus-MacBook-Air") == "felix"
    assert host_role("chenliangyusAir.local") == "felix"
    assert host_role("some-ci-box") is None
    assert host_role("") is None


# ------------------------------------------------------------- happy path


def test_end_to_end_probe_submit_fetch_accept_ack_cleanup(rig):
    transport = rig.transport
    probe = transport.probe(xt.new_job_id())
    assert set(probe) == set(compute._PROBE_KEYS)
    job, fields, expected, capsule = _prepare(rig)
    submitted = transport.submit(job, fields=fields, params={})
    assert set(submitted) == {"job_id", "state"} and submitted["job_id"] == job
    fetched = transport.fetch(job)
    assert set(fetched) == {"receipt", "log"}
    cache = rig.tmp / "cache"
    result = xt.accept_receipt(
        fetched["receipt"],
        fetched["log"],
        transport=transport,
        signer=rig.pinned,
        authority=OscarAckAuthority(cache / "ledger.json", key=b"k" * 32),
        expected=expected,
        caller_host_id="oscar-test",
        cache_root=cache,
        now=__import__("time").time(),
    )
    assert result["ack_verified"] is True
    assert result["cleanup"] == {"state": "acked"}
    assert result["receipt"]["host"] == {"host_id": FELIX_NODE, "host_role": "felix"}
    assert result["receipt"]["returncode"] == 0
    # the sandbox itself recomputed the tree digest the receipt claims
    assert json.loads(fetched["log"])["tree_sha256"] == capsule.tree_sha256
    # one-time ACK removed every Felix-side artifact
    assert not any((rig.state / "jobs").glob("*"))
    assert transport_error(transport.fetch, job) == "launcher-exit"
    run = next(call for call in rig.docker_calls() if call[0] == "run")
    for flag in ("--network", "--read-only", "--cap-drop", "--security-opt", "--user"):
        assert flag in run
    assert run[run.index("--network") + 1] == "none"
    assert run[run.index("--cap-drop") + 1] == "ALL"
    _no_leaks(rig, fetched["log"], json.dumps(probe), json.dumps(submitted))


def transport_error(call, *args):
    try:
        call(*args)
    except xt.TransportError as error:
        return error.code
    return None


def test_probe_reports_contract_fields_only_and_profile_policy(rig):
    probe = rig.transport._call("probe", xt.new_job_id(), fields={"profile": PROFILE})
    assert set(probe) == set(compute._PROBE_KEYS)
    assert probe["reachable"] is True
    assert probe["host_role"] == "felix" and probe["host_id"] == FELIX_NODE
    assert probe["admitted"] is True and probe["runner_verified"] is True
    assert probe["sandbox_ok"] is True and probe["sandbox_policy"] == "repo-readonly"
    assert probe["production_healthy"] is True
    unknown = rig.transport._call(
        "probe", xt.new_job_id(), fields={"profile": "no.such"}
    )
    assert unknown["sandbox_ok"] is False and unknown["sandbox_policy"] is None


def test_probe_fails_closed_on_deploy_lock_runner_digest_and_health(rig, tmp_path):
    lock = tmp_path / "lock"
    lock.mkdir()
    env = dict(rig.env, KG_COMPUTE_DEPLOY_LOCK=str(lock))
    assert (
        json.loads(_raw(rig, "probe", xt.new_job_id(), env=env).stdout)["admitted"]
        is False
    )
    env = dict(rig.env, FAKE_DOCKER_DIGEST="sha256:" + "9" * 64)
    probe = json.loads(_raw(rig, "probe", xt.new_job_id(), env=env).stdout)
    assert probe["runner_verified"] is False
    rig.server.shutdown()
    rig.server.server_close()
    probe = json.loads(_raw(rig, "probe", xt.new_job_id()).stdout)
    assert probe["production_healthy"] is False


# -------------------------------------------------------- key custody


def test_missing_key_fails_closed_before_any_child_runs(rig):
    rig.key_file.unlink()
    job, fields, *_ = _prepare(rig)
    done = _raw(rig, "submit", job, fields)
    assert _error_code(done) == "receipt-key-missing"
    assert rig.docker_calls() == [] or all(c[0] != "run" for c in rig.docker_calls())
    assert not any((rig.state / "jobs").glob("*"))
    _no_leaks(rig, done.stdout, done.stderr)


def test_key_with_open_permissions_is_refused(rig):
    os.chmod(rig.key_file, 0o644)
    job, fields, *_ = _prepare(rig)
    done = _raw(rig, "submit", job, fields)
    assert _error_code(done) == "receipt-key-permissions"
    assert all(c[0] != "run" for c in rig.docker_calls())
    _no_leaks(rig, done.stdout, done.stderr)


def test_garbage_key_is_refused_without_echoing_it(rig):
    rig.key_file.write_text("not a key -----BEGIN PRIVATE KEY----- nope\n")
    os.chmod(rig.key_file, 0o600)
    job, fields, *_ = _prepare(rig)
    done = _raw(rig, "submit", job, fields)
    assert _error_code(done) == "receipt-key-invalid"
    assert "not a key" not in done.stdout + done.stderr


def test_keygen_creates_0600_key_prints_only_public_and_never_overwrites(rig):
    fresh = rig.tmp / "fresh" / "receipt.pem"
    env = dict(
        rig.env, KG_FELIX_RECEIPT_KEY_FILE=str(fresh), KG_COMPUTE_TEST_NODE=FELIX_NODE
    )
    done = rig.run([str(LAUNCHER), "keygen"], env=env)
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert set(payload) == {"public_key"}
    public = base64.b64decode(payload["public_key"], validate=True)
    assert len(public) == 32
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600
    assert SECRET_MARKER not in done.stdout + done.stderr
    assert str(fresh) not in done.stdout + done.stderr
    again = rig.run([str(LAUNCHER), "keygen"], env=env)
    assert _error_code(again) == "receipt-key-exists"
    # the pinned public key verifies receipts the launcher signs with that key
    rig.env["KG_FELIX_RECEIPT_KEY_FILE"] = str(fresh)
    job, fields, expected, _ = _prepare(rig)
    rig.transport.submit(job, fields=fields, params={})
    receipt = rig.transport.fetch(job)["receipt"]
    assert ReceiptSigner.from_public_bytes(public).verify(receipt)["job_id"] == job


def test_keygen_is_refused_off_felix(rig):
    done = rig.run([str(LAUNCHER), "keygen"])
    assert _error_code(done) == "not-felix"


# ----------------------------------------------------- receipt integrity


def test_tampered_or_foreign_signature_is_rejected_by_oscar(rig):
    transport = rig.transport
    job, fields, expected, _ = _prepare(rig)
    transport.submit(job, fields=fields, params={})
    fetched = transport.fetch(job)
    forged = dict(fetched["receipt"], returncode=0, job_id=expected["job_id"])
    forged["profile"] = "ops.docs-lint-registry"
    with pytest.raises(xt.TransportError) as caught:
        xt.verify_receipt(
            forged,
            fetched["log"],
            signer=rig.pinned,
            expected=expected,
            caller_host_id="oscar-test",
            now=__import__("time").time(),
        )
    assert caught.value.code == "receipt-signature"
    other = ReceiptSigner.from_public_bytes(ReceiptSigner.generate().public_bytes())
    with pytest.raises(xt.TransportError) as caught:
        xt.verify_receipt(
            fetched["receipt"],
            fetched["log"],
            signer=other,
            expected=expected,
            caller_host_id="oscar-test",
            now=__import__("time").time(),
        )
    assert caught.value.code == "receipt-signature"


def test_receipt_replay_is_rejected_by_oscar_ledger(rig):
    transport = rig.transport
    job, fields, expected, _ = _prepare(rig)
    transport.submit(job, fields=fields, params={})
    fetched = transport.fetch(job)
    cache = rig.tmp / "cache"
    kwargs = dict(
        transport=transport,
        signer=rig.pinned,
        authority=OscarAckAuthority(cache / "ledger.json", key=b"k" * 32),
        expected=expected,
        caller_host_id="oscar-test",
        cache_root=cache,
        now=__import__("time").time(),
    )
    xt.accept_receipt(fetched["receipt"], fetched["log"], **kwargs)
    with pytest.raises(xt.TransportError) as caught:
        xt.accept_receipt(fetched["receipt"], fetched["log"], **kwargs)
    assert caught.value.code == "receipt-replay"


# ---------------------------------------------------- request admission


def test_profile_outside_the_closed_registry_is_refused(rig):
    job, fields, *_ = _prepare(rig, profile="backend.nonexistent")
    done = _raw(rig, "submit", job, fields)
    assert _error_code(done) == "profile-unknown"
    assert all(c[0] != "run" for c in rig.docker_calls())


def test_spec_request_and_tree_digest_mismatches_are_refused(rig):
    job, fields, *_ = _prepare(rig, **{"spec-digest": "e" * 64})
    assert _error_code(_raw(rig, "submit", job, fields)) == "spec-digest-mismatch"
    job, fields, *_ = _prepare(rig, **{"request-digest": "f" * 64})
    assert _error_code(_raw(rig, "submit", job, fields)) == "request-digest-mismatch"
    # tree digest claimed by Oscar does not match the bytes that arrived
    spec = resolve_profile(PROFILE, {}, registry_path=REGISTRY)
    job, fields, *_ = _prepare(rig)
    bogus = "d" * 64
    fields["tree-digest"] = bogus
    fields["request-digest"] = xt.request_digest(
        job_id=job,
        nonce=fields["nonce"],
        profile=PROFILE,
        spec_digest=spec["spec_digest"],
        commit=fields["commit"],
        tree_digest=bogus,
    )
    assert _error_code(_raw(rig, "submit", job, fields)) == "tree-digest-mismatch"
    assert all(c[0] != "run" for c in rig.docker_calls())
    assert not any((rig.state / "jobs").glob("*"))


def test_dirty_capsule_with_extra_untracked_file_is_refused(rig):
    job, fields, expected, capsule = _prepare(rig)
    writable = rig.tmp / "dirty-capsule"
    shutil.copytree(capsule.materialized_root, writable)
    for root, dirs, files in os.walk(writable):
        for name in dirs + files:
            os.chmod(Path(root) / name, 0o755)
    os.chmod(writable, 0o755)
    (writable / "untracked-extra.txt").write_text("not in the commit\n")
    fields["capsule"] = str(writable)
    assert _error_code(_raw(rig, "submit", job, fields)) == "tree-digest-mismatch"


def test_dirty_source_repo_never_yields_a_capsule(rig):
    (rig.repo / "README.md").write_text("dirty\n")
    with pytest.raises(CapsuleError):
        materialize_tracked_capsule(rig.repo, rig.commit, rig.tmp / "never")


def test_capsule_with_symlink_is_refused_by_relay(rig):
    job, fields, expected, capsule = _prepare(rig)
    writable = rig.tmp / "link-capsule"
    shutil.copytree(capsule.materialized_root, writable)
    for root, dirs, files in os.walk(writable):
        for name in dirs + files:
            os.chmod(Path(root) / name, 0o755)
    os.chmod(writable, 0o755)
    (writable / "evil").symlink_to("/etc/passwd")
    fields["capsule"] = str(writable)
    done = _raw(rig, "submit", job, fields)
    assert _error_code(done) == "capsule-invalid"
    assert rig.ssh_calls() == []


def test_params_cannot_reach_a_profile_that_declares_none(rig):
    job, fields, *_ = _prepare(rig)
    argv = xt.build_argv(
        "submit",
        job_id=job,
        fields=fields,
        params={"test_path": "x; rm -rf / $(id)"},
        launcher=LAUNCHER,
    )
    done = rig.run(argv)
    assert _error_code(done) == "profile-params"
    assert all(c[0] != "run" for c in rig.docker_calls())


def test_job_id_replay_on_felix_is_refused_even_after_ack(rig):
    transport = rig.transport
    job, fields, expected, _ = _prepare(rig)
    transport.submit(job, fields=fields, params={})
    assert _error_code(_raw(rig, "submit", job, fields)) == "job-duplicate"
    fetched = transport.fetch(job)
    ack = OscarAckAuthority(rig.tmp / "l.json", key=b"k" * 32).issue(
        job, fetched["receipt"]["receipt_digest"]
    )
    transport.ack(
        job,
        fields={
            "ack-token": ack["token"],
            "ack-mac": ack["mac"],
            "receipt-digest": ack["receipt_digest"],
        },
    )
    assert _error_code(_raw(rig, "submit", job, fields)) == "job-duplicate"


# ------------------------------------------------------------- ACK / GC


def _ack_fields(job, digest):
    return {
        "ack-token": "1" * 32,
        "ack-mac": "2" * 64,
        "receipt-digest": digest,
    }


def test_ack_with_wrong_digest_keeps_the_job_and_ack_before_fetch_is_refused(rig):
    transport = rig.transport
    job, fields, *_ = _prepare(rig)
    transport.submit(job, fields=fields, params={})
    early = _raw(rig, "ack", job, _ack_fields(job, "a" * 64))
    assert _error_code(early) == "ack-order"
    receipt = transport.fetch(job)["receipt"]
    wrong = _raw(rig, "ack", job, _ack_fields(job, "a" * 64))
    assert _error_code(wrong) == "ack-digest-mismatch"
    assert (rig.state / "jobs" / job).exists()
    good = _raw(rig, "ack", job, _ack_fields(job, receipt["receipt_digest"]))
    assert good.returncode == 0
    payload = json.loads(good.stdout)
    assert payload["cleanup"] == "acked"
    assert payload["ack"] == {
        "token": "1" * 32,
        "job_id": job,
        "receipt_digest": receipt["receipt_digest"],
        "mac": "2" * 64,
    }
    assert not (rig.state / "jobs" / job).exists()
    again = _raw(rig, "ack", job, _ack_fields(job, receipt["receipt_digest"]))
    assert _error_code(again) in {"ack-replay", "job-acked"}


def test_unknown_job_fetch_is_a_named_refusal(rig):
    assert _error_code(_raw(rig, "fetch", xt.new_job_id())) == "job-unknown"


def test_expired_terminal_jobs_are_reaped_on_next_call(rig):
    transport = rig.transport
    job, fields, *_ = _prepare(rig)
    transport.submit(job, fields=fields, params={})
    assert (rig.state / "jobs" / job).exists()
    env = dict(rig.env, KG_COMPUTE_JOB_TTL="0")
    _raw(rig, "probe", xt.new_job_id(), env=env)
    assert not (rig.state / "jobs" / job).exists()


# ---------------------------------------------------------- boundaries


def test_relay_never_puts_dynamic_values_in_ssh_argv(rig):
    job, fields, *_ = _prepare(rig)
    rig.transport.submit(job, fields=fields, params={})
    calls = rig.ssh_calls()
    assert calls
    flat = json.dumps(calls)
    for value in (job, fields["nonce"], fields["request-digest"], fields["commit"]):
        assert value not in flat
    assert all(isinstance(item, str) for call in calls for item in call)
    assert "BatchMode=yes" in calls[0]


def test_public_verbs_on_the_felix_host_are_refused_as_same_host(rig):
    env = dict(rig.env, KG_COMPUTE_TEST_NODE=FELIX_NODE)
    assert _error_code(_raw(rig, "probe", xt.new_job_id(), env=env)) == "same-host"
    assert rig.ssh_calls() == []


def test_unknown_node_cannot_execute_the_felix_side(rig):
    done = rig.run([str(LAUNCHER), "exec"], env=dict(rig.env))
    assert _error_code(done) == "not-felix"


def test_ssh_failure_is_named_without_leaking_transport_details(rig, tmp_path):
    failing = tmp_path / "ssh-fail"
    failing.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stderr.write('ssh: connect to host 100.1.2.3 port 22: refused')\nsys.exit(255)\n"
    )
    failing.chmod(0o755)
    env = dict(rig.env, KG_COMPUTE_SSH=str(failing))
    done = _raw(rig, "probe", xt.new_job_id(), env=env)
    assert _error_code(done) == "transport-unreachable"
    assert "100.1.2.3" not in done.stdout + done.stderr


# --------------------------------------------------------------- selftest


def _selftest_env(rig, monkeypatch, *, role="oscar", node="oscar-test", pinned=True):
    registry = json.loads(REGISTRY.read_text())
    if pinned:
        registry["felix_receipt_public_key"] = base64.b64encode(
            rig.signer.public_bytes()
        ).decode()
    else:
        registry.pop("felix_receipt_public_key", None)
    path = rig.repo / "ops" / "compute_profiles.yml"
    path.write_text(json.dumps(registry))
    _git(rig.repo, "add", ".")
    _git(
        rig.repo,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "pin",
    )
    monkeypatch.setattr(compute, "_transport", lambda args, job: rig.transport)
    monkeypatch.setattr(
        compute, "_caller_identity", lambda: {"host_id": node, "host_role": role}
    )
    monkeypatch.setattr(compute.platform, "node", lambda: node)
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"python-3.13"})
    return path


def _selftest(rig, capsys, registry):
    code = compute.main(
        [
            "--repo",
            str(rig.repo),
            "--registry",
            str(registry),
            "selftest",
            "--target",
            "felix",
            "--profile",
            PROFILE,
            "--json",
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def test_selftest_green_matches_the_live_acceptance_conditions(
    rig, monkeypatch, capsys
):
    registry = _selftest_env(rig, monkeypatch)
    code, out = _selftest(rig, capsys, registry)
    assert code == 0, out
    assert out["verified"] is True
    assert out["caller"]["host_role"] == "oscar"
    assert out["remote"]["host_role"] == "felix"
    assert out["caller"]["host_id"] != out["remote"]["host_id"]
    assert out["transport"]["kind"] == "xmachine-ssh"
    head = _git(rig.repo, "rev-parse", "HEAD")
    assert out["source"]["commit_sha"] == out["remote"]["source"]["commit_sha"] == head
    assert out["source"]["tree_sha256"] == out["remote"]["source"]["tree_sha256"]
    assert out["receipt"]["verifier"] == "oscar-independent"
    for key in (
        "signature_verified",
        "nonce_verified",
        "replay_checked",
        "ack_verified",
    ):
        assert out["receipt"][key] is True
    assert out["runner"]["verified"] is True
    assert out["production"] == {"before": "healthy", "after": "healthy"}
    assert out["cleanup"]["state"] == "acked"
    assert out["cleanup"]["fetch_after_ack_refused"] is True
    assert not any((rig.state / "jobs").glob("*"))
    assert SECRET_MARKER not in json.dumps(out)
    # selftest is a proof, not a run: it must never feed the auto cost model
    assert not (rig.repo / ".cache" / "compute" / "history.ndjson").exists()


def test_selftest_without_a_reachable_felix_fails_closed_with_named_reason(
    rig, monkeypatch, capsys
):
    registry = _selftest_env(rig, monkeypatch)
    broken = dict(rig.env, KG_COMPUTE_SSH=str(rig.tmp / "no-such-ssh"))
    monkeypatch.setattr(
        compute,
        "_transport",
        lambda args, job: xt.XmachineTransport(
            runner=lambda argv: rig.run(argv, env=broken), launcher=LAUNCHER
        ),
    )
    code, out = _selftest(rig, capsys, registry)
    assert code == 2
    assert out["verified"] is False
    assert out["failure_code"] == "felix-refused-no-live-admission"
    assert rig.docker_calls() == []


def test_selftest_refuses_without_pinned_key(rig, monkeypatch, capsys):
    registry = _selftest_env(rig, monkeypatch, pinned=False)
    code, out = _selftest(rig, capsys, registry)
    assert code == 2 and out["verified"] is False
    assert out["failure_code"] == "felix-refused-receipt-key-unpinned"


def test_selftest_refuses_when_caller_is_not_oscar(rig, monkeypatch, capsys):
    registry = _selftest_env(rig, monkeypatch, role="felix", node=FELIX_NODE)
    code, out = _selftest(rig, capsys, registry)
    assert code == 2 and out["verified"] is False
    assert out["failure_code"] == "selftest-caller-not-oscar"
    assert rig.ssh_calls() == []


def test_selftest_refuses_same_host_identity(rig, monkeypatch, capsys):
    registry = _selftest_env(rig, monkeypatch, node=FELIX_NODE)
    code, out = _selftest(rig, capsys, registry)
    assert code == 2 and out["verified"] is False
    assert out["failure_code"] in {
        "felix-refused-same-host",
        "selftest-caller-not-oscar",
    }


def test_selftest_with_a_foreign_signing_key_is_not_verified(rig, monkeypatch, capsys):
    registry = _selftest_env(rig, monkeypatch)
    _write_key(rig.key_file)  # Felix now signs with a key that is not pinned
    code, out = _selftest(rig, capsys, registry)
    assert code == 2 and out["verified"] is False
    assert out["failure_code"] == "receipt-signature"


def test_selftest_detects_residual_job_after_ack(rig, monkeypatch, capsys):
    registry = _selftest_env(rig, monkeypatch)
    real = rig.transport

    class Residual(xt.XmachineTransport):
        first = None
        acked = False

        def fetch(self, job_id):
            if self.acked:
                return self.first  # Felix still serves the job after the ACK
            self.first = super().fetch(job_id)
            return self.first

        def ack(self, job_id, *, fields):
            outcome = super().ack(job_id, fields=fields)
            self.acked = True
            return outcome

    shared = Residual(runner=real._runner, launcher=LAUNCHER)
    monkeypatch.setattr(compute, "_transport", lambda args, job: shared)
    code, out = _selftest(rig, capsys, registry)
    assert code == 2 and out["verified"] is False


def test_selftest_only_accepts_the_source_identity_profile(rig, monkeypatch, capsys):
    registry = _selftest_env(rig, monkeypatch)
    code = compute.main(
        [
            "--repo",
            str(rig.repo),
            "--registry",
            str(registry),
            "selftest",
            "--target",
            "felix",
            "--profile",
            "ops.docs-lint-registry",
            "--json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["verified"] is False
    assert out["failure_code"] == "selftest-profile"


def test_remote_command_is_a_constant_pointing_at_the_dedicated_checkout() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "felix_compute_launcher_under_test", LAUNCHER
    )
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    command = launcher.REMOTE_COMMAND
    # No dynamic value may ever reach the remote shell.
    assert not any(
        token in command for token in ("$", "{", "}", "`", ";", "&", "|", "<", ">")
    )
    # The signing-key holder runs from a dedicated pinned checkout, never from the
    # production service tree.
    assert "~/kg-compute/ops/felix_compute_launcher.py" in command
    assert "kg-prod" not in command
