"""Emitter: demo SoT -> ops_edit user-create + seed plan (dry-run) + expectation.

The mapping contract below is authoritative; this Phase-B implementation honors
it with zero further design decisions.

OUTPUT PATH(S)
  ops/demo/demo_expectation.json   (schema "kg.ops_world_expectation.v1")
  (the regenerated world-expectation consumed by `ops_cli world-diff` when an
  operator needs to assert the seeded account.)

  emit() does NOT mutate production data. "emit-backend" produces:
    1. the two ops_edit invocations (as argv lists, for the operator/runbook),
    2. a DRY-RUN of `ops_edit seed` against demo_dataset.json (prevalidate +
       plan, no --commit), surfaced in the return dict,
    3. the regenerated demo_expectation.json artifact.
  U6 production seeding (--commit) is OUT OF SCOPE and gated on explicit user
  approval; this emitter NEVER passes --commit to ops_edit against production.

OPS_EDIT INVOCATIONS  (SoT -> argv, dry-run unless an operator adds --commit)
  user-create:
    ["ops_edit.py", "user-create", identity.user_id,
     "--email", identity.email, "--provider", identity.provider]
    (provider must be one of google/apple/demo — identity.provider="apple" here.)
    NOTE: ops_edit user-create does not take display_name / provider_user_id /
    access_token; those identity fields are consumed by emit_ios and
    by the auth/login shim, not by the backend seed. Backend identity = uid +
    email + provider only.
  seed:
    ["ops_edit.py", "seed", identity.user_id, "<abs path to demo_dataset.json>"]
    demo_dataset.json is ALREADY in the ops_edit seed-spec schema (review_anchor
    + notebooks[] + cards[] + links[]), so it is passed through verbatim — no
    transformation. cmd_seed prevalidates then plans; dry-run prints the plan.

DRY-RUN SEED VALIDATION (how the plan is obtained without touching production)
  `ops_edit seed` uses EditContext(require_user=True): the target user_dir must
  exist before a seed (even a dry-run) is accepted. We therefore validate in an
  EPHEMERAL sandbox data dir (KG_DATA_DIR=<tmp>), NOT production:
    1. `ops_edit user-create <uid> --email <e> --provider <p> --commit`
       (--commit here writes ONLY into the throwaway sandbox, never production —
       the sandbox dir is removed at the end of emit()).
    2. `ops_edit seed <uid> <abs demo_dataset.json>` (NO --commit) -> dry-run
       plan + prevalidation. Any malformed-spec error surfaces here as a clean
       non-zero exit, which we re-raise as RuntimeError so the CLI exits 1.
  This exercises the REAL backend prevalidator/planner against the SoT spec
  while keeping production data untouched.

EXPECTATION MAPPING  (SoT dataset -> kg.ops_world_expectation.v1)
  {
    "schema": "kg.ops_world_expectation.v1",
    "config": { "review_clock": { "is_paused": true } },   # demo clock paused
    "notebooks": [ {name, cover_pattern, color} for each dataset notebook ],
    "cards":     [ {content, meaning} for each dataset card ],
    "graphs":    [ {notebook, links:[{from,to,kind}]} grouped by link.notebook ]
  }
  Field subset is intentional: the expectation asserts the *observable* world
  (names/colors/meanings/edge kinds), not interval/difficulty internals — it is
  the assertion surface for `ops_cli world-diff`, mirroring
  the backend projection contract. Ordering is deterministic
  and SoT-driven: notebooks in dataset order; cards in dataset order; graph
  groups in dataset-notebook order (only notebooks that actually carry links),
  links in dataset order within each group.

CHECK MODE
  Re-derive demo_expectation.json in memory and byte-compare against the
  committed file; re-run the seed dry-run prevalidation and fail on any error;
  return a drift verdict (the CLI exits 1 on drift).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sot import DemoSoT

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_BACKEND_DIR = _REPO_ROOT / "backend"
_OPS_EDIT = _BACKEND_DIR / "ops_edit.py"
_DATASET_PATH = _HERE / "demo_dataset.json"
_EXPECTATION_PATH = _HERE / "demo_expectation.json"

EXPECTATION_SCHEMA = "kg.ops_world_expectation.v1"


# --------------------------------------------------------------------------- #
# ops_edit argv plan (SoT -> the two invocations an operator runs)
# --------------------------------------------------------------------------- #
def _user_create_argv(identity: dict[str, Any]) -> list[str]:
    return [
        "ops_edit.py", "user-create", identity["user_id"],
        "--email", identity["email"],
        "--provider", identity["provider"],
    ]


def _seed_argv(identity: dict[str, Any], spec_path: str) -> list[str]:
    return ["ops_edit.py", "seed", identity["user_id"], spec_path]


# --------------------------------------------------------------------------- #
# Expectation derivation (dataset -> kg.ops_world_expectation.v1)
# --------------------------------------------------------------------------- #
def build_expectation(dataset: dict[str, Any]) -> dict[str, Any]:
    """Derive the kg.ops_world_expectation.v1 doc from the SoT dataset.

    Pure: no I/O. Deterministic ordering driven entirely by dataset order.
    """
    notebooks = [
        {"name": nb["name"], "cover_pattern": nb.get("cover_pattern"), "color": nb.get("color")}
        for nb in dataset["notebooks"]
    ]
    cards = [
        {"content": c["content"], "meaning": c["meaning"]}
        for c in dataset["cards"]
    ]

    # Group links by notebook, preserving (a) dataset-notebook order for the
    # groups and (b) dataset link order within each group. Only notebooks that
    # actually carry a link get a graph entry (mirrors marketing expectation).
    links_by_nb: dict[str, list[dict[str, str]]] = {}
    for lk in dataset.get("links", []):
        nb = lk.get("notebook", "default")
        links_by_nb.setdefault(nb, []).append(
            {"from": lk["from"], "to": lk["to"], "kind": lk["kind"]}
        )
    nb_order = [nb["name"] for nb in dataset["notebooks"]]
    # Any link-notebook not declared in notebooks[] (shouldn't happen — the SoT
    # loader rejects it) is appended after the declared ones, in first-seen order.
    ordered_nbs = nb_order + [nb for nb in links_by_nb if nb not in nb_order]
    graphs = [
        {"notebook": nb, "links": links_by_nb[nb]}
        for nb in ordered_nbs
        if nb in links_by_nb
    ]

    return {
        "schema": EXPECTATION_SCHEMA,
        "config": {"review_clock": {"is_paused": True}},
        "notebooks": notebooks,
        "cards": cards,
        "graphs": graphs,
    }


def _serialize_expectation(expectation: dict[str, Any]) -> str:
    """Canonical on-disk form: 2-space indent, non-ASCII preserved, trailing NL.

    Mirrors the canonical world-expectation formatting so a
    --check byte-compare is meaningful.
    """
    return json.dumps(expectation, ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# Seed dry-run validation (real backend prevalidator, ephemeral sandbox)
# --------------------------------------------------------------------------- #
def _run_ops_edit(argv: list[str], *, sandbox: str) -> dict[str, Any]:
    """Run ops_edit.py (argv[1:]) under KG_DATA_DIR=<sandbox>, return parsed JSON.

    argv[0] is the conventional "ops_edit.py" label from the plan; we replace it
    with the real interpreter + script path. --json is appended so stdout is a
    single JSON object.
    """
    cmd = [sys.executable, str(_OPS_EDIT), *argv[1:], "--json"]
    env = dict(os.environ)
    env["KG_DATA_DIR"] = sandbox
    proc = subprocess.run(
        cmd, cwd=str(_BACKEND_DIR), env=env,
        capture_output=True, text=True,
    )
    out = proc.stdout.strip()
    try:
        parsed = json.loads(out) if out else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"ops_edit {argv[1]} did not emit JSON (rc={proc.returncode}): "
            f"{out[:400]} / stderr: {proc.stderr.strip()[:400]}"
        ) from exc
    if proc.returncode != 0 or parsed.get("mode") == "error":
        raise RuntimeError(
            f"ops_edit {argv[1]} failed (rc={proc.returncode}): "
            f"{parsed.get('error') or out[:400]}"
        )
    return parsed


def run_seed_dry_run(identity: dict[str, Any], spec_path: Path) -> dict[str, Any]:
    """Validate the seed against the REAL backend prevalidator, no production write.

    Creates the demo user in a throwaway KG_DATA_DIR (so EditContext's
    require_user check passes), then runs `seed` WITHOUT --commit to get the
    prevalidated dry-run plan. The sandbox is removed afterwards. Raises
    RuntimeError on any prevalidation/plan failure.
    """
    with tempfile.TemporaryDirectory(prefix="kg-demo-seed-dryrun-") as sandbox:
        # 1. user-create --commit INTO THE SANDBOX (never production).
        create_argv = _user_create_argv(identity) + ["--commit"]
        _run_ops_edit(create_argv, sandbox=sandbox)
        # 2. seed dry-run (no --commit) -> prevalidated plan.
        seed_argv = _seed_argv(identity, str(spec_path))
        result = _run_ops_edit(seed_argv, sandbox=sandbox)
    return result


# --------------------------------------------------------------------------- #
# emit()
# --------------------------------------------------------------------------- #
def emit(sot: DemoSoT, *, check: bool = False, commit: bool = False) -> dict:
    """Emit the backend seed plan (dry-run) + regenerated world-expectation.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-derive the expectation + re-run seed prevalidation and
            byte-compare against the committed artifact; set result["drift"] on
            any mismatch/error (the CLI exits 1 on drift).
        commit: write the regenerated demo_expectation.json to disk. This flag
            controls ONLY the local expectation artifact — it NEVER seeds
            production data (no `ops_edit --commit` against production).
            Production seeding (U6) is out of scope, gated on user approval.

    Returns:
        A dict with the ops_edit argv invocations, the seed dry-run plan, and
        the expectation path / drift verdict.
    """
    identity = sot.identity
    dataset = sot.dataset

    # 1. The two operator-facing ops_edit invocations (argv, dry-run by default).
    user_create_argv = _user_create_argv(identity)
    seed_argv = _seed_argv(identity, str(_DATASET_PATH))

    # 2. Seed dry-run against the real backend prevalidator (ephemeral sandbox).
    seed_plan = run_seed_dry_run(identity, _DATASET_PATH)

    # 3. Derive the world-expectation from the dataset.
    expectation = build_expectation(dataset)
    rendered = _serialize_expectation(expectation)
    rel_expectation = str(_EXPECTATION_PATH.relative_to(_REPO_ROOT))

    result: dict[str, Any] = {
        "ops_edit": {
            "user_create": user_create_argv,
            "seed": seed_argv,
            "note": "dry-run by default; an operator appends --commit (U6, gated).",
        },
        "seed_dry_run": {
            "mode": seed_plan.get("mode"),
            "committed": seed_plan.get("committed"),
            "plan": seed_plan.get("plan"),
        },
        "expectation_path": rel_expectation,
        "expectation_schema": EXPECTATION_SCHEMA,
        "expectation_counts": {
            "notebooks": len(expectation["notebooks"]),
            "cards": len(expectation["cards"]),
            "graphs": len(expectation["graphs"]),
            "links": sum(len(g["links"]) for g in expectation["graphs"]),
        },
    }

    if check:
        # Drift = committed expectation differs from a fresh emit, OR the
        # committed file is missing. The seed dry-run above already re-ran
        # prevalidation (raises -> CLI exit 1) so a malformed SoT never
        # false-greens a check.
        if not _EXPECTATION_PATH.exists():
            result["drift"] = True
            result["drift_reason"] = f"{rel_expectation} missing (run --commit to generate)"
        else:
            committed = _EXPECTATION_PATH.read_text(encoding="utf-8")
            if committed != rendered:
                result["drift"] = True
                result["drift_reason"] = (
                    f"{rel_expectation} differs from a fresh emit "
                    "(regenerate with --commit)"
                )
            else:
                result["drift"] = False
        return result

    if commit:
        _EXPECTATION_PATH.write_text(rendered, encoding="utf-8")
        result["written"] = rel_expectation
    else:
        result["dry_run"] = True
        result["would_write"] = rel_expectation

    return result
