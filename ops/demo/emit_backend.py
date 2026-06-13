"""Emitter: demo SoT -> ops_edit user-create + seed plan (dry-run) + expectation.

STUB (Phase A). The mapping contract below is authoritative; the Phase-B filler
implements `emit()` against it with zero further design decisions.

OUTPUT PATH(S)
  ops/demo/demo_expectation.json   (schema "kg.ops_world_expectation.v1")
  (the regenerated world-expectation, structurally identical to
  ops/capture_profiles/marketing_demo_expectation.json — it is what
  `ops_cli world-diff` / capture_profile assert the seeded account against.)

  emit() does NOT mutate production data. "emit-backend" produces:
    1. the two ops_edit invocations (as argv lists, for the operator/runbook),
    2. a DRY-RUN of `ops_edit seed` against demo_dataset.json (prevalidate +
       plan, no --commit), surfaced in the return dict,
    3. the regenerated demo_expectation.json artifact.
  U6 production seeding (--commit) is OUT OF SCOPE and gated on explicit user
  approval; this emitter NEVER passes --commit.

OPS_EDIT INVOCATIONS  (SoT -> argv, dry-run unless an operator adds --commit)
  user-create:
    ["ops_edit.py", "user-create", identity.user_id,
     "--email", identity.email, "--provider", identity.provider]
    (provider must be one of google/apple/demo — identity.provider="apple" here.)
    NOTE: ops_edit user-create does not take display_name / provider_user_id /
    access_token; those identity fields are consumed by emit_web / emit_ios and
    by the auth/login shim, not by the backend seed. Backend identity = uid +
    email + provider only.
  seed:
    ["ops_edit.py", "seed", identity.user_id, "<abs path to demo_dataset.json>"]
    demo_dataset.json is ALREADY in the ops_edit seed-spec schema (review_anchor
    + notebooks[] + cards[] + links[]), so it is passed through verbatim — no
    transformation. cmd_seed prevalidates then plans; dry-run prints the plan.

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
  ops/capture_profiles/marketing_demo_expectation.json.

CHECK MODE
  Re-derive demo_expectation.json in memory and byte-compare against the
  committed file; re-run the seed dry-run prevalidation and fail on any error;
  return a drift verdict (exit 1 on drift).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sot import DemoSoT


def emit(sot: DemoSoT, *, check: bool = False, commit: bool = False) -> dict:
    """Emit the backend seed plan (dry-run) + regenerated world-expectation.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-derive the expectation + re-run seed prevalidation and
            byte-compare against the committed artifact; return a drift report.
        commit: write the regenerated demo_expectation.json to disk. This flag
            controls ONLY the local expectation artifact — it NEVER seeds
            production data (no `ops_edit --commit`). Production seeding (U6) is
            out of scope and gated on explicit user approval.

    Returns:
        A dict with the ops_edit argv invocations, the seed dry-run plan, and
        the expectation path / drift verdict.

    Raises:
        NotImplementedError: Phase A stub. See module docstring for the exact
            ops_edit + expectation mapping the Phase-B implementation must honor.
    """
    raise NotImplementedError(
        "emit_backend.emit is a Phase-A stub; see module docstring for the SoT->backend mapping"
    )
