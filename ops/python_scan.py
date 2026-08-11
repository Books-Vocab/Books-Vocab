#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Find duplicate module-level Python definitions without third-party dependencies."""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    name: str
    count: int
    last_line: int
    kind: str = "duplicate"


def _decorator_function(node: ast.expr) -> ast.expr:
    while isinstance(node, ast.Call):
        node = node.func
    return node


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        decorator = _decorator_function(decorator)
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "overload":
            return True
    return False


def _has_allow_marker(source_lines: list[str], line: int) -> bool:
    marker = "# dup-allow:"
    if not 1 <= line <= len(source_lines):
        return False
    comment = source_lines[line - 1].partition(marker)
    return bool(comment[1] and comment[2].strip())


def _duplicate_findings(path: Path, source: str) -> list[Finding]:
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    definitions: dict[str, list[int]] = defaultdict(list)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            _is_overload(node) or _has_allow_marker(lines, node.lineno)
        ):
            continue
        definitions[node.name].append(node.lineno)

    findings: list[Finding] = []
    for name, locations in definitions.items():
        if len(locations) < 2:
            continue
        for line in locations:
            findings.append(Finding(path, line, name, len(locations), locations[-1]))
    return findings


def _repo_root() -> Path:
    script_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "-C", str(script_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def _git_python_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git file inventory failed")
    files: list[Path] = []
    for rel in sorted(set(result.stdout.splitlines())):
        if not rel:
            continue
        path = root / rel
        # `git ls-files` retains deleted index entries; the scanner's default
        # mode must describe the current tree, not report a phantom read error.
        if path.is_file():
            files.append(path)
    return files


def _explicit_files(root: Path, values: list[str]) -> list[Path]:
    files: set[Path] = set()
    for value in values:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if path.is_dir():
            files.update(item for item in path.rglob("*.py") if item.is_file())
        elif path.is_file() and path.suffix == ".py":
            files.add(path)
        else:
            raise FileNotFoundError(path)
    return sorted(files)


def scan(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            source = path.read_text(encoding="utf-8")
            findings.extend(_duplicate_findings(path, source))
        except SyntaxError as exc:
            line = exc.lineno or 1
            print(f"{path}:{line}: unparsable ({exc.msg})", file=sys.stderr)
            findings.append(Finding(path, line, "<syntax>", 1, line, kind="syntax"))
        except OSError as exc:
            print(f"{path}:1: unable to read: {exc}", file=sys.stderr)
            findings.append(Finding(path, 1, "<read>", 1, 1, kind="syntax"))
    return sorted(findings, key=lambda finding: (str(finding.path), finding.line, finding.name))


def _self_probe() -> bool:
    source = "def _python_scan_probe():\n    pass\n\ndef _python_scan_probe():\n    pass\n"
    return len(_duplicate_findings(Path("<probe>"), source)) == 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Usage: ops/python_scan.py [--help] [<path>...]",
    )
    parser.add_argument("paths", nargs="*", help="Python files or directories; default scans tracked files")
    args = parser.parse_args(argv)
    default_mode = not args.paths
    try:
        root = _repo_root()
        paths = _explicit_files(root, args.paths) if args.paths else _git_python_files(root)
        if default_mode:
            if not _self_probe():
                print("python_scan: self-probe failed; refusing to trust the tree", file=sys.stderr)
                return 1
            if len(paths) < 50:
                print(
                    f"python_scan: default scan saw {len(paths)} Python files; refusing green below 50",
                    file=sys.stderr,
                )
                return 1
        findings = scan(paths)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"python_scan: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        if finding.kind == "syntax":
            continue
        print(
            f"{finding.path}:{finding.line}: duplicate top-level definition '{finding.name}' "
            f"({finding.count} definitions in this file; Python keeps line {finding.last_line})"
        )
    if not findings:
        print(f"python_scan: passed: {len(paths)} file(s), duplicate definitions: 0")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
