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
