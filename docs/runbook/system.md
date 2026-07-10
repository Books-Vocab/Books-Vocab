<!-- doc-meta
tier: runbook
authority: derived
update_trigger: sop-change
scope:
  - ops/
verified_against: 8da8c5516
-->
# System Runbook

## Purpose
Provide one stable operations system so any agent can safely execute tasks from:
- repository root (global view)
- project subfolder (project-only view)

## Startup Checklist
1. For a new or cross-surface task, trigger `kg-router`.
2. Run `ops/devops_kg_safe.sh preflight` before production work.
3. Before merging worktree branches into `main` or pruning remote branches, run `ops/branch_audit.sh` (commit reachability, not PR state).
4. Before touching unfamiliar control-plane surfaces, run `ops/capability_matrix.py --json`.
5. If a typed tool is confusing or nudges agents toward bypassing it, classify the friction; fix medium/large tool issues before continuing the original workflow.

## Allowed Production Entrypoints
- KG API: `ops/devops_kg_safe.sh`
- Automated push=deploy reconciler (felix-local, launchd `com.kg.reconcile`): `ops/kg_reconcile.sh` — converges the prod container to `origin/main` on backend changes; shares `/tmp/kg-deploy.lock` with the manual deploy path, self-rolls-back + poisons a bad sha on health-gate failure. Enabled manually by the general manager; see `docs/sop/deploy.md` §push=deploy 自動 reconciler.
- Global status: `ops/devops_kg_safe.sh status` + `ops/devops_kg_safe.sh health`
- Compatibility status wrapper: `ops/status_all.sh`
- Remote branch reachability audit: `ops/branch_audit.sh`
- Capability contract: `ops/capability_matrix.py`
- Cold-start routing: `.claude/skills/kg-router`
- Docs control-plane flow: `.claude/skills/kg-docs-control-plane`
- Completion receipt flow: `.claude/skills/kg-receipt`

Do not bypass these entrypoints unless explicitly required and reviewed.

## Change Types and Required Flow

### A) Feature Delivery
1. Work inside project directory.
2. Implement and test code changes.
3. Run preflight.
4. Backup production state.
5. Deploy via safe script.
6. Validate service health (host-local + public URL).

### B) Maintenance/Incident
1. Run status and logs via safe wrapper.
2. If deploy needed, backup first.
3. If health fails post-deploy, rollback to previous artifact/snapshot.
4. Record incident summary and update runbook docs.

### C) Worktree Lifecycle
**Topology: local-`main`-centric.** Local `main` is the trunk; worktrees fork from it and `cutover` fast-forwards it OFFLINE. origin/main is a deploy target — `deploy` publishes the local trunk to origin, where the felix reconciler turns a backend delta into a rollout. So local main runs ahead of origin until a deliberate `deploy`. Worktree health is a **process-internal invariant**, not a periodic cleanup chore. Isolated worktrees are driven by the `worktree-flow` skill orchestrating `ops/worktree_orchestrate.py` (`preflight` / `open` / `adopt` / `gate` / `cutover` / `resolve` / `deploy` / `sync-main` / `freeze`); each worktree lands via `cutover` and self-cleans via `resolve`. (The former `converge` / `cleanup` / `promote` sweep methodology is retired — its function is now subsumed by this in-flow invariant.)
1. `preflight` = `git fetch` + `worktree_registry sweep` (conservative shapes only: dangling-landed / detached-orphan / registry-resolved). It collects crash residue left *outside* the flow; the base branch and the primary worktree are absolutely protected.
2. `open` births the worktree + branch off LOCAL `main` (offline) and registers it (registry born→resolved ledger + orphan sentinel). `adopt` backfills the registration for a worktree created out-of-band (bootstrap fallback: a bare `git worktree add` needs no tooling); it registers the worktree root and anchors the ledger on the target's git-common-dir.
3. `gate` diffs the worktree vs local `main`, routes changes to existing gate tools, and records a `verdict` bound to worktree + HEAD. `block` must be fixed; `warn` is advisory.
4. `cutover` requires a **fresh non-block verdict** for the current HEAD, then rebases onto local `main` and ff's the primary checkout's local `main` to it (serialized by a per-repo lock; primary must be on main + tracked-clean, since a ff updates its files). OFFLINE — no push, no deploy.
5. `resolve` enforces a **landed-floor** (unlanded branches are refused; `--force` to override), then registry-resolves, removes the worktree, deletes the branch (local + remote if present), and drops the gate-record cache.
6. `deploy` publishes the local trunk to origin — the ONE deliberate production touch. Guarded ff push (primary on main, origin a strict ancestor of local, never a force); noop when already published; surfaces the backend files in range (a backend delta → the felix reconciler runs a health-gated rollout with auto-rollback; deploy does not re-run that gate). "Land backend on origin IS deploying it" — but that push is `deploy`, not `cutover`.
7. `sync-main` = guarded **lossless** ff of the primary checkout's local `main` to origin (refuses unless tracked-clean + on `main` with no merge/rebase in flight + strictly behind origin; a diverged main is never auto-merged — land unique commits via `cutover`). In the local-centric model the dev machine's main runs AHEAD of origin, so this is a noop there; it earns its keep on the felix deploy clone and after a fresh clone.
8. `freeze on --reason <surgery>` = stop-the-world lock for repo surgery (history rewrite / aggressive gc / shared hooks-config): while frozen, `open`/`adopt`/`cutover`/`sync-main`/`deploy` refuse; draining steps (`resolve`/`sweep`/`preflight`/`gate`) stay allowed. Drain to zero active worktrees → back up refs → operate → verify → `freeze off`.
9. All mutation subcommands are dry-run by default; `--commit` to land.

## Operational Definition of Done
- `preflight` succeeded.
- Backup exists and path recorded.
- Health checks return expected HTTP codes.
- Relevant docs updated.

## Hard Stop Conditions
- Missing SSH key or unreachable host.
- No backup path before deploy/migration.
- `ops/branch_audit.sh` reports `merged-pr-but-ahead`, `orphan-ahead`, or `stale-ahead` before a branch merge/prune; PR state is metadata, commit reachability is the source of truth.
- Any operation would reset or force-update `main`; the worktree flow only fast-forward pushes, and `resolve` refuses to tear down unlanded work.
- Any command resembles destructive wildcard cleanup.
