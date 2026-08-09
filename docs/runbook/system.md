<!-- doc-meta
tier: runbook
authority: derived
update_trigger: sop-change
scope:
  - ops/
verified_against: 44d0c76c5
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
- Role-aware context routing: `.claude/skills/kg-agent-context` → `docs/reference/agent_context.md`
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
**Topology: local-`main`-centric, three planes.** Local `main` is the trunk; worktrees fork from it and `cutover` fast-forwards it OFFLINE (develop plane). `origin/prod` is the deploy target — `deploy` advances it (release plane) and the felix reconciler, watching `origin/prod`, turns a backend delta into a rollout; `origin/main` is the backup mirror (`sync` pushes it, **no production effect** — the reconciler ignores main). Isolated worktrees are driven by `worktree-flow`／`ops/worktree_orchestrate.py`. A Ticket Factory thread produces a batch of groomed tickets; each of multiple Delivery Team threads has one Integrator that fans out N child worktrees, incrementally fans them into one integration tree, then owns the team-level `primary + origin/main` closure. Child workers stop at commit + `hand-back`; this is an internal milestone, not team completion. Three-plane verb semantics: `docs/sop/release.md`.
**`close-wave` is the Delivery Team Integrator's resumable end-to-end entrypoint.** `close-wave --commit` composes integration, one fresh Gate, cutover, source resolve, backlog anchor, validation and integration-tree resolve; `--sync` then pushes the exact landed primary tip to `origin/main`. Other teams' active worktrees may remain; only named source branches are touched, and the final primary/remote sequence is serialized by the delivery-loop lock. Before explicit delivery-loop authorization, use `integrate --commit --no-gate`／`--append` and hand back. In an unstable state, message the affected peer thread with the canonical `team/slug`、branch、worktree path、HEAD、state path、具體 blocker 與證據、要求的動作、pause|continue fields; normal state lives in registry／receipt, not chat.
1. `preflight` = `git fetch` + `worktree_registry sweep` (conservative shapes only: dangling-landed / detached-orphan / registry-resolved). It collects crash residue left *outside* the flow; the base branch and the primary worktree are absolutely protected.
2. `open` **registers first, then** births the worktree + branch off LOCAL `main` (offline). The register is also the CLAIM: `open --backlog ID...` refuses (non-zero) when another active record holds one of those tickets, so a loser is left with no branch and no directory, and a failed `worktree add` hands the claim back. A claim lives exactly as long as the record is active, so `resolve` and `sweep` release it — there is no separate release verb. `adopt` backfills the registration for a worktree created out-of-band (bootstrap fallback: a bare `git worktree add` needs no tooling); it registers the worktree root and anchors the ledger on the target's git-common-dir.
3. `gate` diffs the worktree vs local `main`, routes changes to existing gate tools, and records a `verdict` bound to worktree + HEAD. The record also carries `no_changed_files`: `true` means the gate compared no changed paths, so the result may be a legitimate re-gate but must not be read as proof that new edits were verified; human output warns and `--receipt-line` adds `no-changes`. This signal does **not** change the verdict. It **refuses outright when the worktree does not already contain local `main`'s tip**, naming `behind_commits` / `base_changed_files` — cutover rebases first, so gating a behind tree would bind the verdict to code that never lands (`--plan-only` still previews the routing and records nothing). `block` must be fixed; `warn` is advisory; **`inconclusive`** means the gate ran and went red while `refs/tags` moved underneath it (a linked worktree shares `refs/` with the primary, so a concurrent `release.sh` — or any `git fetch --prune` — is visible mid-run), so that red is attributable to neither the branch nor the tools: it folds the verdict to `warn`, is excluded from the never-green streak, and **`cutover` refuses until the gate is re-run** with refs stable. A blocking **shell** gate's summary (internal gates build their own named summaries in-process and point at no log) leads with the **failure-marked lines** lifted out of the child's output (`✗` U+2717 / `✘` U+2718 — Swift Testing prints the second, one codepoint from the first / `FAIL` / `AssertionError` / `not ok` / `error:` / `[review][block]`, capped at 20), keeps the tail after them, and ends with `full output: <path>` — the whole captured output, written beside the verdict record, cleared before each run of that gate and struck by `resolve`. When the child prints no recognised marker the summary says so, AND relabels the tail `tail (NOT failure lines — …)` so the lines below it are not read as the evidence they are not: until 2026-08-09 both branches printed a bare `tail:`, and `review-receipts` — whose tail is `[review][ok]` lines — therefore displayed passes in the slot an operator reads as the failure (IMP-20260808-8b4690). Any changed `*.sh` also selects `ops-shell-scan`, one repo-wide run of `ops/shell_scan.sh` — the cross-file checks that belong to no single script and were therefore reachable from no diff.
4. `cutover` requires a **fresh non-block verdict** for the current HEAD **whose base is already contained**, and additionally refuses while any gate in that verdict is `inconclusive` (remedy: re-run `gate`) — a branch behind local `main` is refused with `behind_commits` / `base_changed_files`. For an ordinary worktree with no live integration state, the remedy is `worktree_orchestrate.py catchup --worktree <path> --commit`, then re-run `gate` (a clean rebase; any conflict aborts). An integration tree with live state must not catch up: abort, verify source hand-back tips, explicitly tear down the reproducible integration tree, and rebuild from the new main as specified in `docs/sop/release.md`. The rebase onto local `main` is then a no-op, so the landed sha equals the gated sha; that equality is re-checked inside the trunk lock, after the rebase and before the ff, because a peer cutover can advance the trunk between the containment check and the rebase. Then it ff's the primary checkout's local `main` to it (serialized by a per-repo lock; primary must be on main + tracked-clean, since a ff updates its files; a dirty-primary refusal also posts a named notice to `<primary>/.cache/coordination/broadcast.md` — idempotent per day+branch+dirty-set, best-effort, and never able to replace the refusal reason; `land`'s pre-gate check posts through the same helper). `land` asks that same tracked-clean question once **before** the gate as well, so an already-dirty primary costs milliseconds instead of a whole gate run — both checks are required, because the primary can be dirtied *during* the gate. OFFLINE — no push, no deploy. After the ff, and after every post-ff refusal, it stamps the landed sha onto this branch's rows in the wave queue (`staged_closures`) — see the closure flow at the end of this section.
5. `resolve` first fixes the **target's identity** — the branch comes from `git worktree list --porcelain` (never from a `rev-parse` inside the path, whose answer for a `.git`-less directory is the *enclosing* checkout's branch), and the trunk, the remote's default branch, any branch checked out in another worktree, and the primary itself are refused outright with a `reason_code`. Then it enforces a **landed-floor** (unlanded branches are refused; `--force` to override). Note for batch work: containment is decided by tree-diff — *does base hold this branch's version of every file it touched* — so a branch whose work was cherry-picked and then further edited reads as unlanded；正規第二證據路徑是 `--via-integration <ref>`，逐顆以 patch-id 或 subject+files 稽核。稽核成功且 `--commit` 時，工具會在刪來源樹前把 `<ref>` 的實際 tip 蓋到該分支 staged closures，讓 worker 證據可由 wave `anchor` 回填；`--force` 仍只是最後手段。之後才 registry-resolve、移除 worktree（若 git 標 `prunable`，先 streamed `rm -rf`）、刪除 branch（含存在的 remote），並清掉 gate record 與同 stem 的失敗輸出（`gate_logs_removed`）。任一 critical step 失敗即停止後續步驟。
6. `deploy` advances **`origin/prod`** to the local trunk — the ONE deliberate production touch (release plane). Guarded ff push (primary on main, origin/prod a strict ancestor of local, never a force); noop when already published; surfaces the backend files in range (a backend delta → the felix reconciler, watching origin/prod, runs a health-gated rollout with auto-rollback; deploy does not re-run that gate). "Land backend on origin/prod IS deploying it" — but that push is `deploy`, not `cutover`. Its sibling `sync` mirrors the trunk to `origin/main` (backup plane) with the same guarded engine but **zero production effect** — the reconciler ignores main.
7. `sync-main` = guarded **lossless** ff of the primary checkout's local `main` to origin (refuses unless tracked-clean + on `main` with no merge/rebase in flight + strictly behind origin; a diverged main is never auto-merged — land unique commits via `cutover`). In the local-centric model the dev machine's main runs AHEAD of origin, so this is a noop there; it earns its keep on the felix deploy clone and after a fresh clone.
8. `freeze on --reason <surgery>` = stop-the-world lock for repo surgery (history rewrite / aggressive gc / shared hooks-config): while frozen, `open`/`adopt`/`catchup`/`integrate`/`cutover`/`sync`/`sync-main`/`deploy` refuse (`catchup` because a rebase rewrites history, which is exactly what the surgery lock exists to serialize); draining steps (`resolve`/`sweep`/`preflight`/`gate`) stay allowed. Drain to zero active worktrees → back up refs → operate → verify → `freeze off`.
9. **Wave closure — a hunter never writes the store.** A worktree cannot write a correct `fixed_by`: the landing sha does not exist yet, and cutover's rebase rewrites whatever the branch was carrying, so an entry closed in place anchors on an orphan. (The rationale this item used to give — that closing rewrote the generated ledger view, the one file parallel branches provably collide on, at O(entries) per hunter — retired with that view at IMP-20260807-b9526c: it is gitignored now and only the explicit `render` subcommand writes it.) Instead: closure 用 `backlog.py stage <id> --verdict <V> --by <who> --evidence '<cmd>'（含反引號時用 --evidence-file）`；波次中發現新問題則用 `backlog.py add --stage ...`。兩者都只 append 到 gitignored per-repo queue、不寫 store；一般單線立單仍用裸 `add` 立即落地。單線 closure 由 `cutover` 蓋真正 landed sha；批次來源樹由成功的 `resolve --via-integration <ref> --commit` 蓋 `<ref>` tip。波次結束 ONE `backlog.py anchor --commit` 全有或全無地回填 closure 與 staged add；壞 row 用 `unstage <id> --commit` 取下，禁止手改 queue。`resolve` 以 `pending_anchor` 列出本分支已蓋、尚待 wave anchor 的 closures，不阻塞 teardown。
10. Mutation taxonomy is interface-defined: `--commit` controls a command's primary landing action, not universal purity. Birth／ledger lifecycle commands without it are immediate: orchestrator `open`／`adopt`, registry `register`／`hand-back`／`resolve`; `gate` writes verdict/history/log unless `--plan-only`; `freeze on|off` directly mutates the freeze lock while only `status` is read-only; and `preflight` always runs `git fetch --prune`, with `--commit` controlling only sweep clearance. Separately, `backlog.py add` is immediate by default with explicit `--dry-run` preview and `--commit` compatibility alias；wave worker 必須用 `add --stage` 延後到整合者 anchor，避免把自己的 ticket filing 混進修復 diff。Read each subcommand help before inferring side effects. Backlog role/state semantics live in `backlog.py lifecycle --json`.

`gate` 對 linked worktree 另記錄 `primary`、`primary_dirty` 與 `primary_dirty_error`：tracked dirty primary 只產生明示警告，不改 verdict 或 exit code；讀不到 primary 狀態也必須明示，不能靜默當成乾淨。`--plan-only` 不查也不記錄這個觀測。

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
