#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Registry-backed docs impact hints.

Path-hint detector: maps changed paths to docs/registry.yml `sources` entries
and emits candidate docs that may need sync. `match_type` indicates whether a
candidate came from an exact source, a broad directory/glob hint, or a
partially/fully suppressed broad match. `--explain` shows which broad matches
were suppressed by registry `!path` / `!glob` exclusions.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Document:
    id: str
    path: str
    kind: str
    authority: str = ""
    generator: str = ""
    triggers: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def run_git(args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def repo_root() -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"]).strip())


def strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_registry(path: Path) -> list[Document]:
    documents: list[Document] = []
    current: Document | None = None
    list_field: str | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("  - id:"):
            if current is not None:
                documents.append(current)
            current = Document(id=strip_scalar(line.split(":", 1)[1]), path="", kind="")
            list_field = None
            continue

        if current is None or not line.startswith("    "):
            continue

        if line.startswith("    ") and not line.startswith("      - "):
            key, sep, value = stripped.partition(":")
            if not sep:
                continue
            value = strip_scalar(value)
            if key in {"triggers", "sources"}:
                list_field = key
                continue
            list_field = None
            if hasattr(current, key):
                setattr(current, key, value)
            continue

        if line.startswith("      - ") and list_field in {"triggers", "sources"}:
            getattr(current, list_field).append(strip_scalar(stripped[2:].strip()))

    if current is not None:
        documents.append(current)
    return documents


def parse_surface_paths(path: Path) -> list[str]:
    """Read the sole agent-facing surface path list from the registry."""
    in_surface = False
    in_paths = False
    paths: list[str] = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line == "agent_facing_surface:":
            in_surface = True
            in_paths = False
            continue
        if in_surface and line and not line[0].isspace():
            break
        if not in_surface:
            continue
        if line == "  paths:":
            in_paths = True
            continue
        if in_paths and line.startswith("    - "):
            paths.append(strip_scalar(line[6:]))
            continue
        if in_paths and line.startswith("  "):
            in_paths = False

    if not paths:
        raise SystemExit("ERROR registry 缺 agent_facing_surface.paths")
    return paths


def scan_surface(root: Path, paths: list[str], pattern: str) -> int:
    """Scan registry-owned paths, including dot-directories, for a regex."""
    try:
        matcher = re.compile(pattern)
    except re.error as exc:
        raise SystemExit(f"ERROR surface pattern 無效: {exc}") from exc

    files: list[Path] = []
    for surface_path in paths:
        target = root / surface_path
        if not target.exists():
            raise SystemExit(f"ERROR surface path 不存在: {surface_path}")
        if target.is_file():
            files.append(target)
            continue
        files.extend(
            candidate
            for candidate in sorted(target.rglob("*"))
            if candidate.is_file() and ".git" not in candidate.relative_to(root).parts
        )

    hits = 0
    for file_path in files:
        relative = file_path.relative_to(root).as_posix()
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError as exc:
            raise SystemExit(f"ERROR surface path 無法讀取: {relative}: {exc}") from exc
        for line_number, line in enumerate(lines, start=1):
            if matcher.search(line):
                print(f"SURFACE {relative}:{line_number}:{line}")
                hits += 1
    print(f"surface_scan: pattern={pattern} roots={len(paths)} files={len(files)} hits={hits}")
    return 0


def normalize_path(path: str) -> str:
    return path.removeprefix("./").strip()


def default_changed_base() -> str:
    if run_git(["rev-parse", "--verify", "origin/HEAD"], check=False).strip():
        return run_git(["merge-base", "origin/HEAD", "HEAD"]).strip()
    return run_git(["rev-parse", "HEAD"]).strip()


def changed_paths_since(base: str) -> list[str]:
    if not run_git(["rev-parse", "--verify", f"{base}^{{commit}}"], check=False).strip():
        raise SystemExit(f"ERROR --since 不是有效 commit: {base}")

    # `<base>...HEAD` needs a merge-base; without one git exits 128 with EMPTY stdout,
    # which would silently render as "no registry impacts". A valid commit is not
    # evidence of shared history, so probe it separately and fail closed.
    if not run_git(["merge-base", base, "HEAD"], check=False).strip():
        # Two different causes share this symptom and git reports neither (its stderr
        # here is empty), so the cause has to be probed or the message will misdirect:
        # a truncated history is fixed by deepening the fetch, never by --files.
        if run_git(["rev-parse", "--is-shallow-repository"], check=False).strip() == "true":
            raise SystemExit(
                f"ERROR --since {base}:這是 shallow checkout,共同祖先很可能只是被截斷。"
                "先 `git fetch --unshallow`(CI 設 fetch-depth: 0)再重跑;"
                "不要改用 --files 手工列路徑繞過,那是拿可修的抓取深度換掉自動偵測。"
            )
        raise SystemExit(
            f"ERROR --since {base} 與 HEAD 無共同祖先,無法從 merge-base 起算。"
            "--since 問的是「這條分支自己改了什麼」;要比對無關歷史請改用 --files。"
        )

    output = "\n".join(
        [
            run_git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"], check=False),
            run_git(["diff", "--name-only", "--diff-filter=ACMR", "--cached"], check=False),
            run_git(["diff", "--name-only", "--diff-filter=ACMR"], check=False),
            run_git(["ls-files", "--others", "--exclude-standard"], check=False),
        ]
    )
    return sorted({normalize_path(line) for line in output.splitlines() if line.strip()})


def source_matches(source: str, changed_path: str) -> bool:
    source = normalize_path(source)
    changed_path = normalize_path(changed_path)
    if any(mark in source for mark in "*?["):
        return fnmatch.fnmatch(changed_path, source)
    if source.endswith("/"):
        return changed_path.startswith(source)
    return changed_path == source


def is_broad_source(source: str) -> bool:
    source = normalize_path(source)
    return source.endswith("/") or any(mark in source for mark in "*?[")


def match_type_rank(match_type: str) -> int:
    order = {
        "exact": 0,
        "suppressed-partial": 1,
        "broad": 2,
        "suppressed": 3,
    }
    return order.get(match_type, 99)


def impact_documents(
    documents: list[Document], changed_paths: list[str], *, explain: bool = False
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    impacts: list[dict[str, object]] = []
    excluded_impacts: list[dict[str, object]] = []
    for doc in documents:
        include_sources = [source for source in doc.sources if not source.startswith("!")]
        exclude_sources = [source[1:] for source in doc.sources if source.startswith("!")]
        matched_sources: set[str] = set()
        matched_paths: set[str] = set()
        excluded_sources: set[str] = set()
        excluded_paths: set[str] = set()
        excluded_by: set[str] = set()
        for source in include_sources:
            for changed_path in changed_paths:
                if not source_matches(source, changed_path):
                    continue
                path_excludes = [
                    f"!{exclude}" for exclude in exclude_sources if source_matches(exclude, changed_path)
                ]
                if path_excludes:
                    if explain:
                        excluded_sources.add(source)
                        excluded_paths.add(changed_path)
                        excluded_by.update(path_excludes)
                    continue
                matched_sources.add(source)
                matched_paths.add(changed_path)
        if matched_paths:
            match_type = "broad" if any(is_broad_source(source) for source in matched_sources) else "exact"
            if explain and excluded_paths:
                match_type = "suppressed-partial"
            impact = {
                "id": doc.id,
                "path": doc.path,
                "kind": doc.kind,
                "authority": doc.authority,
                "match_type": match_type,
                "triggers": doc.triggers,
                "matched_sources": sorted(matched_sources),
                "matched_paths": sorted(matched_paths),
            }
            if explain and excluded_paths:
                impact["excluded_sources"] = sorted(excluded_sources)
                impact["excluded_paths"] = sorted(excluded_paths)
                impact["excluded_by"] = sorted(excluded_by)
            if doc.generator:
                impact["generator"] = doc.generator
            impacts.append(impact)
        elif explain and excluded_paths:
            impact = {
                "id": doc.id,
                "path": doc.path,
                "kind": doc.kind,
                "authority": doc.authority,
                "match_type": "suppressed",
                "triggers": doc.triggers,
                "matched_sources": sorted(excluded_sources),
                "matched_paths": sorted(excluded_paths),
                "excluded_by": sorted(excluded_by),
            }
            if doc.generator:
                impact["generator"] = doc.generator
            excluded_impacts.append(impact)
    impacts.sort(key=lambda impact: (match_type_rank(str(impact.get("match_type", ""))), str(impact["id"])))
    excluded_impacts.sort(
        key=lambda impact: (match_type_rank(str(impact.get("match_type", ""))), str(impact["id"]))
    )
    return impacts, excluded_impacts


def print_human(
    base: str | None,
    changed_paths: list[str],
    impacts: list[dict[str, object]],
    *,
    excluded_impacts: list[dict[str, object]] | None = None,
) -> None:
    base_label = base if base else "files"
    excluded_impacts = excluded_impacts or []
    if not impacts and not excluded_impacts:
        print(f"docs_impact: no registry impacts (base={base_label}, changed={len(changed_paths)})")
        return

    summary = f"docs_impact: base={base_label} changed={len(changed_paths)} impacts={len(impacts)}"
    if excluded_impacts:
        summary += f" excluded={len(excluded_impacts)}"
    print(summary)
    print(
        "docs_impact: match_type legend -> "
        "exact=source exact match, broad=directory/glob candidate, "
        "suppressed-partial=impact kept but some paths excluded, suppressed=fully excluded"
    )
    print(
        "docs_impact: recommended review order -> "
        "exact first, then suppressed-partial, then broad candidates; "
        "suppressed rows are explanation only"
    )
    for impact in impacts:
        match_type = str(impact.get("match_type", "unknown"))
        triggers = ",".join(str(t) for t in impact["triggers"]) or "-"
        sources = ",".join(str(s) for s in impact["matched_sources"]) or "-"
        paths = ",".join(str(p) for p in impact["matched_paths"]) or "-"
        excluded_paths = ""
        excluded_by = ""
        if "excluded_paths" in impact:
            excluded_paths = f" excluded_changed={','.join(str(p) for p in impact['excluded_paths']) or '-'}"
        if "excluded_by" in impact:
            excluded_by = f" excluded_by={','.join(str(p) for p in impact['excluded_by']) or '-'}"
        generator = f" generator={impact['generator']}" if "generator" in impact else ""
        print(
            "IMPACT "
            f"{impact['id']} {impact['path']} "
            f"match_type={match_type} via={sources} changed={paths}{excluded_paths}{excluded_by} triggers={triggers}{generator}"
        )
    for impact in excluded_impacts:
        match_type = str(impact.get("match_type", "suppressed"))
        triggers = ",".join(str(t) for t in impact["triggers"]) or "-"
        sources = ",".join(str(s) for s in impact["matched_sources"]) or "-"
        paths = ",".join(str(p) for p in impact["matched_paths"]) or "-"
        excluded_by = ",".join(str(p) for p in impact["excluded_by"]) or "-"
        generator = f" generator={impact['generator']}" if "generator" in impact else ""
        print(
            "EXCLUDED "
            f"{impact['id']} {impact['path']} "
            f"match_type={match_type} via={sources} changed={paths} excluded_by={excluded_by} triggers={triggers}{generator}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        help="Git base rev; scans <rev>...HEAD (from the merge-base, so a base branch that "
        "moved on is not counted as this branch's work) plus index/worktree changes.",
    )
    parser.add_argument("--files", nargs="+", help="Explicit changed paths, for tests or scripted callers.")
    parser.add_argument("--registry", default="docs/registry.yml", help="Registry path.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Also emit candidates suppressed by registry !path/!glob exclusions.",
    )
    surface_group = parser.add_mutually_exclusive_group()
    surface_group.add_argument(
        "--surface-paths",
        action="store_true",
        help="Print the agent-facing surface paths from docs/registry.yml agent_facing_surface.paths.",
    )
    surface_group.add_argument(
        "--surface-scan",
        metavar="PATTERN",
        help="Regex-scan the registry-owned agent-facing surface, including dot-directories.",
    )
    parser.add_argument(
        "--root",
        metavar="DIR",
        help="Repository root for --surface-paths/--surface-scan (default: git root).",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else repo_root()
    registry_arg = Path(args.registry)
    registry_path = registry_arg if registry_arg.is_absolute() else root / registry_arg
    if not registry_path.is_file():
        raise SystemExit(f"ERROR registry 不存在: {args.registry}")

    if args.surface_paths or args.surface_scan is not None:
        surface_paths = parse_surface_paths(registry_path)
        if args.surface_paths:
            print("\n".join(surface_paths))
            return 0
        return scan_surface(root, surface_paths, args.surface_scan)

    documents = parse_registry(registry_path)
    if args.files:
        base = None
        changed_paths = sorted({normalize_path(path) for path in args.files})
    else:
        base = args.since or default_changed_base()
        changed_paths = changed_paths_since(base)

    impacts, excluded_impacts = impact_documents(documents, changed_paths, explain=args.explain)
    if args.json:
        payload = {"base": base, "changed_paths": changed_paths, "impacts": impacts}
        if args.explain:
            payload["excluded_impacts"] = excluded_impacts
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_human(base, changed_paths, impacts, excluded_impacts=excluded_impacts if args.explain else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
