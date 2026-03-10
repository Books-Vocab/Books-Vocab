# KG Workspace Agent Guide

## Scope
This directory is the project workspace for KG API + iOS app development and maintenance.

## Identity
- project key: `kg`
- local root: `projects/booksbrowser_workspace`
- API remote root: `~/knowledge_graph_api`
- domain: `wordnexus.lol`
- API container: `knowledge-graph-api`
- internal port: `8000`

## First Steps
1. Confirm this task is project-scoped (not global cross-project).
2. Run preflight:
   - `./ops/devops_kg_safe.sh preflight`
3. For deploy/migration, run backup first:
   - `./ops/devops_kg_safe.sh backup`

## Safe Production Entrypoint
- `./ops/devops_kg_safe.sh`

Allowed commands:
- `deploy|restart|status|logs|backup|env-check|migrate|users|user-info|run`

Blocked by default:
- `setup|push-env|delete-user|ssh`
- destructive `run` strings

## Implemented Product Surface (Inventory)
Use this section as the "what already exists" checklist before proposing or changing anything.

- iOS app surface (`booksbrowser_ios/BooksBrowser`):
  - authentication and session flows (Apple, Google, manual/developer debug flow)
  - bookshelf + reader experience (Readium-based navigation, reader settings, reading UI)
  - translation + explanation interaction in reading flow
  - vocabulary capture, list/detail, sync, and knowledge-graph views
  - settings surface, including account deletion entry under danger operations
  - app-intent/background sync related integration
  - preview matrix covering key screens (Settings, Sync, Reader, Translation, Today Review)
  - UI review checklist (`docs/references/ui_review_checklist.md`)

- KG backend surface (`knowledge_graph_api/src/kg`):
  - auth verification and user identity linking logic
  - user config and account lifecycle APIs (including delete account)
  - vocabulary lifecycle APIs and graph-link APIs
  - translate/explain APIs and pipeline processing APIs
  - card/graph/embedding/difficulty/enrichment and optional Mochi integration modules
  - static policy/support page serving (`privacy.html`, `support.html`)

- Admin and internal tooling surface:
  - admin dashboard web UI exists (`/admin`)
  - admin logs/stats APIs exist (`/api/admin/*`)
  - admin test-matrix UI and APIs exist (`/admin/tests`, `/api/admin/tests/*`)
  - in-memory log capture for app + uvicorn channels exists

- Test surface (`knowledge_graph_api/tests`):
  - API contract/surface tests
  - robustness tests (locking, storage, account/data integrity)
  - renderer behavior tests
  - admin endpoint and test-matrix related tests

- Ops and deployment surface:
  - project safe wrapper (`ops/devops_kg_safe.sh`) and workspace wrapper (`devops.sh`)
  - preflight / backup / deploy / restart / status / logs / migration workflows
  - backup artifacts and incident/debug docs are part of normal operations context

## Docs Router
- backend development:
  - `docs/backend-dev.md`
- deploy / env / migration:
  - `docs/deploy.md`
- incidents / 502 / caddy / users:
  - `docs/debug.md`
- iOS build / xcode:
  - `docs/ios-dev.md`
- UI design:
  - `docs/ui-design.md`
- UI review checklist:
  - `docs/references/ui_review_checklist.md`
- multi-project context:
  - `docs/multi_project_ops.md`

## Common Commands
- status: `./ops/devops_kg_safe.sh status`
- logs: `./ops/devops_kg_safe.sh logs 120`
- deploy: `./ops/devops_kg_safe.sh deploy`

## Git Repos
- **Backend**: `knowledge_graph_api/.git` — commit backend code changes here
- **iOS**: `booksbrowser_ios/.git` — commit iOS changes here
- **Workspace-level files** (`devops.sh`, `ops/`, `docs/`): NOT inside any git repo, not version-controlled

## Cross-Project Note
If task becomes global (new project, caddy topology, cross-project ops), switch to repository root and follow root `AGENTS.md`.
