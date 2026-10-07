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
| CI | `.github/workflows/pr-readiness.yml`、`.github/workflows/pr-gate.yml`、`.github/workflows/merge-group-required.yml`、`ops/ci_scope_router.sh`（亦輸出 fail-closed 的 `ios_mode`／`ios_selectors`，targeted 只限單一頂層 `*UITests.swift` 且經 `ops/ios_test.sh --ui --list --file` 探得 `Target/Suite/Method`，其餘全回 `full`）、`ops/ci_confidence_verdict.sh` | typed receipt／exact HEAD readiness；PR 與 merge-group blocking `required`；diff-scoped nonblocking advisory `confidence` |

## Backend routes and data

- API routers：`backend/src/kg/routers/`；schemas／response models：`backend/src/kg/api_models/`。
- Vocabulary intake／CRUD／sync：`backend/src/kg/vocab_*.py`、`backend/src/kg/vocab_handlers/`；missing-target Add Link 的 durable composite operation 在 `backend/src/kg/vocab_add_link_operation.py`，request／status schemas 在 `backend/src/kg/api_models/vocab_add_link.py`。A 的原始 context 只作 B 的 sense-disambiguation 參照，不落地成 B 的例句或關係文案。
- Graph links：`backend/src/kg/graph_*.py` 與 vocabulary router；`POST /api/graph/links/ensure-target` 只 enqueue、`GET /api/operations/{operation_id}` 讀取狀態，詳情以 `docs/reference/sync_lifecycle.md` 為準。 operation 終態 `interrupted`（`errorCode=interrupted`，取代舊 `cancelled`）涵蓋 shutdown 取消與重啟孤兒：app lifespan 在 worker 鎖後把所有非終態 operation 標為 `interrupted`，client 以新 Idempotency-Key 重試；`failed` 的 `errorCode` 另有 `target_archived`、`target_is_source`、`source_unavailable`（不再併入 `target_unavailable`），`enrichment_failed` 只出現在 `warnings`。
- Podcast：`backend/src/kg/podcast_*.py`；生成與音訊工作流在 `lab/podcast/`。
- Provider registry／費率：`backend/src/kg/llm/providers.py`；變動同步 `docs/reference/cost_baseline.md`。
- Database／migration：backend migration entry 與 deployment SOP；不要從本文件猜資料表或直接拼 SQL。
- Runtime SQLite data root：`backend/src/kg/runtime_data_root.py`。app lifespan 取得 worker 鎖並跑完 startup reaper 後 bind `settings.data_dir`，shutdown 在釋放鎖前 release；store 以 `runtime_data_root.current()` 組路徑，未 bind（CLI／ops 工具）才回落 `KG_DATA_DIR`。已接入 `pipeline_log`、`vocab_add_link_operation`。
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
- Delivery control：`ops/delivery.py` 是 JSON command 入口；`inspect`／`metrics`／`plan` 觀測與規劃，`dogfood-preflight` 驗證四角色 clean-slate canary baseline（supervision checkout 必須用 exact `--supervision-worktree` manifest 明確排除），`watchdog` 以約 300 秒 tick 做唯讀 liveness 決策，外部 scheduler 以 `watchdog-claim` 在 dispatch 前原子保留唯一 wake，`render-candidate-body`／`validate-candidate-body` 維護 typed Issue supply，`receipt`／`publish`／`release-published`／`trigger-required`／`queue`／`cleanup-merged`／`sync-main` 執行 exact typed transaction，`validate-pr-body` 供 PR readiness 綁定 machine receipt 與 HEAD。published PR 的 same-owner code-fix／merge-front 恢復分別走 `ops/worktree_orchestrate.py resume-published`／`reanchor`；尚未 publish 的 owner hand-back 若需對齊新 main，走同檔 `reanchor-handback`，在 local rebase 前後都驗證遠端 `origin/main`，共用小型 `ops/worktree_reanchor_core/` transaction 模組，不在 delivery CLI 內混入 worktree mutation。
- Bounded compute：`ops/compute.py` 保留 `plan`／`run`／`status` local CLI，並以 `ops/lib/compute_router.py` 做 deterministic `local`／`auto`／`felix` placement；`ops/lib/compute_contract.py` 驗證 clean source、literal argv、runner provenance、參數與 side-effect contract，`ops/lib/xmachine_transport.py` 只呼叫固定 launcher（literal argv、shell=false，job id／digest／profile key／參數皆獨立 argv element），並由 Oscar 以 registry 內 pinned Ed25519 public key 驗證 Felix receipt 的 signature、nonce、request digest、source／spec／runner、freshness、log digest 與 replay ledger，先原子落檔再送 one-time HMAC ACK；admission 只來自 live probe（過期、未知、同機皆 fail closed 到 local），子程序啟動後失敗不自動 local retry。結果只落目前 worktree 的 `.cache/compute/`，不做 remote agent scheduling 或 production mutation。`auto` 的成本模型只讀 `.cache/compute/history.ndjson`（`ops/lib/compute_history.py`，append-only NDJSON、flock＋fsync、>2000 行壓縮為每 profile 最近 50 筆）：只有驗證通過且 returncode=0 的 local／felix run 才寫入（selftest／plan／status／失敗／被拒皆不寫，寫入失敗不影響 run 結果與 exit code）；local 預估取近 14 天內最新 ≤20 筆 local 秒數的中位數且至少 3 筆，felix transfer 取 probe 值、缺則取近 14 天 felix 紀錄的中位數；壞行、未來時間、過期、稀疏或缺 transfer 一律不可用並 fail closed 到 local（`auto-local-cost-unknown`），router 規則不變。固定 launcher 是 `ops/felix_compute_launcher.py`（`probe`／`submit`／`fetch`／`ack`）：Oscar 端為 relay，只執行一條無動態值的固定 ssh 命令，請求與 clean-committed-tree capsule 走 stdin；Felix 端（`exec`，限 `ops/lib/compute_hosts.py` 封閉表內的 felix）只接受封閉 profile registry、重算 spec／request／tree digest，於 network-none／read-only／non-root 容器執行，以 Felix 本機 0600 Ed25519 私鑰（`KG_FELIX_RECEIPT_KEY_FILE` 或 `~/.kg-compute/receipt-ed25519.pem`，缺失即 fail closed，永不入 repo／log）簽 receipt，one-time ACK 後清除 job；`keygen` 只印公鑰。`./ops/compute.py selftest --target felix --profile source-identity --json` 是唯一 live 跨機證明（僅 `source-identity`，shipped `remote_eligible=false`，registry 未 pin `felix_receipt_public_key` 前一律 fail closed 並給具名 code）。
- Project health：`ops/doctor.py` 是唯讀的單一健康報告（`--json`；exit 0/1/2＝ok/warn/blocker），只做其他工具沒有的判斷：每個 workflow 在 main 上的連續紅燈（known-red：≥3 次且 ≥3 天）、production 版本（`/api/system/info`）落後 main 的 commit／天數、registry 的 ghost／ownerless claim、disk guard、open issue 是否有可執行的驗收指令；`--run-acceptance` 才會執行驗收指令，且只對 repo owner 開的 issue（issue 文字是資料，任何人都能開），不會寫入 repo、registry 或 GitHub。每個 session 開場先跑它。
- One-command delivery：`ops/deliver.py --check 'label=cmd' [--merge]` 只串接既有工具（`worktree_orchestrate.py`／`delivery.py`／`gh`），不自存狀態：每次由 registry 與 GitHub 回推所在階段，失敗後原樣重跑即續做。流程 checks → adopt → hand-back → receipt → publish → 等 `required`；加 `--merge` 才 queue、等合併、`cleanup-merged`、`sync-main`。`--merge` 在 queue 前先等 PR exact head 上的 `agent-review` 收斂（讀該 SHA 全部同名 check run：Actions job 未完成或尚無結論即等待，被取消 run 遺留的 in_progress verdict marker 不算），review 失敗、或 review bot（帳號讀自 `agent-review.yml`）在該 head 留有 inline comment（`commit_id`／`original_commit_id` 等於 head）就拒絕 queue 並列出每則 `path:line`、標題與連結；只有 `--accept-review-findings '<reason>'` 能放行，理由寫進 log 與結果的 `review` 欄位；`neutral`（reviewer 未出現）視為 advisory、不擋。hand-back 的 outcomes 只來自本次實際執行的 `--check`（exit code＋輸出末行），無法手填；check 失敗、髒樹、main 分支、無法乾淨 rebase 皆在 claim 前拒絕。任一階段失敗時錯誤全文輸出、不截尾：`delivery.py` 的 `ok:false` JSON 取整段 `error`（底層 GitHub 訊息常接在很長的 GraphQL query 之後），其他命令輸出完整 stderr／stdout。delivery／registry／worktree mutation 撞上 `delivery mutation already in progress`（operation lock 在任何變更前取得，被拒的嘗試什麼都沒做）時，每 5 秒重試並印出持有者，最多 `--lock-timeout` 秒（預設 600），逾時才以完整錯誤失敗；其他失敗不重試。`deliver.py gc [--dry-run]` 對「published、worktree 已消失、PR 已 merged」的 lane 跑 `cleanup-merged`（即 doctor 報的 ghost claim）。Scope 一律由 worktree 對 `origin/main` 的 diff 推得（`worktree_orchestrate.py adopt --scope-from-diff` 同理；`deliver.py --scope-from-diff` 另會在 hand-back 前刷新已 adopt 的 active claim 的 Scope）；adopt 以 `origin/main` 為 base，若既有 active claim 的 `base_sha` 不是分支與 `origin/main` 的 fork point（舊的本機 `main`），會以 `resolve --status abandoned` 退役後重新 adopt；`--branch` 續跑遇 PR 已 merged 且無待清理 claim 時直接停止並要求從 `origin/main` 開新 lane。`cleanup_pending` 且 PR 已 MERGED（head 為預期 HEAD；或 remote branch 已消失且從無任何 PR 紀錄，CLOSED-unmerged 須走 closed-PR disposition）的 lane，可用 `worktree_orchestrate.py resolve --status abandoned` 退役，證據由指令自行查證；registry CLI 本身不接受退役證據參數，只有 orchestrator 驗證後以 in-process 傳入。測試在 `delivery-control` 群組（`ops/tests/test_delivery_deliver.py`）。
- Release preflight：`ops/release_train.py`（唯讀，`--json`；exit 0/1/2＝ready/warn/blocked，`--skip-remote` 不 ssh felix）回答「現在能不能推 origin/prod」，每項檢查對應一次真實踩坑：main 紅燈／未同步、`origin/prod` 不能 ff（reconciler 用 `--ff-only`）、release 必碰的 `backend/src/kg/api.py` 未格式化（PR gate 只格式化變更檔，candidate PR 會紅）、felix `~/kg-prod` 與 `origin/prod` diverged（歷史被改寫，ff-only 會拒絕部署）、reconciler dry-run／launchd 狀態、live 版本是否已在上次 release、24h 內備份、production env、範圍內的 auth／billing／LLM／handler 檔案（出貨需 owner 明確同意）。測試在 `doctor` 群組（`ops/tests/test_release_train.py`）。
- Complexity budget：`ops/complexity.py`（`check`／`ratchet`／`show`）以 `ops/complexity_budget.json` 的行數上限（只算 `.py/.sh/.md/.yml/.yaml/.swift` 等人寫的程式碼與文件，fixture、plist 等資料檔不算，重新產生資料不得讓閘門變紅）約束 `ops/`、`docs/`、`.github/workflows/` 不會無聲膨脹（並回報 ops:ios 比值，目前約 1.2＝工具行數仍大於產品行數）。`ops/tests/test_complexity.py::test_the_repository_is_within_its_complexity_budget` 在 `doctor` 群組內執行，超標即紅；解法只有兩種且都留在 PR 內可審視：刪掉東西，或在同一 PR 提高 ceiling 並寫明理由。`ratchet` 只會把 ceiling 往下收（刪除的額度入帳、不可被再次無聲花掉），`doctor.py` 另顯示 headroom 最小的區域。
- Weekly health report：`.github/workflows/health.yml` 每週一（及手動 dispatch）跑 `./ops/doctor.py --ci --json`（`--ci` 略過只存在開發機的檢查：checkout 狀態、claim、disk guard），再由 `ops/doctor_issue.py` 讓**唯一一張** label 為 `health-report` 的 issue 與報告同步：出現 warn／block 就建立、內容變動才更新、全部 ok 就自動關閉並留言，未變動不動作（無週報噪音）。`doctor.py` 計算 open issue 時排除該 label（避免自我參照）。`--dry-run` 只印決策。測試在 `doctor` 群組（`ops/tests/test_doctor_issue.py`）。
- Delivery metrics：`ops/delivery_metrics.py` 由 `doctor.py` 的 `delivery` 區塊呈現（本機與 `--ci` 皆有）：近 28 天合併 PR 數與每週速率、PR 建立→合併的中位數／p90 與近兩週對前兩週的趨勢、近 28 天關閉 issue 的開啟→關閉時間（requester 等待時間，含 PR 之前的一切）、api 版本 commit 的發版節奏。發版節奏是**代理指標**（`origin/prod` 只是指向 main 的指標、沒有前進歷史）；發版後失敗率沒有可靠資料來源，刻意不猜。只對 PR 中位數 >24h 或 p90 >72h 警告，issue 時間先不設門檻（等累積數週穩態資料）。完整摘要每週寫入 `health` workflow 的 run summary。測試在 `doctor` 群組（`ops/tests/test_delivery_metrics.py`）。
- Long-task safety：`ops/task_registry.py`、`ops/lib/streaming_command.py`（只記 process ownership／heartbeat，不記產品工作狀態）。
- Ops regression：`ops/test_ops.sh`。
- Backend venv health：`uv run --no-project --python 3.13 ops/venv_health.py`；檢查必需的 main `backend/.venv`，並對缺少或失效的 Python、pytest、`uv.lock` 或 dependency probe fail closed。
- Safety／release：`ops/devops_kg_safe.sh`、`ops/release.sh`、`ops/kg_reconcile.sh`、`ops/branch_audit.sh`。
- App Store Connect：`ops/asc.sh`；metadata／submission limitations 以 `docs/sop/ios.md` 為準。

## Configuration and domains

不要在索引內寫秘密值。host、domain、container、port 與 tunnel 以 `docs/reference/host_topology.md` 為準；deployment、migration、health、rollback 以 `docs/sop/deploy.md` 與 `docs/policy/safety.md` 為準；CloudKit／sync 以 `docs/reference/sync_lifecycle.md`；card／CSV 以 `docs/reference/card_format.md`；backend／iOS test strategy 以 `docs/reference/testing/`。

## Change rule

先讀 code 與對應 SoT，再做修改；變更 agent-facing command、flag、env 或 schema 時，跑 `./ops/docs_impact.py --surface-scan` 與 `./ops/docs_lint.sh`。若入口不存在，修正索引與 tests，不留下指向已刪除工具的說明。
