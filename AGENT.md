# AGENT.md

This workspace is a **single monorepo**.

## Scope (rough)
- Root git tracks everything under this workspace.
- Main code areas:
  - `booksbrowser_ios/` (iOS app)
  - `knowledge_graph_api/` (backend)
- Ops/docs live at root: `docs/`, `ops/`, `devops.sh`, `support.html`, `privacy.html`.

## Agent Rules (rough)
1. Decide target scope first: iOS / API / workspace ops.
2. Keep commits focused by scope (do not mix unrelated iOS/API/ops changes in one commit).
3. For deploy/migration tasks, run preflight/backup flow before production actions.
4. Prefer updating this file briefly and keeping detailed rules in docs.

## Detailed Workflow
See: `docs/super_repo_submodules.md` (detailed monorepo workflow and commit conventions).
