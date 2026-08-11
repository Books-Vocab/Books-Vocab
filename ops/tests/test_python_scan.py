from __future__ import annotations

import subprocess
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "ops/python_scan.py"


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCANNER), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_duplicate_function_definitions_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "dup.py"
    source.write_text(
        "def helper():\n"
        "    return 1\n"
        "\n\n"
        "def helper():\n"
        "    return 2\n",
        encoding="utf-8",
    )

    assert SCANNER.is_file() and SCANNER.stat().st_mode & 0o111, (
        "ops/python_scan.py must exist and be executable"
    )
    result = _run(source)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "dup.py:1:" in output
    assert "dup.py:5:" in output
    assert "helper" in output


def test_clean_file_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "clean.py"
    source.write_text(
        "def helper():\n"
        "    return 1\n\n\n"
        "def other():\n"
        "    return 2\n",
        encoding="utf-8",
    )

    assert SCANNER.is_file() and SCANNER.stat().st_mode & 0o111, (
        "ops/python_scan.py must exist and be executable"
    )
    result = _run(source)
    assert result.returncode == 0


def test_allow_comment_and_overload_are_exempt(tmp_path: Path) -> None:
    source = tmp_path / "allowed.py"
    source.write_text(
        "from typing import overload\n"
        "\n"
        "@overload\n"
        "def overloaded(value: int) -> int: ...\n"
        "\n"
        "@overload\n"
        "def overloaded(value: str) -> str: ...\n"
        "\n"
        "def helper():\n"
        "    return 1\n"
        "\n"
        "def helper():  # dup-allow: compatibility shim\n"
        "    return 2\n",
        encoding="utf-8",
    )
    result = _run(source)
    assert result.returncode == 0, result.stdout + result.stderr


def test_only_module_level_definitions_are_checked(tmp_path: Path) -> None:
    source = tmp_path / "nested.py"
    source.write_text(
        "class Box:\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "    def value(self):\n"
        "        return 2\n",
        encoding="utf-8",
    )
    result = _run(source)
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_scan_refuses_a_tiny_git_tree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "ops").mkdir(parents=True)
    scanner = root / "ops" / "python_scan.py"
    shutil.copy2(SCANNER, scanner)
    scanner.chmod(scanner.stat().st_mode | 0o111)
    (root / "ops" / "only.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    result = subprocess.run(
        [str(scanner)], cwd=root, text=True, capture_output=True, check=False
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "below 50" in output


def test_default_scan_ignores_deleted_index_entries(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "ops").mkdir(parents=True)
    scanner = root / "ops" / "python_scan.py"
    shutil.copy2(SCANNER, scanner)
    scanner.chmod(scanner.stat().st_mode | 0o111)
    for index in range(50):
        name = "deleted.py" if index == 0 else f"fixture_{index:02d}.py"
        (root / "ops" / name).write_text(
            f"value_{index} = {index}\n", encoding="utf-8"
        )
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    (root / "ops" / "deleted.py").unlink()
    result = subprocess.run(
        [str(scanner)], cwd=root, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "duplicate definitions: 0" in result.stdout


def test_help_mentions_usage(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(SCANNER), "--help"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
