<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/src/kg/
  - ios/BooksAndVocab/
  - ops/
  - lab/
  - .github/
verified_against: 2a7930c04f661c266ce05b3568f375e1db2a39f1
-->
# Technical Index

這份索引只提供入口，不複製程式邏輯。新增 endpoint、table、env、CLI、workflow 或主要模組時，在同一 PR 更新對應行並跑 docs lint。

## Repository map

| Area | Entry | Tests／verification |
|---|---|---|
| iOS app | `ios/BooksAndVocab/` | `./ops/ios_ops.sh build/test` |
| iOS observability | `ios/BooksAndVocab/Services/AppCrashReporting.swift`、`docs/reference/ios_observability.md` | `./ops/ios_ops.sh sentry --json`、`./ops/sentry_tool.py ... --json` |
| Backend | `backend/src/kg/` | `cd backend && uv run --locked python -m pytest` |
| Podcast／LLM lab | `lab/podcast/`、`lab/llm_eval/` | 各自 README／`uv run` entrypoint |
| GitHub-native delivery model | `docs/reference/delivery_model.md` | GitHub Issue／Project／PR／Actions／repository rules |
| Deterministic delivery control | `ops/delivery.py`、`ops/delivery_control/` | `./ops/delivery.py --help`、`./ops/test_ops.sh delivery-control` |
| Local coordinator | `ops/worktree_registry.py`、`ops/worktree_orchestrate.py` | `./ops/test_ops.sh worktree` |
| Docs control | `docs/registry.yml`、`ops/docs_impact.py`、`ops/docs_lint.sh` | `./ops/test_ops.sh docs-lint` |
| GitHub intake/review | `.github/ISSUE_TEMPLATE/`、`.github/PULL_REQUEST_TEMPLATE.md` | GitHub Issue／PR |
| CI | `.github/workflows/pr-readiness.yml`、`.github/workflows/pr-gate.yml`、`.github/workflows/merge-group-required.yml`、`ops/ci_scope_router.sh`、`ops/ci_confidence_verdict.sh` | typed receipt／exact HEAD readiness；PR 與 merge-group blocking `required`；diff-scoped nonblocking advisory `confidence` |

## Backend routes and data

- API routers：`backend/src/kg/routers/`；schemas／response models：`backend/src/kg/api_models/`。
- Vocabulary intake／CRUD／sync：`backend/src/kg/vocab_*.py`、`backend/src/kg/vocab_handlers/`。
- Graph links：`backend/src/kg/graph_*.py` 與 vocabulary router；詳情以 `docs/reference/sync_lifecycle.md` 為準。
- Podcast：`backend/src/kg/podcast_*.py`；生成與音訊工作流在 `lab/podcast/`。
- Provider registry／費率：`backend/src/kg/llm/providers.py`；變動同步 `docs/reference/cost_baseline.md`。
- Database／migration：backend migration entry 與 deployment SOP；不要從本文件猜資料表或直接拼 SQL。
- Admin／資料操作：`backend/ops_cli.py`、`backend/ops_edit.py`；依 repo guide 的 CLI contract 執行。

## iOS modules

- Reader／bookshelf：`ios/BooksAndVocab/Views/Reader/`、`Views/Bookshelf/`、`Services/`。
- Vocabulary／sync／review：`Views/Vocabulary/`、`Views/TodayReview/`、`Services/KGService+*.swift`。
- Notebook：`Views/Notebook/`；binding／outbox／tombstone 規則見 notebook boundary。
- Podcast：`Views/Podcast/`、`Services/Podcast*`；Release visibility 以 feature flag 與 tests 為準。
- Explore：`Views/Explore/`、shared deck service；catalog contract 見 discover boundary。
- Shared UI／tokens：`Components/`、`DesignSystem/`、`design-system/tokens.json`。
- Localization：`L10n` 與 `ops/i18n_lint.sh`；禁止新增 raw user-facing strings。

## Operational entrypoints

- Build／test：`ops/ios_ops.sh`、`ops/ios_build.sh`、`ops/ios_test.sh`。
- iOS Sentry／agent diagnostics：`ops/ios_ops.sh sentry`、`ops/sentry_tool.py`、`ops/sentry_api.py`、`ops/sentry_contract.py`。
- UI quality：`ops/ui_quality_plane.py`、`ops/ui_quality_gate.py`、`ops/ios_ops.sh quality`。
- Lint／scan：`ops/docs_lint.sh`、`ops/i18n_lint.sh`、`ops/shell_scan.sh`、`ops/python_scan.py`。
- Worktree：`ops/lib/worktree_scope.py`、`ops/worktree_registry.py`、`ops/worktree_orchestrate.py`。
- Delivery control：`ops/delivery.py` 是 JSON command 入口；`inspect`／`metrics`／`plan` 觀測與規劃，`dogfood-preflight` 驗證四角色 clean-slate canary baseline，`receipt`／`publish`／`release-published`／`queue`／`cleanup-merged`／`sync-main` 執行 exact typed transaction，`validate-pr-body` 供 PR readiness 綁定 machine receipt 與 HEAD。
- Long-task safety：`ops/task_registry.py`、`ops/lib/streaming_command.py`（只記 process ownership／heartbeat，不記產品工作狀態）。
- Ops regression：`ops/test_ops.sh`。
- Backend venv health：`uv run --no-project --python 3.13 ops/venv_health.py`；檢查必需的 main `backend/.venv`，並對缺少或失效的 Python、pytest、`uv.lock` 或 dependency probe fail closed。
- Safety／release：`ops/devops_kg_safe.sh`、`ops/release.sh`、`ops/kg_reconcile.sh`、`ops/branch_audit.sh`。
- App Store Connect：`ops/asc.sh`；metadata／submission limitations 以 `docs/sop/ios.md` 為準。

## Configuration and domains

不要在索引內寫秘密值。host、domain、container、port 與 tunnel 以 `docs/reference/host_topology.md` 為準；deployment、migration、health、rollback 以 `docs/sop/deploy.md` 與 `docs/policy/safety.md` 為準；CloudKit／sync 以 `docs/reference/sync_lifecycle.md`；card／CSV 以 `docs/reference/card_format.md`；backend／iOS test strategy 以 `docs/reference/testing/`。

## Change rule

先讀 code 與對應 SoT，再做修改；變更 agent-facing command、flag、env 或 schema 時，跑 `./ops/docs_impact.py --surface-scan` 與 `./ops/docs_lint.sh`。若入口不存在，修正索引與 tests，不留下指向已刪除工具的說明。
