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


# ------------------------------------------------------------ target routing

import base64  # noqa: E402
import hashlib  # noqa: E402
import subprocess  # noqa: E402

from lib import xmachine_transport as xt  # noqa: E402
from lib.compute_receipt import ReceiptSigner  # noqa: E402


def _remote_registry(tmp_path: Path, *, signer: ReceiptSigner | None) -> Path:
    _write_repo_files(tmp_path)
    path = tmp_path / "ops" / "compute_profiles.yml"
    registry = json.loads(path.read_text())
    profile = registry["profiles"]["fake.echo"]
    profile["remote_eligible"] = True
    profile["minimum_remote_seconds"] = 30
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
        *extra,
        "fake.echo",
        "--param",
        "message=fixtures/hello.txt",
    ]


def _felix_probe(**over):
    probe = {
        "reachable": True,
        "observed_at": 1000.0,
        "host_id": "felix-host",
        "host_role": "felix",
        "admitted": True,
        "runner_verified": True,
        "sandbox_ok": True,
        "production_healthy": True,
        "receipt_key_pinned": True,
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
    monkeypatch.setattr(compute, "_gate_history", lambda profile: [100.0, 110.0])
    monkeypatch.setattr(compute.platform, "node", lambda: "oscar-host")
    return tmp_path


def test_default_auto_on_local_only_profile_never_probes_remote(
    routed, monkeypatch, capsys
):
    _write_repo_files(routed)
    monkeypatch.setattr(
        compute,
        "_probe_felix",
        lambda *a, **k: pytest.fail("local-only must not probe"),
    )
    registry = routed / "ops" / "compute_profiles.yml"
    assert compute.main(_cmd(routed, registry, "plan")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"]["target"] == "local"
    assert "remote-ineligible" in payload["decision"]["reasons"]


def test_explicit_felix_cannot_bypass_ineligible_profile(routed, monkeypatch, capsys):
    _write_repo_files(routed)
    monkeypatch.setattr(
        compute.subprocess, "run", lambda *a, **k: pytest.fail("no local run")
    )
    registry = routed / "ops" / "compute_profiles.yml"
    assert compute.main(_cmd(routed, registry, "run", "--target", "felix")) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "router-refused"
    assert "remote-ineligible" in payload["error"]["reasons"]


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
    assert compute.main(_cmd(routed, registry, "run")) == 0
    payload = json.loads(capsys.readouterr().out)  # one parseable document
    assert payload["decision"]["target"] == "local"
    assert "probe-unknown" in payload["decision"]["reasons"]
    assert calls[0][1]["shell"] is False
    assert payload["result"]["receipt"]["schema"] == xt.RECEIPT_SCHEMA


def test_plan_reports_felix_decision_without_running(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    monkeypatch.setattr(
        compute.subprocess, "run", lambda *a, **k: pytest.fail("plan only")
    )
    assert compute.main(_cmd(routed, registry, "plan")) == 0
    decision = json.loads(capsys.readouterr().out)["decision"]
    assert decision["target"] == "felix" and decision["reasons"] == [
        "remote-profitable"
    ]


class _FakeFelix:
    """Launcher stand-in: signs a receipt bound to the submitted request."""

    def __init__(self, signer, *, returncode=0, fail_fetch=False):
        self.signer, self.returncode, self.fail_fetch = signer, returncode, fail_fetch
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
        receipt = self.signer.sign(
            {
                "schema": xt.RECEIPT_SCHEMA,
                "job_id": job_id,
                "nonce": fields["nonce"],
                "request_digest": fields["request-digest"],
                "profile": fields["profile"],
                "spec_digest": fields["spec-digest"],
                "runner_image_digest": "sha256:" + "0123456789abcdef" * 4,
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
        )
        return {"receipt": receipt, "log": log}

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

    def guarded(
        argv, *a, **k
    ):  # signing helpers may call openssl; profiles must not run
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
    assert compute.main(_cmd(routed, registry, "run")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"]["target"] == "felix"
    assert payload["result"]["stdout"] == "remote-out\n"
    assert payload["result"]["cleanup"] == {"state": "acked"}
    result_path = Path(payload["result"]["result_path"])
    assert routed / ".cache" / "compute" in result_path.parents
    assert json.loads(result_path.read_text())["ack_verified"] is True
    assert fake.calls == ["submit", "fetch", "ack"]
    # profile parameters travel as typed params, not argv strings or shell
    assert fake.submitted[2] == {"message": "fixtures/hello.txt"}
    local_shape = compute._local_receipt(
        {"profile": "p", "spec_digest": "s", "spec": {"runner_image_digest": "r"}},
        {"head": "h"},
        0,
        "",
    )
    assert set(local_shape) - {"signature"} <= set(payload["result"]["receipt"])


def test_felix_failure_after_submit_never_retries_locally(routed, monkeypatch, capsys):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(routed, signer=signer)
    fake = _wire_felix(monkeypatch, signer, fail_fetch=True)
    assert compute.main(_cmd(routed, registry, "run", "--target", "felix")) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "felix-run"
    assert fake.calls == ["submit", "fetch"]


def test_unpinned_receipt_key_blocks_even_explicit_felix(routed, monkeypatch, capsys):
    registry = _remote_registry(routed, signer=None)
    monkeypatch.setattr(
        compute, "_probe_felix", lambda *a, **k: _felix_probe(receipt_key_pinned=False)
    )
    assert compute.main(_cmd(routed, registry, "run", "--target", "felix")) == 2
    assert (
        "receipt-key-unpinned"
        in json.loads(capsys.readouterr().out)["error"]["reasons"]
    )


@pytest.mark.parametrize(
    "flags",
    [
        ["--host", "x"],
        ["--ssh", "x"],
        ["--ip", "1.2.3.4"],
        ["--argv", "ls"],
        ["--remote-path", "/x"],
        ["--target", "ssh"],
        ["--shell", "ls"],
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
                *flags,
                "fake.echo",
            ]
        )
    assert caught.value.code == 2


def test_status_supports_targets_and_probes_only_for_remote_profiles(
    routed, monkeypatch, capsys
):
    registry = _remote_registry(routed, signer=ReceiptSigner.generate())
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe())
    for target, probed in (("auto", True), ("felix", True), ("local", False)):
        assert (
            compute.main(
                [
                    "--repo",
                    str(routed),
                    "--registry",
                    str(registry),
                    "status",
                    "--target",
                    target,
                ]
            )
            == 0
        )
        result = json.loads(capsys.readouterr().out)["result"]
        assert result["remote_profiles"] == ["fake.echo"]
        assert (result["felix_probe"] is not None) is probed
