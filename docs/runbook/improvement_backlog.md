<!-- doc-meta
tier: runbook
authority: SoT
update_trigger: manual
scope:
  - .claude/agents/platform-steward.md
  - .claude/skills/kg-receipt/
verified_against: febc68ebb
-->
# 改善 Backlog（kaizen ledger）

> 自我提升迴圈的 **SoT**:所有「工具 / CLI / 文檔 / 架構」摩擦的 open 問題單一登記處。
> 原則見**鐵律9**(摩擦優先修工具)、分級見 `kg-router`「Tool Friction」、表態見 `kg-receipt`「Tooling Debt」——本文**不複述**,只負責**持久化、追蹤、收斂**。

## 為什麼存在

receipt 裡的 tooling debt 會隨 transcript 蒸發。本 ledger 讓每個 raised 問題**進 git、可回溯、有 owner、追到 resolved**,杜絕 agent 無聲妥協(硬幹)。owner = `platform-steward`(Staff)。

## Andon — 任何節點怎麼提一筆

1. 撞到摩擦 → 先第一性原理判根因(鐵律9),分級(kg-router「Tool Friction」)。
2. 在 receipt 表態(規則見 `kg-receipt`「Tooling Debt」)。
3. 非 trivial 且未當場修掉 → 由上一階 / `platform-steward` 追加一列到下表。
4. 中大型 / 結構級 → 不只登記:停手修工具,或升級上一階(鐵律9 + `docs/sop/agent_org.md`「反硬幹升級階梯」)。

## Entry schema

- `status`: `open` → `triaged` → `in-progress` → `fixed` / `wont-fix`(附理由)
- `category`: `tool` / `cli` / `doc` / `arch`
- `severity`: `low` / `med` / `high`
- `resolution`: 解決 commit hash,或 wont-fix 理由(這是「可回溯」的關鍵欄)
- resolution hash 慣例:PR 合併前為 branch-local;若該 PR 採 **squash merge**,合併後由 `platform-steward` 更新為 squashed hash,維持 audit trail 不斷。

## Ledger

| id | date | source | category | severity | status | detail | resolution |
|---|---|---|---|---|---|---|---|
| IMP-0001 | 2026-06-13 | docs-steward 首測 | doc | low | fixed | agent 檔寫「依 kg-receipt 格式」但未給欄位指標,靠 brief 餵 | `7c95a02`(補欄位指標) |
| IMP-0002 | 2026-06-13 | review gate | doc | low | fixed | agent_org.md 3 處 borderline 複述鐵律判準 | `3671b89`(收斂為純指標) |
| IMP-0003 | 2026-06-13 | docs-steward 首測 | cli | low | triaged | `docs_impact.py` 對 CLAUDE.md 純政策段新增穩定產生 5 條 exact 誤報(`via=CLAUDE.md`);hint≠命令故不阻擋,但每次需人工判讀 | open — 候選 enhancement:registry 對 CLAUDE.md source 加 section-anchor 機制 |
| IMP-0004 | 2026-06-13 | backend-engineer smoke | tool | low | wont-fix | 首次 `uv run` 觸發 .venv bootstrap(~100MB),新 worktree / CI 首跑有感 | 正常行為,快取後即解;不修 |
| IMP-0005 | 2026-06-13 | kaizen-loop review gate | cli | low | fixed | `docs_lint.sh` 不接受裸 doc 路徑當位置參數(`docs_lint.sh foo.md` → Unknown arg),已加可接受裸路徑並保留清楚提示 | `813356b1` |
| IMP-0006 | 2026-07-08 | iOS 2.0.0 發版檢討 | tool | low | fixed | `asc.sh`/`ios_release.sh` 靜默吞 ASC API 錯誤(403 agreement 無輸出 exit 1) | `ef5fcfb00`(fd3 透出+403 GUI 指引+test_asc §17) |
| IMP-0007 | 2026-07-08 | iOS 2.0.0 發版檢討 | arch | med | fixed | 升級觸發清單漏「執行中發現 human-only 動作」,blocker 批到 receipt 才告知(ASC 403 損失 40 min 可平行人工時間) | `9a8209a4c`(agent_org.md 補即時升級觸發)+`fbf2221cb`(review 修正) |
| IMP-0008 | 2026-07-08 | iOS 2.0.0 發版檢討 | arch | med | fixed | 委派無成本下限,trivial 工作也燒全套 agent+receipt | `9a8209a4c`(agent_org.md 補 trivial 門檻)+`fbf2221cb`(trivial vs 豁免釐清) |
| IMP-0009 | 2026-07-08 | iOS 2.0.0 發版檢討 | doc | low | fixed | 逐項 review 固定檢查項靠 GM 每次手寫 brief,重複且易漏 | `9a8209a4c`(code-reviewer.md 內建 checklist)+`fbf2221cb`(SoT 收斂:複述→指標) |
| IMP-0010 | 2026-07-08 | iOS 2.0.0 發版檢討 | cli | med | fixed | `release.sh bump` 跑了立即寫檔,違 dry-run 預設慣例(實際咬人:預覽即污染 pbxproj) | `34cd97866`+`9c88b55b2`(dry-run 預設+--yes+全面語意同步+迴歸) |
| IMP-0011 | 2026-07-08 | iOS 2.0.0 發版檢討 | cli | low | fixed | `ios_test.sh --ui` 缺 dataset 錯誤不列可用清單,需二次查找 | `27d61ecb5`+`d56efeabe`(錯誤附 ui_worlds 名單+set -e 防死+迴歸) |
| IMP-0012 | 2026-07-08 | iOS 2.0.0 發版檢討 | doc | low | open | `docs/sop/ios.md` §UI World dataset 契約為單行 ~4000 字牆,知識密度高但不可讀不可維護;候選:結構化為表格+分節 | — |
| IMP-0013 | 2026-07-08 | 版本控制盤點 | cli | med | fixed | api 元件版號分叉:tag api/1.6.0 vs pyproject 0.1.0,339 筆 commit 未發版(版本真相兩處互相矛盾) | `208e41437`(bump+tag api/2.0.0,漂移清零) |
| IMP-0014 | 2026-07-08 | 版本控制盤點 | cli | low | fixed | 同版重送(被拒後最高頻操作)無 build-only bump typed 入口,須手改 pbxproj | `9578d9cb0`+`2cd12c8de`(release.sh bump-build ios,dry-run 預設+11 斷言+docs 同步) |
| IMP-0016 | 2026-07-08 | Phase 1 review(world-export) | tool | low | open | Card/Notebook schema 變更無 lint 抓「export/seed 未同 PR 對齊」→ roundtrip 靜默有損;現靠 ops_state_plane §1.1 紀律 + roundtrip 測試抓 export 側漏導。符合 gate 刻意延後政策([[ops-gate-enforcement-deferred-by-design]]),升級訊號=同錯第三次 | — |
| IMP-0017 | 2026-07-08 | ops-engineer（spec 投影 Phase 2） | tool | med | open | `ios_test.sh` 在 set -e + pipefail 下任何內部管線非零會**靜默中止且 exit 0**（cleanup trap 吞 exit code、無錯誤輸出）——cache-key 缺檔觸發點已修（`4d11a11d2`），但「mute rc-0 abort」這一類故障模式仍在:任何未 `|| true` 防護的管線都可能無聲假綠。候選:EXIT trap 保留原 exit code + set -e 中止時印 stderr 診斷行（兩度撞號:原 IMP-0013→改 0014 又撞 release 盤點→定 0017） | — |
| IMP-0015 | 2026-07-08 | rebase 收斂事故(92da32e64) | cli | med | fixed | `docs_lint.sh` 對 changed docs 不掃 git 衝突標記（`<<<<<<<`）也不驗 `verified_against` hash 在 main 可達——衝突標記+不可達 hash 雙雙進 main 而 lint 全綠（當次資料修復見 6cec330c8）。兩檢查都已進日常 gate | `c6c1b1619`(衝突標記 gate + 修 5 個 invalid verified_against)+`a4a100603`(verified_against HEAD 可達性，堵 rebase 後 orphan anchor 假綠) |
| IMP-0018 | 2026-07-08 | deflate 修復(c272101c9) | tool | med | fixed | `ui_world_manifest.py validate` 與 Swift decoder 有 nullability gap:todayReview `dateAdded` null 過 validator 卻在 app preconditionFailure——validator 應對齊 Swift date 非空要求 | `6a9761d5e`(validator dateAdded 必填 + spec_world 非空導出)；`5a25ae6ac` 追加 graph link in-seed 驗證（同類 nullability/dangling gap） |
| IMP-0019 | 2026-07-08 | deflate 修復(c272101c9) | tool | med | fixed | catalog content-pinned seeds（wordDetail/wordEdit/search/archived 等釘死特定內容的 scenario）無 pre-flight 檢查,world 覆蓋 pinned domain 只能跑到該 surface 才 fatal;候選:emit/validate 層列舉 pinned fixture 清單並擋覆蓋 | `6a9761d5e`+`5a25ae6ac`(emit 層:vocabulary 8 個 + reviewDeck probe/notebookReviewDeck 共 10 個 pinned fixture 入 SPEC_BASELINE_KEPT_FIXTURES,spec 模式強制 byte-equal baseline;standalone validate 不驗 pin——pin 是 spec 投影語意,非 world 格式契約) |
| IMP-0020 | 2026-07-08 | deflate 修復(c272101c9) | cli | low | open | `catalog snapshots --reuse-build` 在「cache hit 但 test run 失敗」時回 `status:"cache-miss"`,語意誤導（實為 run failure） | — |
| IMP-0021 | 2026-07-09 | spec_world 修復 review(5a25ae6ac) | tool | low | open | `ui_world_manifest.py` 對 vocabulary/reviewDeck 的 graphLinksByKind **link 元素**無 schema 驗證（只驗頂層 Mapping[str→list]）:非 str word/cardId 或非 mapping link 會雙層靜默放行,Swift decode 才炸;todayReview link 已有 `_validate_today_review_link` 全鍵驗證,建議比照補上 | — |
| IMP-0022 | 2026-07-09 | 行銷帳號 Phase5(felix 漂移) | tool | med | open | felix 生產後端 git HEAD 靜默落後 origin/main 80 commits(0cea7f67 vs main),無任何告警。stale 容器的 `ops-edit seed` 舊碼**靜默丟棄** spec 的 counter-form 複習日期(review_count>0=0、next_review_at 全 null)、不合成 review_events(heatmap/streak=0)、不做 is_default→default remap(多殘留空 notebook)——差點注入「看起來全新未使用」的行銷帳號。本 session 已 deploy felix→main(0611f3ca)解當下阻塞,但**監控 gap 仍在**。候選:`devops_kg_safe.sh health` 加「commits behind main」metric + warn 閾值,讓生產漂移顯式化。 | —(deploy 0611f3ca 解當下;monitoring 候選未做) |
| IMP-0023 | 2026-07-09 | 行銷帳號 Phase5(backup) | cli | med | open | `devops.sh cmd_backup`(line 596)無條件用 GNU-rsync 專屬旗標 `rsync -az --delete --info=progress2 --human-readable`,macOS 內建 openrsync 不支援 `--info=progress2`(`unrecognized option`)→ 從 oscar 跑 `devops_kg_safe.sh backup` 直接失敗、備份命令不可用。候選:偵測 rsync flavor(GNU vs openrsync)擇旗標,或改用兩者皆支援的 `--progress`,或該旗標包 `\|\| true` 降級。 | — |
| IMP-0024 | 2026-07-09 | 行銷帳號 Phase5(reshape 機制) | cli | med | open | `ops-edit seed` 為 additive-upsert,`CardStore.add` 查重綁 `notebook_id`(`cards/mutations.py:51-55`)→ 對「卡已存在但在別的 notebook」會**新增重複卡**而非搬移;把一個既有帳號 reshape 成 spec(結構不同時)會造大量重複卡且 verify_fn 報綠(false-green)。現只能靠「seed 一個 throwaway scratch → clone-demo 原子替換」的迂迴。候選:`ops-edit seed --replace <uid> <spec>`——單一 EditContext 內先 wipe 整層 vocab(複用 clone-demo 的 `_is_vocab_file` 移除,含 review_events.db)再 seed,self-verifying,把 spec→exact-state 收成一個原語。 | — |
| IMP-0025 | 2026-07-09 | 行銷帳號 Phase5(scratch 清理) | cli | low | open | 無 `ops-edit user-delete` 原語 → reshape 用的 throwaway scratch 帳號(及一般 demo 帳號)會殘留在 users.json(`_` 前綴者 `is_real_user=False` 自動隱藏於 fleet-overview,但實體條目仍在),只能靠手寫 scoped script 清(本 session 即如此)。候選:`ops-edit user-delete <uid>`(移 user dir + users.json 條目 + email/subscription index scrub,dry-run 預設、寫前自動備份)。 | — |
| IMP-0026 | 2026-07-09 | 行銷帳號 Phase5(驗證) | cli | low | open | `ops-cli world-diff` 硬性要求 `schema==kg.ops_world_expectation.v1`(`ops_world_diff.py:18`),無法驗「帳號 == seed_spec」(注入格式是 `kg.seed_spec.v1`)。缺一個 first-class「reshape 是否精確落地」檢查,只能靠 `world-export` + 外部 normalized diff 橋接(本 session 自寫 python 比對)。候選:教 world-diff(或新 world-verify)吃 seed_spec,或 seed/clone-demo 自吐比對 verdict。 | — |
| IMP-0027 | 2026-07-09 | 行銷帳號 Phase5(provenance) | tool | low | fixed | 行銷 spec provenance 曾未 pin，無機制保證「重建／注入的 artifact == 被審核的 artifact」。現由 tracked source spec + history plan 重建，要求生成 dataset SHA 精確等於 release spec，reviewer bundle 再封閉綁定 profile / dataset / render spec / 每張輸出 digest；live-demo identity 另沿 spec→ASC mirror→runner→receipt 同一 SHA 收斂，故不另開重複的 closed-world debt。 | `98ec95539`(typed producer + exact reviewer-bundle closure)+`4d320ff5b`(live identity closure) |
| IMP-0028 | 2026-07-09 | 行銷帳號 Phase5(時鐘凍結對抗驗證) | tool | med | fixed | iOS `SettingsCoordinator.applyServerReviewClock`(`SettingsCoordinator.swift:113`)用 strict `AppDateFormatters.iso8601`(要小數秒)解析伺服器 `paused_at`,而非旁邊的 `AppDateFormatters.parseISO8601` fallback(`AppDateFormatters.swift:56-57`)→ 缺小數秒的 `paused_at` 靜默回 nil → 凍結退回 wall-clock 卻仍報 is_paused=true(false-green)。本 session 注入用 `.000Z` 規避,但潛伏 bug 仍在。**已修復**:改用 `AppDateFormatters.parseISO8601`(小數秒優先 + 不含小數秒 fallback),對稱寫入側恆產小數秒;TDD 兩案回歸測試(有/無小數秒)。 | bb45e0f85(#981;rebase onto main 後 CI ui-quality-gate pass、squash merge) |
| IMP-0029 | 2026-07-09 | 行銷帳號 Phase5(時鐘凍結對抗驗證) | arch | low | open | iOS 伺服器 review-clock push 只在 cold-start 套用(`SettingsCoordinator.swift:111` gate `pauseClockSnapshot.updatedAt == nil`)+ `KGFeatureFlags.serverReviewClockLwwEnabled` dead-`false`(`KGFeatureFlags.swift:27`)→ **任何曾本地 toggle 過複習時鐘的裝置,伺服器凍結會被忽略**。屬當前同步狀態的 by-design(LWW 未啟用),非 bug;行銷截圖走 catalog fixture(offline UserDefaults seed 恆套用)故不受影響。候選(產品決策):是否讓 server-authoritative review-clock LWW 出貨。 | —(by-design,待產品決策) |
| IMP-0030 | 2026-07-10 | Explore P1 docs-sync | tool | med | open | `ios_test.sh --ui <bareMethod>`(裸方法名)對**不在** class `BooksAndVocabUITests` 的 UITest method 回 `tests=0` 卻 exit 0(**FALSE GREEN**):bare method 只在預設 suite 內解析,別的 UITest class(如 `ExploreNavigationUITests`)的 method 靜默零執行、假綠。workaround=用完整限定 `Class/method`。fix 候選:runner auto-resolve method→其所屬 class,或 `--help`/零匹配錯誤明示「bare method 僅限預設 suite,跨 class 用 Class/method」 | — |
| IMP-0031 | 2026-07-13 | iOS 2.0.1 誤標事故 | cli | high | fixed | `release.sh` 把 iOS semver 建議當成可執行 release，未要求 previous marketing version 已完成審查的 typed attestation，且先 tag/push 再 upload；被拒中的 2.0.0 因而可被誤升 2.0.1，upload 失敗也會留下 false release marker | `6ff5bcf10`(離線 `--new-version-after-ready` guard + semver 單調性 + upload-before-tag + 71 斷言) |
| IMP-0032 | 2026-07-14 | App Review 2.0.0 evidence producer | cli | med | fixed | `app_review_evidence.py` 的 desired shape/build/bundle、journey、physical demo、gate evaluation 曾以 `capture_output=True` 靜默等待。現統一走 bounded streaming runner：stderr 最長每 20 秒回 phase/elapsed/PID/alive，stdout 保持單一 JSON；raw argv 不進 progress，中斷會清整個 isolated process group。 | `4e2e89b55`(producer heartbeat + stdout purity + secret/process-group adversarial regressions) |
| IMP-0033 | 2026-07-14 | App Review 2.0.0 Release iphoneos compile gate | cli | high | fixed | `ios_ops.sh test --ui --configuration Release --destination generic/platform=iOS --prepare-cache --json` 曾在 xcodebuild exit 0、iphoneos xctestrun 與兩個 `.app` 都存在時，同份 JSON 回 `status:"prepared"` 與 `productsReady:false`。根因＝readiness predicate 以 `platform=iOS,`（**帶逗號**）判 device SDK，comma-less 的 `generic/platform=iOS` 落回 iphonesimulator。調查發現嚴重度高於原評：**雙向錯誤**（iphonesimulator 產物會被當成 device build 的證據）、sentinel 走同一 predicate 故該 cache 永久冷、且 `prepare` 硬寫 `"prepared"` 而只有 `status=="error"` 才 exit 1 → `worktree_orchestrate` 的 live-only Release compile **block** gate 在「build exit 0 但零產物」時仍綠（假綠）。順帶修 `--json` 下 progress banner 污染 stdout。 | `febc68ebb`(`ios_test_sdk_suffix` seam + `ios_test_prepare_status` 導出 status + stdout 純度 + hermetic iphoneos fixture 迴歸；365 passed/0 failed) |
| IMP-0034 | 2026-07-14 | App Review 2.0.0 worktree gate | tool | med | fixed | 修改 `LiveDemoAccessUITests.swift` 時，cutover 原先誤套 Debug simulator + marketing fixture，與該測試的 Release / physical / no-fixture 契約必然衝突。現 live-only class 改走 Release generic-iOS compile gate，runtime evidence 明示交給 `app_review_evidence.py demo-run`。 | `534acb68a` |
| IMP-0035 | 2026-07-14 | App Review 2.0.0 live runner review | tool | high | fixed | live-demo staging 曾把 account identity marker/hash 注入 xctestrun 的所有 test targets，權限面大於固定 live-only method。現先 sanitize/scan 每個 configuration/target，只注入唯一 `BlueprintName=BooksAndVocabUITests` target；0 或多個匹配在注入前 fail-closed，其他 target 保留 key-absent。 | `30df7f5f1` |
| IMP-0036 | 2026-07-17 | App Review evidence worktree gate | cli | med | fixed | `worktree_orchestrate.py gate` 曾把每個 shell gate 的合併輸出靜默 capture 到結束；長 iOS/pytest gate 無 PID/heartbeat，操作者無法分辨排隊、執行或卡死。現共用 bounded streaming runner，stderr 有 start/spawn/20 秒 heartbeat（正常 exit 另有 done），JSON stdout 不受污染，中斷清整個 process group，並保留 merged tail、rc/signal 語意。 | `4e2e89b55`(gate heartbeat + bounded capture regressions) |
| IMP-0037 | 2026-07-17 | worktree resolve 實測 | cli | high | fixed | committed `resolve` 的 `git worktree remove --force` 實測約 30 秒、CPU 約 40%，期間因 mutation 共用 silent `subprocess.run(PIPE)` 完全無輸出，操作者無法分辨忙碌或卡死；同一路徑也涵蓋 fetch/rebase/merge/push/branch teardown 與網路 probe。現所有潛在長時 mutation、`ls-remote` 與 committed sweep 統一走 bounded streaming runner，stderr 立即顯示安全語意 phase/PID/alive、最長每 20 秒 heartbeat、正常 exit done；JSON stdout、dry-run 與 failure detail 保持，raw argv 不顯示。 | `457b8ea74`(mutation heartbeat + caller-route/JSON/secret regression) |
| IMP-0038 | 2026-08-03 | harness 可信度改造 Phase 1 | doc | med | open | 約 10 份 doc 的 `verified_against` 錨點指向 **從未進入 origin 的 pre-squash commit**（`docs/policy/safety.md` f0d37ca4、多份 `feature_boundary/*` …）。本機能過 `docs_lint` 只是因為本地 dangling object 仍在，CI 上（即使 `fetch-depth: 0`）一律解析失敗。Doc Tier 契約要求錨點「main 可達」，故這是實質假綠而非 CI 怪癖。`docs-lint` 因此暫時排除於 linux CI set。下一步：逐份把錨點 bump 到 main 可達 commit，然後把 group 移回 `LINUX_GROUPS`。 | — |
| IMP-0039 | 2026-08-03 | harness 可信度改造 Phase 2 | tool | high | open | `ios-build-catalyst` 是 cutover 的 **block** gate，但本機**結構性不可能通過**：`No "Mac Development" signing certificate matching team ID XNSH5U9FNV`。未改動的 main 亦然（exit 65）。一道環境上不可能綠的 block gate 與一道不可能紅的 gate 同樣有害，方向相反——它讓每個 iOS cutover 都被擋，而唯一的出路是繞過流程。下一步（需執行長決定）：安裝 Mac Development 憑證，或把 Catalyst build 降為 warn 並改由別處保證。 | — |
| IMP-0040 | 2026-08-03 | harness 可信度改造（開場） | doc | low | open | `worktree-flow` skill 宣稱「所有 mutation 子指令 dry-run 預設、`--commit` 才落地」，但 `worktree_orchestrate.py open` 沒有 `--commit` 旗標、直接落地。第一次照文檔呼叫即撞到 usage error。下一步：修文檔措辭（列出例外），或給 `open` 加上 dry-run 語意。 | — |
| IMP-0041 | 2026-08-03 | harness 可信度改造 Phase 3.1（未完成） | tool | med | open | `ops/ui_quality_gate.py:46-66` 的 `FAST_COMMANDS`/`SLOW_COMMANDS`/`UI_WORLD_REQUIRED` 是**第二份手寫 mechanism id 清單**，與 `ops/ui_quality_plane.yml` 無交叉驗證：yml 新增機制但忘了在 runner 登記 → `resolve_args` 回 (None,None) → status=`planned` → 不計入 failed → gate 全綠。違反 CLAUDE.md「SoT 零重複鐵則」。下一步：把命令併進 yml 成 `run:`/`requires:` 欄位，`cmd_validate` 對 `gate: manual` 而無 `run:` 報 ERROR，runner 改讀 yml 且讀不到即 failed（非 planned）。 | — |
| IMP-0042 | 2026-08-03 | harness 可信度改造 Phase 5（未完成） | arch | med | open | exit code 有兩個互斥家族：家族1 `0/1/2=pass/warn/block`（`ios.gate`/`branch_audit`/`review_audit`/`docs_lint`）與家族2 `0=pass,2=block,1=工具錯誤`（app_review 全家）。決定性理由：這些腳本跑在 `set -euo pipefail` 下，未捕捉的中途失敗天然 exit 1，所以家族1 讓「腳本半路死掉」與「乾淨判 warn」不可區分——同一種病換一層。裁定應為 `0=pass/1=tool error/2=block/3=warn/64=usage`。遷移成本經查證極低（branch_audit/review_audit 的 exit code 無機器消費者；worktree 測試幾乎全用符號常數）。附帶：sha256 五份、canonical JSON 四份（`ops/demo/emit_ios.py:280` separators 不同導致 hash 不相容）、ISO8601 三份、原子寫檔四份，應抽進 `ops/lib/`。 | — |
