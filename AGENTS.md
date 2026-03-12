# KG Workspace Agent Guide

## Scope
This directory is the project workspace for KG API + iOS app development and maintenance.

## Identity
- project key: `kg`
- local root: `projects/kg`
- backend root: `projects/kg/backend`
- ios root: `projects/kg/ios`
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

- iOS app surface (`ios/BooksBrowser`):
  - authentication and session flows (Apple, Google, manual/developer debug flow)
  - bookshelf + reader experience (Readium-based navigation, reader settings, reading UI)
  - translation + explanation interaction in reading flow
  - vocabulary capture, list/detail, sync, and knowledge-graph views
  - settings surface, including account deletion entry under danger operations
  - app-intent/background sync related integration
  - preview matrix covering key screens (Settings, Sync, Reader, Translation, Today Review)
  - UI review checklist (`docs/references/ui_review_checklist.md`)

- KG backend surface (`backend/src/kg`):
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

- Test surface (`backend/tests`):
  - API contract/surface tests
  - robustness tests (locking, storage, account/data integrity)
  - renderer behavior tests
  - admin endpoint and test-matrix related tests

- Ops and deployment surface:
  - project safe wrapper (`ops/devops_kg_safe.sh`) and workspace wrapper (`devops.sh`)
  - preflight / backup / deploy / restart / status / logs / migration workflows
  - backup artifacts and incident/debug docs are part of normal operations context
  - preview matrix covering key screens (Settings, Sync, Reader, Translation, Today Review)
  - UI review checklist (`docs/references/ui_review_checklist.md`)

## iOS 編譯 SOP（強制）

**唯一合法的 xcodebuild 指令**（從 `projects/kg/` 執行）：

```bash
xcodebuild \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -quiet build
```

規則：
- Exit 0 → 成功，停止
- Exit 非 0 → 讀錯誤上下文 ±20 行，修正後重跑
- **禁止**：改機型、拿掉 `-quiet`、加 `2>&1 | grep`、加 `cd ios &&`

## iOS UI Design System（強制）

**觸發條件**：任何涉及 iOS View / UI 的新增或修改任務。

### 前置讀取（動手前必做）
1. 讀 `docs/references/ui_component_pattern_inventory.md` — 查現有元件與 pattern
2. 讀 `docs/references/ui_review_checklist.md` — 自查清單

### Token 禁令（零容忍）
- **禁止** raw color（`Color.red`、`Color(red:...)`、`#colorLiteral`）→ 用 `AppTheme` / `VocabSkin.Palette` / `AppColors`
- **禁止** raw font（`.font(.system(...))`、`Font.custom(...)`）→ 用 `AppFonts` / `VocabSkin.Typography`
- **禁止** raw spacing magic number → 用 `AppShellMetrics` / `AppMetrics` / `VocabSkin.Spacing`
- **禁止** raw animation（`.spring(...)`、`.easeOut(...)`、`.default`）→ 用 `AppMotion` token
- **禁止** raw transition → 用 `AppTransition` token

### 元件復用（先查後建）
- 新增 UI 前**必須**查 inventory，確認無現成元件可用
- 復用優先序：現成 Pattern → 現成 Component → 擴充 Token → 新建元件
- 新建元件須放入對應層級（App Shell / VocabSkin / Reader / Settings）

### 狀態覆蓋（不可省略）
- 每個新畫面/元件必須覆蓋：loading、empty、error、success/completed
- 參照 `docs/references/ui_state_matrix.md` 確認覆蓋範圍

### Motion 契約
- 所有動畫走 `AppMotion` 語意 token（定義在 `Models/AppMetrics.swift`）
- 需要新動畫 → 先在 `AppMotion` 新增 token，再在 feature 中引用
- 同類互動跨 feature 必須共用同一 token

### 環境注入
- Theme：`@Environment(\.appTheme)`，不可硬建 `AppTheme()` instance
- VocabSkin：`@Environment(\.vocabSkin)`，不可硬建 instance

### 完工自查
- 對照 `docs/references/ui_review_checklist.md` 五大項逐一確認
- 關鍵畫面須有 `#Preview`，preview 須能固定狀態（不依賴登入/後端）

## Common Commands
- status: `./ops/devops_kg_safe.sh status`
- logs: `./ops/devops_kg_safe.sh logs 120`
- deploy: `./ops/devops_kg_safe.sh deploy`

## Git
- Monorepo root (`.git`) covers iOS app, backend API, ops/docs
- Commit prefix: `ios:` / `api:` / `ops:` / `docs:`

## Reference Docs (read on demand)
- backend development: `docs/backend-dev.md`
- deploy / env / migration: `docs/deploy.md`
- incidents / 502 / caddy / users: `docs/debug.md`
- iOS build / xcode: `docs/ios-dev.md`
- UI design: `docs/ui-design.md`
- architecture / sync protocol: `docs/architecture.md`

## Cross-Project Note
If task becomes global (new project, caddy topology, cross-project ops), switch to repository root and follow root `CLAUDE.md`.
