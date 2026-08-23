"""Run a test group behind a repository-wide blocking execution lock."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parent
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from lib.executables import resolve_argv  # noqa: E402
from lib.test_execution_lock import TestExecutionLock  # noqa: E402


def common_anchor(repo: Path) -> Path:
    """Return the shared Git directory parent for linked or normal worktrees."""

    root = repo.expanduser().resolve()
    command = resolve_argv(["git", "-C", str(root), "rev-parse", "--git-common-dir"])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("unable to resolve Git common directory: timed out") from exc
    except OSError as exc:
        raise RuntimeError(f"unable to resolve Git common directory: {exc}") from exc
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise RuntimeError(f"unable to resolve Git common directory: {detail}")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--lock-name", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("a child command is required after --")

    try:
        anchor = common_anchor(args.repo_root)
        with TestExecutionLock(anchor, args.lock_name):
            return subprocess.run(command, check=False, cwd=args.repo_root).returncode
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"test execution group failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
