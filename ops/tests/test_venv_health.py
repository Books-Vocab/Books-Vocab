from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "venv_health.py"


@pytest.fixture
def health_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("venv_health_under_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def matching_venv(tmp_path: Path) -> Path:
    backend_dir = tmp_path / "backend"
    bin_dir = backend_dir / ".venv" / "bin"
    bin_dir.mkdir(parents=True)

    python = bin_dir / "python"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)

    pytest_script = bin_dir / "pytest"
    pytest_script.write_text(f"#!{python}\n")
    pytest_script.chmod(0o755)

    (backend_dir / "uv.lock").write_text("lock\n")
    return backend_dir / ".venv"


def install_matching_probe(
    monkeypatch: pytest.MonkeyPatch,
    health_module: ModuleType,
    *,
    freeze_output: str = "pytest==8.3.5\n",
) -> None:
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Python 3.13.5\n",
                stderr="",
            )
        if command[:3] == ["uv", "pip", "list"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=freeze_output,
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(health_module.subprocess, "run", fake_run)


def test_missing_required_backend_venv_fails_closed(
    health_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert health_module.main(repo_root=tmp_path, cwd=tmp_path) == 1
    assert "venv directory does not exist" in capsys.readouterr().err


def test_missing_pytest_script_fails_closed(
    health_module: ModuleType,
    matching_venv: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_matching_probe(monkeypatch, health_module)
    (matching_venv / "bin" / "pytest").unlink()

    assert health_module.check_venv(matching_venv, "fixture") == 1
    assert "pytest script missing" in capsys.readouterr().err


def test_dead_pytest_shebang_fails_closed(
    health_module: ModuleType,
    matching_venv: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_matching_probe(monkeypatch, health_module)
    (matching_venv / "bin" / "pytest").write_text(
        f"#!{tmp_path / 'missing-python'}\n"
    )

    assert health_module.check_venv(matching_venv, "fixture") == 1
    assert "pytest shebang points to dead path" in capsys.readouterr().err


def test_failed_dependency_probe_fails_closed(
    health_module: ModuleType,
    matching_venv: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_probe(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Python 3.13.5\n",
                stderr="",
            )
        if command[:3] == ["uv", "pip", "list"]:
            raise subprocess.CalledProcessError(1, command, stderr="probe unavailable")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(health_module.subprocess, "run", failing_probe)

    assert health_module.check_venv(matching_venv, "fixture") == 1
    assert "pytest dependency probe failed" in capsys.readouterr().err


def test_mismatched_dependency_probe_fails_closed(
    health_module: ModuleType,
    matching_venv: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_matching_probe(monkeypatch, health_module, freeze_output="pip==25.0\n")

    assert health_module.check_venv(matching_venv, "fixture") == 1
    assert "pytest dependency missing from uv probe" in capsys.readouterr().err


def test_complete_matching_fixture_remains_healthy(
    health_module: ModuleType,
    matching_venv: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_matching_probe(monkeypatch, health_module)

    assert health_module.check_venv(matching_venv, "fixture") == 0
