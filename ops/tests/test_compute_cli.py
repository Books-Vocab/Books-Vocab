"""Contract tests for the bounded local compute CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import compute


def _write_repo_files(root: Path) -> None:
    (root / "ops").mkdir()
    (root / "ops" / "compute_profiles.yml").write_text(
        json.dumps(
            {
                "schema": "kg.compute_profiles.v1",
                "version": 1,
                "runner_image_provenance": {
                    "source": "local@sha256:" + "0123456789abcdef" * 4,
                    "digest": "sha256:" + "0123456789abcdef" * 4,
                    "provided_capabilities": ["bash", "git", "python-3.13", "uv"],
                },
                "profiles": {
                    "fake.echo": {
                        "command": {"argv": ["printf", "{message}"], "shell": False},
                        "parameters": {
                            "message": {
                                "type": "relative-path",
                                "prefix": "fixtures/",
                                "suffix": ".txt",
                                "max_length": 100,
                            }
                        },
                        "source_kind": "clean-committed-tree",
                        "required_capabilities": ["bash"],
                        "runner_capabilities": ["bash"],
                        "bootstrap": [],
                        "resource_class": "test",
                        "minimum_tier": "observer",
                        "timeout_seconds": 10,
                        "remote_eligible": False,
                        "git_metadata_required": False,
                        "side_effects": ["repo-read"],
                        "network_policy": "none",
                        "sandbox_policy": "repo-readonly",
                        "runner_image_digest": "sha256:" + "0123456789abcdef" * 4,
                        "artifact_contract": "stdout-stderr-only",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_plan_emits_typed_literal_argv_without_execution(monkeypatch, tmp_path, capsys):
    _write_repo_files(tmp_path)
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": True, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})
    monkeypatch.setattr(
        compute.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("plan must not execute a profile"),
    )

    assert (
        compute.main(
            [
                "--repo",
                str(tmp_path),
                "--registry",
                str(tmp_path / "ops" / "compute_profiles.yml"),
                "plan",
                "fake.echo",
                "--param",
                "message=fixtures/hello.txt",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "kg.compute.cli.v1"
    assert payload["result"]["argv"] == ["printf", "fixtures/hello.txt"]
    assert payload["result"]["shell"] is False
    assert payload["result"]["mutation_authority"] is False


def test_run_refuses_dirty_source_before_profile_execution(
    monkeypatch, tmp_path, capsys
):
    _write_repo_files(tmp_path)
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": False, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})
    monkeypatch.setattr(
        compute.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail(
            "dirty source must be refused before execution"
        ),
    )

    assert (
        compute.main(
            [
                "--repo",
                str(tmp_path),
                "--registry",
                str(tmp_path / "ops" / "compute_profiles.yml"),
                "run",
                "fake.echo",
                "--param",
                "message=fixtures/hello.txt",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "dirty-source"


def test_run_passes_literal_argv_and_shell_false(monkeypatch, tmp_path, capsys):
    _write_repo_files(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return compute.subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": True, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})
    monkeypatch.setattr(compute.subprocess, "run", fake_run)

    assert (
        compute.main(
            [
                "--repo",
                str(tmp_path),
                "--registry",
                str(tmp_path / "ops" / "compute_profiles.yml"),
                "run",
                "fake.echo",
                "--param",
                "message=fixtures/hello.txt",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"]["returncode"] == 0
    assert calls[0][0] == ["printf", "fixtures/hello.txt"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_status_reports_registry_and_source_without_running_profile(
    monkeypatch, tmp_path, capsys
):
    _write_repo_files(tmp_path)
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": True, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})

    assert (
        compute.main(
            [
                "--repo",
                str(tmp_path),
                "--registry",
                str(tmp_path / "ops" / "compute_profiles.yml"),
                "status",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"]["profiles"] == ["fake.echo"]
    assert payload["result"]["source_clean"] is True


def test_unknown_profile_and_unsafe_parameter_are_structured_refusals(
    monkeypatch, tmp_path, capsys
):
    _write_repo_files(tmp_path)
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": True, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})

    assert (
        compute.main(
            [
                "--repo",
                str(tmp_path),
                "--registry",
                str(tmp_path / "ops" / "compute_profiles.yml"),
                "plan",
                "missing.profile",
            ]
        )
        == 2
    )
    unknown = json.loads(capsys.readouterr().out)
    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "unknown-profile"

    assert (
        compute.main(
            [
                "--repo",
                str(tmp_path),
                "--registry",
                str(tmp_path / "ops" / "compute_profiles.yml"),
                "plan",
                "fake.echo",
                "--param",
                "message=fixtures/../escape.txt",
            ]
        )
        == 2
    )
    unsafe = json.loads(capsys.readouterr().out)
    assert unsafe["ok"] is False
    assert unsafe["error"]["code"] == "path-traversal"


# --------------------------------------------------------------------------
# Issue #1010: local/auto/felix routing, fixed transport, Oscar verification.
# --------------------------------------------------------------------------
import base64  # noqa: E402
import hashlib  # noqa: E402
import subprocess  # noqa: E402

from lib import xmachine_transport as xt  # noqa: E402
from lib.compute_receipt import ReceiptSigner  # noqa: E402

RUNNER = "sha256:" + "0123456789abcdef" * 4


def _remote_registry(tmp_path: Path, *, signer: ReceiptSigner | None) -> Path:
    _write_repo_files(tmp_path)
    path = tmp_path / "ops" / "compute_profiles.yml"
    registry = json.loads(path.read_text())
    registry["profiles"]["fake.echo"]["remote_eligible"] = True
    registry["profiles"]["fake.echo"]["resource_class"] = "compute-remote"
    if signer is not None:
        registry["felix_receipt_public_key"] = base64.b64encode(
            signer.public_bytes()
        ).decode()
    path.write_text(json.dumps(registry))
    return path


def _cmd(tmp_path: Path, registry: Path, command: str, *extra: str) -> list[str]:
    return [
        "--repo",
        str(tmp_path),
        "--registry",
        str(registry),
        command,
        "fake.echo",
        "--param",
        "message=fixtures/hello.txt",
        *extra,
    ]


def _felix_probe(**over):
    probe = {
        "reachable": True,
        "observed_at": 1000.0,
        "host_id": "felix-host",
        "host_role": "felix",
        "admitted": True,
        "runner_verified": True,
        "runner_image_digest": RUNNER,
        "sandbox_ok": True,
        "sandbox_policy": "repo-readonly",
        "production_healthy": True,
        "warmup_seconds": 1.0,
        "transfer_seconds": 1.0,
    }
    probe.update(over)
    return probe


@pytest.fixture()
def routed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": True, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})
    monkeypatch.setattr(compute, "_now", lambda: 1000.0)
    monkeypatch.setattr(
        compute,
        "_local_load",
        lambda: {"busy": True, "slowdown": 4.0, "host_id": "oscar-host"},
    )
    monkeypatch.setattr(compute, "_gate_history", lambda profile, cache: [100.0, 110.0])
    monkeypatch.setattr(compute.platform, "node", lambda: "oscar-host")
    return tmp_path


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def test_default_mode_local_never_probes_remote(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(
        compute, "_probe_felix", lambda *a, **k: pytest.fail("local must not probe")
    )
    assert compute.main(_cmd(routed, registry, "plan")) == 0
    assert _out(capsys)["result"]["route"]["reason_code"] == "local-requested"


def test_auto_on_ineligible_profile_never_probes_remote(routed, monkeypatch, capsys):
    _write_repo_files(routed)
    monkeypatch.setattr(
        compute, "_probe_felix", lambda *a, **k: pytest.fail("ineligible: no probe")
    )
    registry = routed / "ops" / "compute_profiles.yml"
    assert compute.main(_cmd(routed, registry, "plan", "--mode", "auto")) == 0
    route = _out(capsys)["result"]["route"]
    assert route["selected"] == "local"
    assert route["reason_code"] == "auto-local-no-live-admission"


def test_explicit_felix_cannot_bypass_ineligible_profile(routed, monkeypatch, capsys):
    _write_repo_files(routed)
    monkeypatch.setattr(
        compute.subprocess, "run", lambda *a, **k: pytest.fail("no local run")
    )
    registry = routed / "ops" / "compute_profiles.yml"
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 2
    assert _out(capsys)["error"]["code"].startswith("felix-refused-")


def test_auto_unknown_probe_fails_closed_to_local_and_runs_locally(
    routed, monkeypatch, capsys
):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(
        compute.subprocess,
        "run",
        lambda argv, **kw: (
            calls.append((argv, kw)) or subprocess.CompletedProcess(argv, 0, "hi", "")
        ),
    )
    assert compute.main(_cmd(routed, registry, "run", "--mode", "auto")) == 0
    payload = _out(capsys)
    assert payload["result"]["route"]["selected"] == "local"
    assert payload["result"]["route"]["reason_code"] == "auto-local-no-live-admission"
    assert calls[0][1]["shell"] is False


@pytest.mark.parametrize(
    ("probe", "reason"),
    (
        (None, "no-live-admission"),
        ({"observed_at": 900.0}, "probe-stale"),
        ({"observed_at": 2000.0}, "probe-stale"),
        ({"host_id": "oscar-host"}, "same-host"),
        ({"host_role": "oscar"}, "no-live-admission"),
        ({"admitted": False}, "no-live-admission"),
        ({"production_healthy": False}, "production-unhealthy"),
        ({"runner_image_digest": "sha256:" + "f" * 64}, "runner-unverified"),
        ({"runner_verified": False}, "runner-unverified"),
        ({"sandbox_policy": "other"}, "sandbox-unverified"),
        ({"sandbox_ok": False}, "sandbox-unverified"),
    ),
)
def test_explicit_felix_cannot_bypass_probe_safety(
    routed, monkeypatch, capsys, probe, reason
):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    value = None if probe is None else _felix_probe(**probe)
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: value)
    monkeypatch.setattr(
        compute, "_transport", lambda *a, **k: pytest.fail("no remote work")
    )
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 2
    assert _out(capsys)["error"]["code"] == f"felix-refused-{reason}"


def test_explicit_felix_refuses_dirty_source(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": False, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 2
    assert _out(capsys)["error"]["code"] == "felix-refused-dirty-source"


def test_auto_that_falls_back_local_still_requires_clean_source(
    routed, monkeypatch, capsys
):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": False, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: None)
    monkeypatch.setattr(
        compute.subprocess, "run", lambda *a, **k: pytest.fail("dirty must not run")
    )
    assert compute.main(_cmd(routed, registry, "run", "--mode", "auto")) == 2
    assert _out(capsys)["error"]["code"] == "dirty-source"


def test_plan_reports_felix_route_without_running(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    monkeypatch.setattr(
        compute.subprocess, "run", lambda *a, **k: pytest.fail("plan only")
    )
    assert compute.main(_cmd(routed, registry, "plan", "--mode", "auto")) == 0
    route = _out(capsys)["result"]["route"]
    assert route["selected"] == "felix"
    assert route["reason_code"] == "felix-selected-positive-savings"


def test_auto_without_gate_history_stays_local(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(compute, "_gate_history", lambda profile, cache: None)
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    assert compute.main(_cmd(routed, registry, "plan", "--mode", "auto")) == 0
    assert _out(capsys)["result"]["route"]["reason_code"] == "auto-local-cost-unknown"


def test_auto_not_busy_stays_local(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(
        compute,
        "_local_load",
        lambda: {"busy": False, "slowdown": 1.0, "host_id": "oscar-host"},
    )
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    assert compute.main(_cmd(routed, registry, "plan", "--mode", "auto")) == 0
    assert _out(capsys)["result"]["route"]["reason_code"] == "auto-local-local-not-busy"


class _FakeFelix:
    """Launcher stand-in: signs a receipt bound to the submitted request."""

    def __init__(self, signer, *, returncode=0, fail_fetch=False, tamper=None):
        self.signer, self.returncode, self.fail_fetch = signer, returncode, fail_fetch
        self.tamper = tamper
        self.calls, self.submitted = [], None

    def submit(self, job_id, *, fields, params):
        self.calls.append("submit")
        self.submitted = (job_id, fields, params)
        return {"state": "running"}

    def fetch(self, job_id):
        self.calls.append("fetch")
        if self.fail_fetch:
            raise xt.TransportError("launcher-exit", "9")
        _, fields, _ = self.submitted
        log = "remote-out\n"
        body = {
            "schema": xt.RECEIPT_SCHEMA,
            "job_id": job_id,
            "nonce": fields["nonce"],
            "request_digest": fields["request-digest"],
            "profile": fields["profile"],
            "spec_digest": fields["spec-digest"],
            "runner_image_digest": RUNNER,
            "source": {
                "commit_sha": fields["commit"],
                "tree_sha256": fields["tree-digest"],
            },
            "host": {"host_id": "felix-host", "host_role": "felix"},
            "issued_at": 1000.0,
            "returncode": self.returncode,
            "log_digest": hashlib.sha256(log.encode()).hexdigest(),
            "artifact_digests": {},
        }
        if self.tamper:
            body.update(self.tamper)
        return {"receipt": self.signer.sign(body), "log": log}

    def ack(self, job_id, *, fields):
        self.calls.append("ack")
        return {
            "cleanup": "acked",
            "ack": {
                "token": fields["ack-token"],
                "job_id": job_id,
                "receipt_digest": fields["receipt-digest"],
                "mac": fields["ack-mac"],
            },
        }


def _wire_felix(monkeypatch, signer, **kwargs):
    fake = _FakeFelix(signer, **kwargs)
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    monkeypatch.setattr(compute, "_transport", lambda args, job_id: fake)
    monkeypatch.setattr(
        compute,
        "materialize_tracked_capsule",
        lambda repo, commit, dest: type(
            "C",
            (),
            {
                "commit": commit,
                "tree_sha256": "b" * 64,
                "materialized_root": Path(dest),
            },
        )(),
    )
    real_run = subprocess.run

    def guarded(argv, *a, **k):  # openssl signing helper only; never the profile
        if argv[0] != "openssl":
            pytest.fail("felix path must not run the profile locally")
        return real_run(argv, *a, **k)

    monkeypatch.setattr(compute.subprocess, "run", guarded)
    return fake


def test_felix_run_verifies_receipt_and_writes_only_worktree_cache(
    routed, monkeypatch, capsys
):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(routed, signer=signer)
    fake = _wire_felix(monkeypatch, signer)
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 0
    payload = _out(capsys)
    assert payload["ok"] is True
    assert payload["result"]["route"]["selected"] == "felix"
    assert payload["result"]["stdout"] == "remote-out\n"
    assert payload["result"]["cleanup"] == {"state": "acked"}
    assert payload["result"]["verification"] == {
        "signature_verified": True,
        "nonce_verified": True,
        "replay_checked": True,
        "ack_verified": True,
    }
    result_path = Path(payload["result"]["result_path"])
    assert routed / ".cache" / "compute" in result_path.parents
    assert json.loads(result_path.read_text())["ack_verified"] is True
    assert fake.calls == ["submit", "fetch", "ack"]
    # profile parameters travel as typed params, never as argv strings or shell
    assert fake.submitted[2] == {"message": "fixtures/hello.txt"}


def test_felix_output_exposes_no_transport_surface(routed, monkeypatch, capsys):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(routed, signer=signer)
    _wire_felix(monkeypatch, signer)
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 0
    text = json.dumps(_out(capsys))
    for leaked in ("xmachine", "launcher", "ssh", "felix-host", "felix_compute"):
        assert leaked not in text


def test_felix_remote_nonzero_exit_is_reported_not_retried(routed, monkeypatch, capsys):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(routed, signer=signer)
    fake = _wire_felix(monkeypatch, signer, returncode=3)
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 3
    payload = _out(capsys)
    assert payload["ok"] is False
    assert payload["result"]["returncode"] == 3
    assert fake.calls == ["submit", "fetch", "ack"]


@pytest.mark.parametrize(
    ("tamper", "code"),
    (
        ({"nonce": "0" * 32}, "receipt-nonce"),
        ({"request_digest": "0" * 64}, "receipt-request-digest"),
        ({"spec_digest": "0" * 64}, "receipt-spec"),
        ({"issued_at": 1.0}, "receipt-stale"),
        ({"log_digest": "0" * 64}, "receipt-log-digest"),
        ({"host": {"host_id": "oscar-host", "host_role": "felix"}}, "receipt-host"),
    ),
)
def test_unverifiable_receipt_is_never_trusted_or_retried(
    routed, monkeypatch, capsys, tamper, code
):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(routed, signer=signer)
    fake = _wire_felix(monkeypatch, signer, tamper=tamper)
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 2
    payload = _out(capsys)
    assert payload["ok"] is False
    assert payload["result"]["route"]["reason_code"] == "remote-failed-no-local-retry"
    assert payload["result"]["failure_code"] == code
    assert "ack" not in fake.calls
    assert not list((routed / ".cache" / "compute").glob("*/result.json"))


def test_receipt_signed_by_unpinned_key_is_rejected(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    _wire_felix(monkeypatch, ReceiptSigner.generate())
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 2
    assert _out(capsys)["result"]["failure_code"] == "receipt-signature"


def test_felix_failure_after_submit_never_retries_locally(routed, monkeypatch, capsys):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(routed, signer=signer)
    fake = _wire_felix(monkeypatch, signer, fail_fetch=True)
    assert compute.main(_cmd(routed, registry, "run", "--mode", "auto")) == 2
    payload = _out(capsys)
    assert payload["result"]["route"]["reason_code"] == "remote-failed-no-local-retry"
    assert payload["result"]["route"]["local_retry_allowed"] is False
    assert fake.calls == ["submit", "fetch"]


def test_unpinned_receipt_key_blocks_even_explicit_felix(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=None)
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    assert compute.main(_cmd(routed, registry, "run", "--mode", "felix")) == 2
    assert _out(capsys)["error"]["code"] == "felix-refused-receipt-key-unpinned"


@pytest.mark.parametrize(
    "flags",
    [
        ["--host", "x"],
        ["--ssh", "x"],
        ["--ip", "1.2.3.4"],
        ["--argv", "ls"],
        ["--remote-path", "/x"],
        ["--mode", "ssh"],
        ["--shell", "ls"],
        ["--admission-file", "/tmp/x"],
    ],
)
def test_cli_exposes_no_host_path_or_raw_command_surface(routed, flags):
    registry = _remote_registry(routed, signer=None)
    with pytest.raises(SystemExit) as caught:
        compute.main(
            [
                "--repo",
                str(routed),
                "--registry",
                str(registry),
                "plan",
                "fake.echo",
                *flags,
            ]
        )
    assert caught.value.code == 2


def test_status_supports_modes_and_probes_only_when_remote_requested(
    routed, monkeypatch, capsys
):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    for mode, probed in (("auto", True), ("felix", True), ("local", False)):
        argv = ["--repo", str(routed), "--registry", str(registry), "status"]
        assert compute.main([*argv, "--mode", mode]) == 0
        result = _out(capsys)["result"]
        assert result["remote_profiles"] == ["fake.echo"]
        assert (result["felix_available"] is True) is probed
        assert "felix-host" not in json.dumps(result)


def test_entrypoint_shebang_provides_cryptography_for_receipt_verification():
    # Without cryptography the receipt module falls back to a host OpenSSL path
    # that rejects valid Ed25519 receipts, so the documented ./ops/compute.py
    # entry would fail every Felix run with receipt-signature.
    first_line = (
        (Path(__file__).resolve().parents[1] / "compute.py")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert first_line.startswith("#!/usr/bin/env -S uv run")
    # env -S does not unquote on every platform, so the requirement must be a
    # single unquoted token.
    assert "--with cryptography>=48,<49" in first_line
    assert "'" not in first_line and '"' not in first_line
