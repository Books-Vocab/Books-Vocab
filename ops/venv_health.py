#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""KG backend .venv health checker — catches shebang drift and version mismatch.

Run from repo root:
    uv run --no-project --python 3.13 ops/venv_health.py

Exit 0 = all healthy, exit 1 = issues found.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _out(msg: str) -> None:
    print(f"  ✅ {msg}")


def _err(msg: str) -> None:
    print(f"  ❌ {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def check_venv(venv_dir: Path, label: str) -> int:
    """Return error count."""
    errors = 0
    print(f"\n🔍 {label}: {venv_dir}")

    if not venv_dir.is_dir():
        _err("venv directory does not exist")
        return 1

    py_exe = venv_dir / "bin" / "python"
    if not py_exe.is_file():
        _err("python executable missing")
        return 1

    # 1. Python version
    try:
        ver_out = subprocess.run(
            [str(py_exe), "--version"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if "3.13" in ver_out:
            _out(f"Python {ver_out}")
        else:
            _warn(f"Python {ver_out} (expected 3.13.x)")
            errors += 1
    except (OSError, subprocess.SubprocessError) as e:
        _err(f"cannot run python: {e}")
        errors += 1

    # 2. pytest console script shebang
    pytest_script = venv_dir / "bin" / "pytest"
    if not pytest_script.is_file():
        _err("pytest script missing")
        errors += 1
    else:
        try:
            first_line = pytest_script.read_text().splitlines()[0]
        except (IndexError, OSError, UnicodeError) as e:
            _err(f"cannot read pytest script: {e}")
            errors += 1
        else:
            if not first_line.startswith("#!"):
                _err("pytest script has no shebang")
                errors += 1
            else:
                shebang_path = first_line[2:].strip()
                shebang_py = Path(shebang_path)
                if not shebang_py.is_file():
                    _err(f"pytest shebang points to dead path: {shebang_path}")
                    errors += 1
                else:
                    _out(f"pytest shebang valid: {shebang_path}")

        # 3. pytest dependency probe for this exact venv
        try:
            freeze_output = subprocess.run(
                ["uv", "pip", "list", "--python", str(py_exe), "--format=freeze"],
                cwd=venv_dir.parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError) as e:
            _err(f"pytest dependency probe failed: {e}")
            errors += 1
        else:
            pytest_versions = [
                line.split("==", maxsplit=1)[1]
                for line in freeze_output.splitlines()
                if line.startswith("pytest==")
            ]
            if pytest_versions and pytest_versions[0]:
                _out(f"pytest {pytest_versions[0]} (from venv)")
            else:
                _err("pytest dependency missing from uv probe")
                errors += 1

    # 4. uv.lock presence
    uv_lock = venv_dir.parent / "uv.lock"
    if uv_lock.exists():
        _out("uv.lock present")
    else:
        _err("uv.lock missing — run `uv lock`")
        errors += 1

    return errors


def main(*, repo_root: Path | None = None, cwd: Path | None = None) -> int:
    total_errors = 0
    repo_root = repo_root or Path(__file__).resolve().parent.parent

    # Main repo
    main_backend = repo_root / "backend"
    total_errors += check_venv(main_backend / ".venv", "main repo (required)")

    # Claude worktrees
    wt_root = repo_root / ".claude" / "worktrees"
    if wt_root.exists():
        for wt in sorted(wt_root.iterdir()):
            be = wt / "backend"
            if (be / ".venv").exists():
                total_errors += check_venv(be / ".venv", f"worktree {wt.name}")

    # CWD worktree (if different from above)
    cwd = cwd or Path.cwd()
    if cwd != repo_root and (cwd / ".venv").exists():
        total_errors += check_venv(cwd / ".venv", "current directory")

    print(f"\n{'─' * 50}")
    if total_errors == 0:
        print("🎉 All venvs healthy")
        return 0
    else:
        print(f"💥 {total_errors} issue(s) found")
        print("\nRepair: cd backend && uv sync --reinstall")
        return 1


if __name__ == "__main__":
    sys.exit(main())
