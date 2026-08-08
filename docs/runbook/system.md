<!-- doc-meta
tier: runbook
authority: derived
update_trigger: sop-change
scope:
  - ops/
verified_against: db0e9ed46
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
- Automated release=deploy reconciler (felix-local, launchd `com.kg.reconcile`, runs in the dedicated prod clone `~/kg-prod` via `KG_RECON_REPO`): `ops/kg_reconcile.sh` — converges the prod container to `origin/prod` on backend changes (the release plane; `origin/main` is now a backup mirror the reconciler ignores); shares `/tmp/kg-deploy.lock` with the manual deploy path, self-rolls-back + poisons a bad sha on health-gate failure. Enabled manually by the general manager; see `docs/sop/deploy.md` §reconciler and `docs/sop/release.md` for the three-plane switchover.
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
**Topology: local-`main`-centric, three planes.** Local `main` is the trunk; worktrees fork from it and `cutover` fast-forwards it OFFLINE (develop plane). `origin/prod` is the deploy target — `deploy` advances it (release plane) and the felix reconciler, watching `origin/prod`, turns a backend delta into a rollout; `origin/main` is now the backup mirror (`sync` pushes it, **no production effect** — the reconciler ignores main). So local main runs ahead of both origins until a deliberate `deploy`. Worktree health is a **process-internal invariant**, not a periodic cleanup chore. Isolated worktrees are driven by the `worktree-flow` skill orchestrating `ops/worktree_orchestrate.py` (`preflight` / `open` / `adopt` / `gate` / `catchup` / `land` / `integrate` / `cutover` / `resolve` / `sync` / `deploy` / `sync-main` / `freeze`); each worktree lands via `cutover` and self-cleans via `resolve`. (The former `converge` / `cleanup` / `promote` sweep methodology is retired — its function is now subsumed by this in-flow invariant.) Three-plane verb semantics: `docs/sop/release.md`.
1. `preflight` = `git fetch` + `worktree_registry sweep` (conservative shapes only: dangling-landed / detached-orphan / registry-resolved). It collects crash residue left *outside* the flow; the base branch and the primary worktree are absolutely protected.
2. `open` **registers first, then** births the worktree + branch off LOCAL `main` (offline). The register is also the CLAIM: `open --backlog ID...` refuses (non-zero) when another active record holds one of those tickets, so a loser is left with no branch and no directory, and a failed `worktree add` hands the claim back. A claim lives exactly as long as the record is active, so `resolve` and `sweep` release it — there is no separate release verb. `adopt` backfills the registration for a worktree created out-of-band (bootstrap fallback: a bare `git worktree add` needs no tooling); it registers the worktree root and anchors the ledger on the target's git-common-dir.
3. `gate` diffs the worktree vs local `main`, routes changes to existing gate tools, and records a `verdict` bound to worktree + HEAD. It **refuses outright when the worktree does not already contain local `main`'s tip**, naming `behind_commits` / `base_changed_files` — cutover rebases first, so gating a behind tree would bind the verdict to code that never lands (`--plan-only` still previews the routing and records nothing). `block` must be fixed; `warn` is advisory; **`inconclusive`** means the gate ran and went red while `refs/tags` moved underneath it (a linked worktree shares `refs/` with the primary, so a concurrent `release.sh` — or any `git fetch --prune` — is visible mid-run), so that red is attributable to neither the branch nor the tools: it folds the verdict to `warn`, is excluded from the never-green streak, and **`cutover` refuses until the gate is re-run** with refs stable. A blocking **shell** gate's summary (internal gates build their own named summaries in-process and point at no log) leads with the **failure-marked lines** lifted out of the child's output (`✗` / `FAIL` / `AssertionError` / `not ok` / `error:`, capped at 20), keeps the old tail after them, and ends with `full output: <path>` — the whole captured output, written beside the verdict record, cleared before each run of that gate and struck by `resolve`. When the child prints no recognised marker the summary says so rather than silently falling back to the tail alone. Any changed `*.sh` also selects `ops-shell-scan`, one repo-wide run of `ops/shell_scan.sh` — the cross-file checks that belong to no single script and were therefore reachable from no diff.
4. `cutover` requires a **fresh non-block verdict** for the current HEAD **whose base is already contained**, and additionally refuses while any gate in that verdict is `inconclusive` (remedy: re-run `gate`) — a branch behind local `main` is refused with `behind_commits` / `base_changed_files` (remedy: `worktree_orchestrate.py catchup --worktree <path> --commit`, then re-run `gate` — a clean rebase; any conflict aborts and comes back to you, since the generated-file auto-resolver left with the file it was written for in IMP-20260807-b9526c). The rebase onto local `main` is then a no-op, so the landed sha equals the gated sha; that equality is re-checked inside the trunk lock, after the rebase and before the ff, because a peer cutover can advance the trunk between the containment check and the rebase. Then it ff's the primary checkout's local `main` to it (serialized by a per-repo lock; primary must be on main + tracked-clean, since a ff updates its files; a dirty-primary refusal also posts a named notice to `<primary>/.cache/coordination/broadcast.md` — idempotent per branch+dirty-set, best-effort, and never able to replace the refusal reason). `land` asks that same tracked-clean question once **before** the gate as well, so an already-dirty primary costs milliseconds instead of a whole gate run — both checks are required, because the primary can be dirtied *during* the gate. OFFLINE — no push, no deploy. After the ff, and after every post-ff refusal, it stamps the landed sha onto this branch's rows in the wave queue (`staged_closures`) — see the closure flow at the end of this section.
5. `resolve` first fixes the **target's identity** — the branch comes from `git worktree list --porcelain` (never from a `rev-parse` inside the path, whose answer for a `.git`-less directory is the *enclosing* checkout's branch), and the trunk, the remote's default branch, any branch checked out in another worktree, and the primary itself are refused outright with a `reason_code`. Then it enforces a **landed-floor** (unlanded branches are refused; `--force` to override). Note for batch work: containment is decided by tree-diff — *does base hold this branch's version of every file it touched* — so a branch whose work was cherry-picked and then further edited by review fixes reads as unlanded, and `--force` after a per-branch audit is the **normal** cleanup path there, not an escape hatch (audit steps: `.claude/skills/worktree-flow/SKILL.md` batch-integration section), registry-resolves, removes the worktree (preceded by a streamed `rm -rf` when git flags the entry `prunable`, i.e. an earlier teardown was interrupted), deletes the branch (local + remote if present), and drops the gate-record cache together with any failed-gate output logs sitting beside it (`gate_logs_removed`). A failed critical step aborts the remaining ones instead of carrying on.
6. `deploy` advances **`origin/prod`** to the local trunk — the ONE deliberate production touch (release plane). Guarded ff push (primary on main, origin/prod a strict ancestor of local, never a force); noop when already published; surfaces the backend files in range (a backend delta → the felix reconciler, watching origin/prod, runs a health-gated rollout with auto-rollback; deploy does not re-run that gate). "Land backend on origin/prod IS deploying it" — but that push is `deploy`, not `cutover`. Its sibling `sync` mirrors the trunk to `origin/main` (backup plane) with the same guarded engine but **zero production effect** — the reconciler ignores main.
7. `sync-main` = guarded **lossless** ff of the primary checkout's local `main` to origin (refuses unless tracked-clean + on `main` with no merge/rebase in flight + strictly behind origin; a diverged main is never auto-merged — land unique commits via `cutover`). In the local-centric model the dev machine's main runs AHEAD of origin, so this is a noop there; it earns its keep on the felix deploy clone and after a fresh clone.
8. `freeze on --reason <surgery>` = stop-the-world lock for repo surgery (history rewrite / aggressive gc / shared hooks-config): while frozen, `open`/`adopt`/`catchup`/`integrate`/`cutover`/`sync`/`sync-main`/`deploy` refuse (`catchup` because a rebase rewrites history, which is exactly what the surgery lock exists to serialize); draining steps (`resolve`/`sweep`/`preflight`/`gate`) stay allowed. Drain to zero active worktrees → back up refs → operate → verify → `freeze off`.
9. **Wave closure — a hunter never writes the store.** A worktree cannot write a correct `fixed_by`: the landing sha does not exist yet, and cutover's rebase rewrites whatever the branch was carrying, so an entry closed in place anchors on an orphan. (The rationale this item used to give — that closing rewrote the generated ledger view, the one file parallel branches provably collide on, at O(entries) per hunter — retired with that view at IMP-20260807-b9526c: it is gitignored now and only the explicit `render` subcommand writes it.) Instead: `backlog.py stage <id> --verdict <V> --by <who> --evidence '<cmd>'（含反引號時用 --evidence-file）` appends to the gitignored per-repo queue (no `--status`: a wave exists because the landing commit does not exist yet, and `fixed` is the only status that needs one). `cutover` stamps the real landed sha; at wave end ONE `backlog.py anchor --commit` replays the batch into the store, all or nothing. `unstage <id> --commit` is the escape hatch for a row that blocks the wave — never hand-edit the queue. `resolve` lists this branch's still-unanchored closures (`pending_anchor`) without blocking: that is the normal state at teardown, and it is the last moment the worktree exists to say it.
10. All mutation subcommands are dry-run by default; `--commit` to land.

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
