# Agent Entry (Workspace Super-Repo)

This workspace is a **super-repo** that coordinates two project repos via submodules.

## What This Repo Is For
- Cross-project coordination (release alignment, deploy/runbook, ops docs)
- Tracking which iOS commit + API commit are paired for a release
- Workspace-level scripts/docs only

## What To Do First
1. Confirm task scope: `ios`, `api`, or `workspace`.
2. If changing app/backend code, enter the corresponding submodule and commit there.
3. Return to workspace root and commit updated submodule pointers.

## Repo Boundaries
- `booksbrowser_ios/` = iOS git repo (submodule)
- `knowledge_graph_api/` = backend git repo (submodule)
- root (`docs/`, `ops/`, `devops.sh`, policy/support pages, this file) = workspace super-repo

## Golden Rule
- Do not mix code commits across layers:
  - app/api code changes => commit in submodule first
  - version pairing/docs/ops changes => commit in workspace root

## Detailed Workflow
See: `docs/super_repo_submodules.md`
