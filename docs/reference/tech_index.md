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
verified_against: afe016c4ea2fcbd7306f9c4f40b4556e77865100
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
| Local coordinator | `ops/worktree_registry.py`、`ops/worktree_registry_core/`、`ops/worktree_orchestrate.py` | `./ops/test_ops.sh worktree` |
| Docs control | `docs/registry.yml`、`ops/docs_impact.py`、`ops/docs_lint.sh` | `./ops/test_ops.sh docs-lint` |
| GitHub intake/review | `.github/ISSUE_TEMPLATE/`、`.github/PULL_REQUEST_TEMPLATE.md` | GitHub Issue／PR |
| CI | `.github/workflows/pr-readiness.yml`、`.github/workflows/pr-gate.yml`、`.github/workflows/merge-group-required.yml`、`ops/ci_scope_router.sh`、`ops/ci_confidence_verdict.sh` | typed receipt／exact HEAD readiness；PR 與 merge-group blocking `required`；diff-scoped nonblocking advisory `confidence` |

## Backend routes and data

- API routers：`backend/src/kg/routers/`；schemas／response models：`backend/src/kg/api_models/`。
- Vocabulary intake／CRUD／sync：`backend/src/kg/vocab_*.py`、`backend/src/kg/vocab_handlers/`；missing-target Add Link 的 durable composite operation 在 `backend/src/kg/vocab_add_link_operation.py`，request／status schemas 在 `backend/src/kg/api_models/vocab_add_link.py`。A 的原始 context 只作 B 的 sense-disambiguation 參照，不落地成 B 的例句或關係文案。
- Graph links：`backend/src/kg/graph_*.py` 與 vocabulary router；`POST /api/graph/links/ensure-target` 只 enqueue、`GET /api/operations/{operation_id}` 讀取狀態，詳情以 `docs/reference/sync_lifecycle.md` 為準。
- Podcast：`backend/src/kg/podcast_*.py`；生成與音訊工作流在 `lab/podcast/`。
- Provider registry／費率：`backend/src/kg/llm/providers.py`；變動同步 `docs/reference/cost_baseline.md`。
- Database／migration：backend migration entry 與 deployment SOP；不要從本文件猜資料表或直接拼 SQL。
- Admin／資料操作：`backend/ops_cli.py`、`backend/ops_edit.py`；依 repo guide 的 CLI contract 執行。

## iOS modules

- Reader／bookshelf：`ios/BooksAndVocab/Views/Reader/`、`Views/Bookshelf/`、`Services/`。
- Vocabulary／sync／review：`Views/Vocabulary/`、`Views/TodayReview/`、`Services/KGService+*.swift`；missing-target Add Link 的 operation wire contract／client transport 在 `Services/AddLinkOperation.swift`、`Services/KGService+AddLinkOperation.swift`，context 僅作建立 B 時的私有義項線索，完成後沿用既有 serialized vocabulary pull。
- Notebook：`Views/Notebook/`；binding／outbox／tombstone 規則見 notebook boundary。
- Podcast：`Views/Podcast/`、`Services/Podcast*`；Release visibility 以 feature flag 與 tests 為準。
- Explore：`Views/Explore/`、shared deck service；catalog contract 見 discover boundary。
- Shared UI／tokens：`Components/`、`DesignSystem/`、`design-system/tokens.json`。
- Localization：`L10n` 與 `ops/i18n_lint.sh`；禁止新增 raw user-facing strings。

## Operational entrypoints

- Build／test：`ops/ios_ops.sh`、`ops/ios_build.sh`、`ops/ios_test.sh`。
- UI flow evidence：`.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh`、`.claude/skills/ios-simulator-verification/references/evidence-contract.md`、`docs/sop/ui_flow_evidence.md`；lease pool 無 slot 時以 `status=result=inconclusive`、typed `exit=65`、`helper.contractStatus=lease-exhausted` 與 `--device <UDID>` recovery hint 回報，不能當成測試失敗。
- P9 Review Calendar evidence：`p9_review_calendar_evidence.py` 的 `validate` CLI（`uv run --python 3.13 python ops/p9_review_calendar_evidence.py validate <manifest> --workspace-root <run-root> --outer-verdict <verdict.json>`）驗證 `kg.p9.review_calendar.review_manifest.v2` sidecar、重新 hash 截圖與 app materialized fixture，並 exact-match outer verdict 的 `p9ReviewCalendarEvidence` artifact。UI evidence producer 傳遞 `KG_UI_TEST_APP_ARGS_JSON`、`KG_UI_TEST_SOURCE_COMMIT`、`KG_UI_TEST_DATASET_ID`、`KG_UI_TEST_DATASET_SHA256`、`KG_UI_TEST_DEVICE_UDID`、`KG_UI_TEST_SCREENSHOT_DIR`；app proof path 由 `KG_P9_INSTALLED_FIXTURE_PROOF_RELATIVE_PATH` 控制（相對 Documents，預設 `Evidence/<datasetID>.json`）。runner 在 validation 前唯讀取回 app 寫入的 proof。
- iOS Sentry／agent diagnostics：`ops/ios_ops.sh sentry`、`ops/sentry_tool.py`、`ops/sentry_api.py`、`ops/sentry_contract.py`。
- UI quality：`ops/ui_quality_plane.py`、`ops/ui_quality_gate.py`、`ops/ios_ops.sh quality`。
- Lint／scan：`ops/docs_lint.sh`、`ops/i18n_lint.sh`、`ops/shell_scan.sh`、`ops/python_scan.py`。
- Worktree：`ops/lib/worktree_scope.py`、`ops/worktree_registry.py`（相容 CLI facade）、`ops/worktree_registry_core/`（admission／records／handback／lifecycle／storage／parser）、`ops/worktree_orchestrate.py`。
- Delivery control：`ops/delivery.py` 是 JSON command 入口；`inspect`／`metrics`／`plan` 觀測與規劃，`dogfood-preflight` 驗證四角色 clean-slate canary baseline（supervision checkout 必須用 exact `--supervision-worktree` manifest 明確排除），`watchdog` 以約 300 秒 tick 做唯讀 liveness 決策，外部 scheduler 以 `watchdog-claim` 在 dispatch 前原子保留唯一 wake，`render-candidate-body`／`validate-candidate-body` 維護 typed Issue supply，`receipt`／`publish`／`release-published`／`trigger-required`／`queue`／`cleanup-merged`／`sync-main` 執行 exact typed transaction，`validate-pr-body` 供 PR readiness 綁定 machine receipt 與 HEAD。published PR 的 same-owner code-fix／merge-front 恢復分別走 `ops/worktree_orchestrate.py resume-published`／`reanchor`，共用小型 `ops/worktree_reanchor_core/` transaction 模組，不在 delivery CLI 內混入 worktree mutation。
- Bounded local compute：`ops/compute.py` 的 `plan`／`run`／`status` 只依 `ops/compute_profiles.yml` 執行 clean committed tree 上的 literal argv；`ops/lib/compute_contract.py` 驗證 runner provenance、參數與 side-effect contract，禁止 remote、shell 與 production mutation。
- Long-task safety：`ops/task_registry.py`、`ops/lib/streaming_command.py`（只記 process ownership／heartbeat，不記產品工作狀態）。
- Ops regression：`ops/test_ops.sh`。
- Backend venv health：`uv run --no-project --python 3.13 ops/venv_health.py`；檢查必需的 main `backend/.venv`，並對缺少或失效的 Python、pytest、`uv.lock` 或 dependency probe fail closed。
- Safety／release：`ops/devops_kg_safe.sh`、`ops/release.sh`、`ops/kg_reconcile.sh`、`ops/branch_audit.sh`。
- App Store Connect：`ops/asc.sh`；metadata／submission limitations 以 `docs/sop/ios.md` 為準。

## Configuration and domains

不要在索引內寫秘密值。host、domain、container、port 與 tunnel 以 `docs/reference/host_topology.md` 為準；deployment、migration、health、rollback 以 `docs/sop/deploy.md` 與 `docs/policy/safety.md` 為準；CloudKit／sync 以 `docs/reference/sync_lifecycle.md`；card／CSV 以 `docs/reference/card_format.md`；backend／iOS test strategy 以 `docs/reference/testing/`。

## Change rule

先讀 code 與對應 SoT，再做修改；變更 agent-facing command、flag、env 或 schema 時，跑 `./ops/docs_impact.py --surface-scan` 與 `./ops/docs_lint.sh`。若入口不存在，修正索引與 tests，不留下指向已刪除工具的說明。
