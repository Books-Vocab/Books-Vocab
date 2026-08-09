#!/usr/bin/env -S uv run --python 3.13
"""Enforce the iOS project-level version-setting ownership contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


OBJECT_START = re.compile(r"^\s*([A-Za-z0-9]+)(?:\s*/\*.*?\*/)?\s*=\s*\{\s*$")
SETTING = re.compile(
    r"^\s*(MARKETING_VERSION|CURRENT_PROJECT_VERSION)\s*=\s*[^;]+;\s*$"
)


def object_ranges(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Return UUID/object spans as half-open line ranges."""

    objects: dict[str, tuple[int, int]] = {}
    for start, line in enumerate(lines):
        match = OBJECT_START.match(line)
        if not match:
            continue
        if match.group(1) == "objects":
            continue
        depth = 0
        end = None
        for index in range(start, len(lines)):
            depth += lines[index].count("{")
            depth -= lines[index].count("}")
            if depth == 0:
                end = index + 1
                break
        if end is not None:
            objects[match.group(1)] = (start, end)
    return objects


def block_text(lines: list[str], span: tuple[int, int]) -> str:
    return "".join(lines[span[0] : span[1]])


def assignment(block: str, key: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(key)}\s*=\s*([A-Za-z0-9]+)\s*(?:/\*.*?\*/)?\s*;",
        block,
    )
    return match.group(1) if match else None


def list_ids(block: str, key: str) -> list[str]:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*\((.*?)\);", block, re.S)
    if not match:
        return []
    return re.findall(r"\b([A-Za-z0-9]+)\s*/\*.*?\*/", match.group(1))


def lint(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]

    objects = object_ranges(lines)
    errors: list[str] = []
    project_candidates = [
        span for span in objects.values() if "isa = PBXProject;" in block_text(lines, span)
    ]
    if len(project_candidates) != 1:
        errors.append(f"expected exactly one PBXProject object, found {len(project_candidates)}")
        return errors

    project_span = project_candidates[0]
    project_block = block_text(lines, project_span)
    config_list_id = assignment(project_block, "buildConfigurationList")
    if not config_list_id:
        errors.append("PBXProject has no buildConfigurationList")
        return errors
    config_list_span = objects.get(config_list_id)
    if config_list_span is None:
        errors.append(f"buildConfigurationList object {config_list_id} is missing")
        return errors

    config_ids = list_ids(block_text(lines, config_list_span), "buildConfigurations")
    if len(config_ids) != 2:
        errors.append(
            f"project buildConfigurationList {config_list_id} has {len(config_ids)} "
            "XCBuildConfiguration objects; expected 2"
        )

    project_config_spans: list[tuple[int, int]] = []
    for config_id in config_ids:
        span = objects.get(config_id)
        if span is None:
            errors.append(f"project XCBuildConfiguration object {config_id} is missing")
            continue
        if "isa = XCBuildConfiguration;" not in block_text(lines, span):
            errors.append(f"project configuration {config_id} is not XCBuildConfiguration")
            continue
        project_config_spans.append(span)

    settings: dict[str, list[int]] = {
        "MARKETING_VERSION": [],
        "CURRENT_PROJECT_VERSION": [],
    }
    for line_number, line in enumerate(lines, start=1):
        match = SETTING.match(line.rstrip("\n"))
        if match:
            settings[match.group(1)].append(line_number)

    for key, line_numbers in settings.items():
        if len(line_numbers) != 2:
            errors.append(f"{key} appears {len(line_numbers)} times; expected exactly 2")
        for line_number in line_numbers:
            zero_based = line_number - 1
            if not any(start <= zero_based < end for start, end in project_config_spans):
                errors.append(f"{key} at line {line_number} is outside project-level build configs")

    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) == 2 else Path("ios/BooksAndVocab.xcodeproj/project.pbxproj")
    if len(argv) > 2:
        print(f"usage: {argv[0]} [PBXPROJ]", file=sys.stderr)
        return 2
    errors = lint(path)
    if errors:
        print(f"PBXPROJ VERSION LINT: {path}", file=sys.stderr)
        for error in errors:
            print(f"  ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PBXPROJ VERSION LINT OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
