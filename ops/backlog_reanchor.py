"""Patch-id based recovery of orphaned backlog commit evidence."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Pattern


def _default_git(*args: str, repo: Path | None = None):
    return subprocess.run(
        ["git", *args],
        cwd=repo or Path.cwd(),
        capture_output=True,
        text=True,
    )


def _default_patch_id_runner(text: str, cwd: Path):
    return subprocess.run(
        ["git", "patch-id", "--stable"],
        input=text,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class ReanchorDeps:
    """Callbacks for the reanchor planner and transaction."""

    default_repo: Path = Path(".")
    sha_pattern: Pattern[str] = re.compile(r"^[0-9a-f]{7,40}$")
    doc_anchor_pattern: Pattern[str] = re.compile(
        r"^\s*verified_against:\s*([0-9a-fA-F]{7,40})\s*$", re.MULTILINE
    )
    git: Callable[..., Any] = _default_git
    patch_id_runner: Callable[[str, Path], Any] = _default_patch_id_runner
    make_commit_state: Callable[..., Any] | None = None
    iter_entries: Callable[[Path], Iterable[dict]] | None = None
    entry_path: Callable[[Path, str], Path] | None = None
    update_entry: Callable[..., dict] | None = None
    write_atomic: Callable[[Path, str], None] | None = None
    reanchor_store: Callable[..., dict] | None = None
    error_type: type[Exception] = ValueError


def patch_id(rev: str, repo: Path | None = None, *, deps: ReanchorDeps) -> str | None:
    """Return a stable patch id for one revision, or ``None`` if unavailable."""
    show = deps.git("show", rev, repo=repo or deps.default_repo)
    if show.returncode != 0 or not show.stdout:
        return None
    proc = deps.patch_id_runner(show.stdout, repo or deps.default_repo)
    stdout = proc if isinstance(proc, str) else getattr(proc, "stdout", "")
    values = stdout.split()
    return values[0] if values else None


def reanchor_store(
    store: Path,
    ids: list[str] | None = None,
    *,
    search_depth: int = 2000,
    repo: Path | None = None,
    docs: bool = False,
    deps: ReanchorDeps,
) -> dict:
    """Plan patch-id replacements for orphaned entry/doc anchors."""
    if deps.make_commit_state is None or deps.iter_entries is None:
        raise RuntimeError("reanchor requires make_commit_state and iter_entries")
    state = deps.make_commit_state(repo)
    if state is None:
        raise deps.error_type("reanchor needs a git repository (no --git-dir found)")

    repo_root = Path(repo or deps.default_repo)
    targets: list[tuple[dict, list[str]]] = []
    for payload in deps.iter_entries(store):
        if ids and payload.get("id") not in ids:
            continue
        shas = payload.get("fixed_by") or []
        orphans = [
            sha for sha in shas
            if deps.sha_pattern.match(sha) and state(sha) == "orphan"
        ]
        if orphans:
            targets.append((payload, orphans))

    doc_targets: list[tuple[str, str]] = []
    if docs:
        docs_root = repo_root / "docs"
        if docs_root.is_dir():
            for path in sorted(docs_root.rglob("*.md")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                match = deps.doc_anchor_pattern.search(text)
                if not match:
                    continue
                old = match.group(1)
                if state(old) == "orphan":
                    doc_targets.append((str(path.relative_to(repo_root)), old))

    if not targets and not doc_targets:
        result = {
            "plan": [],
            "searched": 0,
            "scanned": 0,
            "search_depth": search_depth,
            "window_exhausted": None,
            "frame_depth": None,
        }
        if docs:
            result.update({"doc_plan": [], "doc_unmatched": []})
        return result

    frame = ["HEAD", "main"] if deps.git(
        "rev-parse", "--verify", "--quiet", "main^{commit}", repo=repo
    ).returncode == 0 else ["HEAD"]
    log = deps.git("rev-list", f"--max-count={search_depth}", *frame, repo=repo)
    if log.returncode != 0:
        raise deps.error_type("reanchor needs a resolvable HEAD")
    candidates = log.stdout.split()
    total = deps.git("rev-list", "--count", *frame, repo=repo).stdout.strip()
    frame_depth = int(total) if total.isdigit() else None

    by_patch: dict[str, list[str]] = {}
    indexed = 0
    for rev in candidates:
        value = patch_id(rev, repo, deps=deps)
        if value:
            by_patch.setdefault(value, []).append(rev)
            indexed += 1

    plan: list[dict] = []
    for payload, orphans in targets:
        shas = payload.get("fixed_by") or []
        moves, unmatched = {}, []
        for sha in orphans:
            value = patch_id(sha, repo, deps=deps)
            hits = by_patch.get(value, []) if value else []
            if len(hits) == 1:
                moves[sha] = hits[0][:9]
            else:
                if len(hits) > 1:
                    reason = "ambiguous-patch-id"
                    next_step = (
                        f"choose the correct landed commit and run update {payload['id']} "
                        "--fixed-by <sha>"
                    )
                elif frame_depth is None or len(candidates) < frame_depth:
                    reason = "search-window-not-covered"
                    next_step = (
                        f"rerun reanchor with --search-depth > {len(candidates)} "
                        "to cover the full frame"
                    )
                else:
                    reason = "patch-id-mismatch"
                    next_step = (
                        f"run update {payload['id']} --fixed-by {sha} with the "
                        "correct landed commit"
                    )
                unmatched.append(
                    {
                        "sha": sha,
                        "candidates": len(hits),
                        "reason": reason,
                        "next_step": next_step,
                    }
                )
        if moves or unmatched:
            plan.append(
                {
                    "id": payload["id"],
                    "moves": moves,
                    "unmatched": unmatched,
                    "new_fixed_by": [moves.get(sha, sha) for sha in shas],
                }
            )

    doc_plan: list[dict] = []
    doc_unmatched: list[dict] = []
    for path, old in doc_targets:
        value = patch_id(old, repo, deps=deps)
        hits = by_patch.get(value, []) if value else []
        if len(hits) == 1:
            doc_plan.append({"path": path, "old": old, "new": hits[0][:9]})
            continue
        if len(hits) > 1:
            reason = "ambiguous-patch-id"
            next_step = "choose the correct landed commit and reanchor the document manually"
        elif frame_depth is None or len(candidates) < frame_depth:
            reason = "search-window-not-covered"
            next_step = (
                f"rerun reanchor with --search-depth > {len(candidates)} "
                "to cover the full frame"
            )
        else:
            reason = "patch-id-mismatch"
            next_step = "choose the correct landed commit and reanchor the document manually"
        doc_unmatched.append(
            {
                "path": path,
                "old": old,
                "candidates": len(hits),
                "reason": reason,
                "next_step": next_step,
            }
        )

    result = {
        "plan": plan,
        "searched": indexed,
        "scanned": len(candidates),
        "search_depth": search_depth,
        "frame_depth": frame_depth,
        "window_exhausted": frame_depth is not None and len(candidates) >= frame_depth,
    }
    if docs:
        result.update({"doc_plan": doc_plan, "doc_unmatched": doc_unmatched})
    return result


def cmd_reanchor(args, *, deps: ReanchorDeps) -> int:
    """Run the reanchor plan and commit entry/doc replacements transactionally."""
    if deps.reanchor_store is None:
        raise RuntimeError("reanchor command requires a reanchor_store dependency")
    if deps.entry_path is None or deps.update_entry is None or deps.write_atomic is None:
        raise RuntimeError("reanchor command requires write dependencies")

    result = deps.reanchor_store(
        args.store,
        args.ids or None,
        search_depth=args.search_depth,
        docs=getattr(args, "docs", False),
    )
    landed = []
    doc_landed = []
    if args.commit:
        doc_operations = []
        entry_snapshots = []
        doc_snapshots = []
        try:
            if getattr(args, "docs", False):
                for item in result["doc_plan"]:
                    path = Path(deps.default_repo) / item["path"]
                    text = path.read_text(encoding="utf-8")
                    old = item["old"]
                    new = item["new"]
                    replaced = False

                    def replace_anchor(match):
                        nonlocal replaced
                        if match.group(1) == old:
                            replaced = True
                            return match.group(0).replace(match.group(1), new)
                        return match.group(0)

                    rewritten, count = deps.doc_anchor_pattern.subn(replace_anchor, text)
                    if count < 1 or not replaced:
                        raise deps.error_type(
                            f"document anchor changed while reanchoring: {item['path']}"
                        )
                    doc_operations.append((path, text, rewritten, item["path"]))

            for item in result["plan"]:
                if not item["moves"]:
                    continue
                entry_file = deps.entry_path(args.store, item["id"])
                entry_snapshots.append((entry_file, entry_file.read_text(encoding="utf-8")))
                deps.update_entry(args.store, item["id"], fixed_by=item["new_fixed_by"])
                landed.append(item["id"])
            for path, original, rewritten, rel_path in doc_operations:
                doc_snapshots.append((path, original))
                deps.write_atomic(path, rewritten)
                doc_landed.append(rel_path)
        except (OSError, ValueError, deps.error_type) as exc:
            rollback_errors = []
            for path, original in reversed(doc_snapshots):
                try:
                    deps.write_atomic(path, original)
                except (OSError, ValueError, deps.error_type) as rollback_exc:
                    rollback_errors.append(f"{path}: {rollback_exc}")
            for path, original in reversed(entry_snapshots):
                try:
                    deps.write_atomic(path, original)
                except (OSError, ValueError, deps.error_type) as rollback_exc:
                    rollback_errors.append(f"{path}: {rollback_exc}")

            result["mode"] = "commit"
            result["landed"] = []
            if getattr(args, "docs", False):
                result["doc_landed"] = []
                result["doc_paths"] = [
                    item["path"]
                    for item in result.get("doc_plan", [])
                    if isinstance(item, dict) and item.get("path")
                ]
            result["ok"] = False
            result["error"] = f"reanchor transaction rolled back: {exc}"
            if rollback_errors:
                result["rollback_errors"] = rollback_errors
            if args.json:
                print(json.dumps({"schema": "kg.backlog.reanchor.v1", **result}, ensure_ascii=False))
                return 64
            raise deps.error_type(result["error"])

    result["mode"] = "commit" if args.commit else "dry-run"
    result["landed"] = landed
    if getattr(args, "docs", False):
        result["doc_landed"] = doc_landed
    if args.json:
        print(json.dumps({"schema": "kg.backlog.reanchor.v1", **result}, ensure_ascii=False))
        return 0
    if result["plan"]:
        window = (
            f"indexed {result['searched']} of {result['scanned']} commits scanned"
            f" (--search-depth {result['search_depth']}"
            + (
                f", frame is {result['frame_depth']} commits deep"
                if result["frame_depth"] is not None
                else ""
            )
            + (
                ", window exhausted"
                if result["window_exhausted"]
                else ", window NOT exhausted"
            )
            + ")"
        )
    else:
        window = "no orphans, so no commits were indexed"
    print(f"[{result['mode']}] {window}")
    for item in result["plan"]:
        for old, new in item["moves"].items():
            print(f"  {item['id']}: {old} -> {new}")
        for miss in item["unmatched"]:
            print(
                f"  {item['id']}: {miss['sha']} UNMATCHED "
                f"({miss['candidates']} patch-id candidates in window) — "
                f"{miss['reason']}: {miss['next_step']}"
            )
    if not result["plan"]:
        print("  no orphaned fixed_by shas")
    elif not args.commit:
        print("  (dry-run — pass --commit to land)")
    return 0
