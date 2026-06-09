#!/usr/bin/env python3
"""Execute a local JSON batch plan against ops_edit.py.

Plan schema:
{
  "schema": "kg.ops_edit_batch.v1",
  "ops": [
    {"argv": ["notebook-create", "uid", "Demo", "--color", "#8B6F5A", "--commit", "--json"]},
    ["card-move", "uid", "file in", "--to-notebook", "Turns of Phrase", "--commit", "--json"]
  ]
}

The runner is designed for `devops.sh ops-edit-batch <plan.json>`:
- local plan is uploaded to the production container
- this script is uploaded alongside it
- the script calls `ops_edit.py` once per op inside the container

It also supports local tests by falling back to `backend/ops_edit.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_ops_edit_path() -> Path:
    prod = Path("/app/ops_edit.py")
    if prod.exists():
        return prod
    return _repo_root() / "backend" / "ops_edit.py"


def _default_env(edit_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if edit_path != Path("/app/ops_edit.py"):
        env.setdefault("PYTHONPATH", str(edit_path.parent / "src"))
    return env


def _build_ops_edit_cmd(edit_path: Path) -> list[str]:
    if edit_path == Path("/app/ops_edit.py"):
        return [sys.executable, str(edit_path)]
    uv_bin = shutil.which("uv")
    if uv_bin is None:
        home_uv = Path.home() / ".local" / "bin" / "uv"
        if home_uv.exists():
            uv_bin = str(home_uv)
    if uv_bin:
        return [uv_bin, "run", "--project", str(edit_path.parent), "python", str(edit_path)]
    return [sys.executable, str(edit_path)]


def _normalize_op(raw: Any, *, index: int) -> list[str]:
    if isinstance(raw, list):
        argv = raw
    elif isinstance(raw, dict):
        argv = raw.get("argv")
    else:
        raise ValueError(f"ops[{index}] 必須是 argv list 或 {{\"argv\": [...]}}")
    if not isinstance(argv, list) or not argv:
        raise ValueError(f"ops[{index}].argv 必須是非空 list")
    if not all(isinstance(part, str) and part for part in argv):
        raise ValueError(f"ops[{index}].argv 只能包含非空字串")
    return argv


def _load_plan(path: Path) -> tuple[list[list[str]], bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"plan not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan JSON 無法解析: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("plan root 必須是 object")
    raw_ops = payload.get("ops")
    if not isinstance(raw_ops, list) or not raw_ops:
        raise ValueError("plan.ops 必須是非空 list")
    stop_on_error = bool(payload.get("stopOnError", True))
    ops = [_normalize_op(raw, index=i) for i, raw in enumerate(raw_ops)]
    return ops, stop_on_error


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: ops_edit_batch.py <plan.json>", file=sys.stderr)
        return 2 if not args else 0

    plan_path = Path(args[0])
    try:
        ops, stop_on_error = _load_plan(plan_path)
    except ValueError as exc:
        print(json.dumps({
            "schema": "kg.ops_edit_batch_result.v1",
            "ok": False,
            "error": str(exc),
            "count": 0,
            "results": [],
        }, ensure_ascii=False, indent=2))
        return 1

    edit_path = _default_ops_edit_path()
    env = _default_env(edit_path)
    edit_cmd = _build_ops_edit_cmd(edit_path)
    results: list[dict[str, Any]] = []
    ok = True
    for index, op_argv in enumerate(ops):
        proc = subprocess.run(
            [*edit_cmd, *op_argv],
            capture_output=True,
            text=True,
            env=env,
        )
        result: dict[str, Any] = {
            "index": index,
            "argv": op_argv,
            "returncode": proc.returncode,
        }
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stdout:
            try:
                result["stdout_json"] = json.loads(stdout)
            except json.JSONDecodeError:
                result["stdout"] = stdout
        if stderr:
            result["stderr"] = stderr
        results.append(result)
        if proc.returncode != 0:
            ok = False
            if stop_on_error:
                break

    print(json.dumps({
        "schema": "kg.ops_edit_batch_result.v1",
        "ok": ok,
        "count": len(results),
        "stoppedEarly": len(results) < len(ops),
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
