#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Static command-chain inventory for ``ops/test_ops.sh`` groups.

The CI exclusion falsifier masks binaries through ``PATH``.  That experiment
cannot say anything about a command invoked by an absolute path, so this small
stdlib-only scanner reports those calls from the selected group's real shell
files, including source/include edges.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GROUP_ARM_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\)(.*)$")
REPO_PATH_RE = re.compile(
    r"(?P<path>ops/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:sh|py)\b)"
)
SOURCE_RE = re.compile(
    r"(?:^|[;&|])\s*(?:source|\.)\s+(?P<target>\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
)
ABSOLUTE_COMMAND_RE = re.compile(
    r"(?P<path>/(?:usr|bin|sbin|opt|Applications|System)/[^\s;&|()]+)"
)
PREFIX_WORDS = {
    "command",
    "do",
    "elif",
    "else",
    "env",
    "exec",
    "if",
    "then",
    "until",
    "while",
}


@dataclass(frozen=True)
class AbsoluteCall:
    group: str
    source: Path
    line: int
    path: str
    command: str


def _strip_shell_comment(line: str) -> str:
    """Remove a shell comment without treating ``#`` in quotes as syntax."""

    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char == "#":
            return line[:index]
    return line


def parse_dispatcher(source: str) -> dict[str, str]:
    """Extract ``run_one``'s group arms without executing the dispatcher."""

    run_one = source.find("run_one()")
    if run_one < 0:
        raise ValueError("ops/test_ops.sh has no run_one()")
    case_start = source.find('case "$1" in', run_one)
    if case_start < 0:
        raise ValueError("run_one() has no case arm")

    arms: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    in_case = False
    for line in source[case_start:].splitlines():
        stripped = line.strip()
        if not in_case:
            in_case = True
            continue
        if stripped == "esac":
            break

        match = GROUP_ARM_RE.match(line)
        if match:
            current = match.group(1)
            body = []
            inline = match.group(2)
            if ";;" in inline:
                body.append(inline.split(";;", 1)[0])
                arms[current] = "\n".join(body)
                current = None
            else:
                body.append(inline)
            continue

        if current is None:
            continue
        if ";;" in line:
            body.append(line.split(";;", 1)[0])
            arms[current] = "\n".join(body)
            current = None
        else:
            body.append(line)

    if current is not None:
        raise ValueError(f"group arm {current!r} has no ;; terminator")
    if not arms:
        raise ValueError("run_one() yielded no group arms")
    return arms


def case_arms() -> dict[str, str]:
    """Return the current dispatcher arms, excluding the ``*`` fallback."""

    return parse_dispatcher((ROOT / "ops/test_ops.sh").read_text())


def _repo_path(root: Path, reference: str, current: Path) -> Path | None:
    reference = reference.strip("\"'")
    if "ops/" in reference:
        return root / reference[reference.index("ops/") :]
    if reference.startswith("$SCRIPT_DIR/"):
        return current.parent / reference.removeprefix("$SCRIPT_DIR/")
    if reference.startswith(("$ROOT/", "$REPO/", "$WORKSPACE/")):
        return root / reference.split("/", 1)[1]
    if reference.startswith(("./", "../")):
        return (current.parent / reference).resolve()
    return None


def _referenced_files(root: Path, current: Path, code: str) -> set[Path]:
    refs: set[Path] = set()
    variables: dict[str, Path] = {}
    for line in code.splitlines():
        clean = _strip_shell_comment(line)
        for assignment in re.finditer(
            r"(?:^|[;&|]\s*|\blocal\s+)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;&|]+)",
            clean,
        ):
            name, value = assignment.groups()
            match = REPO_PATH_RE.search(value)
            if match:
                candidate = root / match.group("path")
                if candidate.is_file():
                    variables[name] = candidate
        for match in SOURCE_RE.finditer(clean):
            candidate = _repo_path(root, match.group("target"), current)
            if candidate is not None and candidate.is_file():
                refs.add(candidate)
        for segment in _command_segments(clean):
            candidate_segment = segment.strip()
            if not candidate_segment:
                continue
            first = candidate_segment.split(None, 1)[0].strip("\"'")
            candidate = _repo_path(root, first, current)
            if candidate is not None and candidate.is_file():
                refs.add(candidate)
            command_name = Path(first).name
            if command_name in {"bash", "sh", "zsh"}:
                for name in re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", candidate_segment):
                    candidate = variables.get(name)
                    if candidate is not None:
                        refs.add(candidate)
                for match in REPO_PATH_RE.finditer(candidate_segment):
                    candidate = root / match.group("path")
                    if candidate.is_file():
                        refs.add(candidate)
    return refs


def _command_segments(line: str) -> list[str]:
    """Split simple shell commands while retaining quoted data as one segment."""

    segments: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char in ";|&()":
            segments.append(line[start:index])
            start = index + 1
            if char in "|&" and index + 1 < len(line) and line[index + 1] == char:
                index += 1
                start = index + 1
        index += 1
    segments.append(line[start:])
    return segments


def _logical_shell_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Join backslash continuations so a ``for`` word list is not a command."""

    logical: list[tuple[int, str]] = []
    buffered = ""
    start_line = 1
    for line_number, line in enumerate(lines, 1):
        if not buffered:
            start_line = line_number
        piece = line.rstrip()
        continued = piece.endswith("\\") and not piece.endswith("\\\\")
        if continued:
            buffered += piece[:-1] + " "
        else:
            buffered += piece
            logical.append((start_line, buffered))
            buffered = ""
    if buffered:
        logical.append((start_line, buffered))
    return logical


def _absolute_call(segment: str) -> str | None:
    candidate = segment.strip()
    while candidate:
        word = candidate.split(None, 1)[0]
        if word in PREFIX_WORDS or word == "!":
            candidate = candidate[len(word) :].lstrip()
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            # An assignment containing an absolute path is data, not a call.
            # Keep assignments that prefix a real command (``VAR=x /bin/foo``)
            # traversable, but do not report ``VAR=/usr/bin/foo``.
            if "$(" in word:
                substitution = re.search(r"\$\(\s*(?P<path>/(?:usr|bin|sbin|opt|Applications|System)/[^\s;&|()]+)", candidate)
                return substitution.group("path") if substitution else None
            if candidate == word:
                return None
            candidate = candidate[len(word) :].lstrip()
            continue
        break
    match = ABSOLUTE_COMMAND_RE.match(candidate)
    return match.group("path") if match else None


def parse_group_files(root: Path, group: str) -> set[Path]:
    dispatcher_path = root / "ops/test_ops.sh"
    arms = parse_dispatcher(dispatcher_path.read_text())
    if group not in arms:
        raise ValueError(f"unknown ops test group: {group}")

    files: set[Path] = set()
    pending_groups = deque([group])
    seen_groups: set[str] = set()
    while pending_groups:
        current_group = pending_groups.popleft()
        if current_group in seen_groups:
            continue
        seen_groups.add(current_group)
        body = arms[current_group]
        for nested in re.findall(r"\brun_one\s+([A-Za-z][A-Za-z0-9_-]*)", body):
            if nested in arms:
                pending_groups.append(nested)
        files.update(
            root / match.group("path")
            for match in REPO_PATH_RE.finditer(
                "\n".join(_strip_shell_comment(line) for line in body.splitlines())
            )
            if (root / match.group("path")).is_file()
        )

    pending_files = deque(files)
    seen_files: set[Path] = set()
    while pending_files:
        current = pending_files.popleft()
        if current in files and current not in seen_files:
            seen_files.add(current)
        else:
            continue
        for referenced in _referenced_files(root, current, current.read_text()):
            if referenced not in files:
                files.add(referenced)
                pending_files.append(referenced)
    return files


def scan_group(root: Path, group: str) -> list[AbsoluteCall]:
    """Return absolute command calls reachable from one dispatcher group."""

    files = parse_group_files(root, group)
    calls: list[AbsoluteCall] = []
    for path in sorted(files):
        if path.suffix != ".sh":
            continue
        for line_number, line in _logical_shell_lines(path.read_text().splitlines()):
            clean = _strip_shell_comment(line)
            for segment in _command_segments(clean):
                absolute = _absolute_call(segment)
                if absolute is not None:
                    calls.append(
                        AbsoluteCall(
                            group=group,
                            source=path.relative_to(root),
                            line=line_number,
                            path=absolute,
                            command=segment.strip(),
                        )
                    )
    return sorted(calls, key=lambda call: (str(call.source), call.line, call.path))


def chain(group: str) -> list[Path]:
    """Return the files reachable from one dispatcher group."""

    return sorted(parse_group_files(ROOT, group))


def abs_calls_in_file(path: Path) -> list[tuple[int, str]]:
    """Return absolute command calls as ``(line, stripped source)`` pairs."""

    hits: list[tuple[int, str]] = []
    for line_number, line in _logical_shell_lines(path.read_text(errors="replace").splitlines()):
        clean = _strip_shell_comment(line)
        if any(_absolute_call(segment) is not None for segment in _command_segments(clean)):
            hits.append((line_number, line.strip()))
    return hits


def abs_calls(group: str) -> list[tuple[Path, int, str]]:
    """Return ``(relative source path, line, command)`` for a group."""

    return [(call.source, call.line, call.command) for call in scan_group(ROOT, group)]


def _report(root: Path, groups: list[str]) -> list[dict[str, object]]:
    return [
        {
            **asdict(call),
            "source": str(call.source),
        }
        for group in groups
        for call in scan_group(root, group)
    ]


def _positional_cli(argv: list[str]) -> int | None:
    if not argv or argv[0] not in {"chain", "abs-calls", "abs-calls-file"}:
        return None

    command = argv[0]
    try:
        if command == "chain" and len(argv) == 2:
            for path in chain(argv[1]):
                print(path.relative_to(ROOT))
            return 0
        if command == "abs-calls" and len(argv) in {2, 3}:
            calls = abs_calls(argv[1])
            if len(argv) == 3 and argv[2] == "--count":
                print(len(calls))
            elif len(argv) == 2:
                for path, line, text in calls:
                    print(f"{path}:{line}:{text}")
            else:
                raise ValueError("abs-calls accepts only --count as an optional flag")
            return 0
        if command == "abs-calls-file" and len(argv) == 2:
            path = Path(argv[1])
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            for line, text in abs_calls_in_file(path):
                print(f"{line}:{text}")
            return 0
    except (KeyError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"usage: {command} <group> [--count]", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    positional_result = _positional_cli(argv)
    if positional_result is not None:
        return positional_result

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--group", action="append", dest="groups")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    dispatcher = parse_dispatcher((root / "ops/test_ops.sh").read_text())
    groups = args.groups or sorted(dispatcher)
    report = _report(root, groups)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, sort_keys=True)
        print()
    else:
        for row in report:
            print(
                f"{row['group']}\t{row['source']}:{row['line']}\t"
                f"{row['path']}\t{row['command']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
