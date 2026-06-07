<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: 219e0f94
-->
# BooksBrowser iOS 開發技能

## 核心資訊

- **專案路徑**: `ios/BooksBrowser.xcodeproj`
- **Scheme**: `BooksBrowser`
- **工作目錄**: repo root（`~/kg/`）
- **Destinations**: iOS 17+ / iPadOS 17+ / Mac Catalyst（macOS 15.0+，非原生 macOS）
- **平台抽象**: `Platform/PlatformRepresentable.swift`、`Platform/PlatformCompatibility.swift`

---

## 最高指導原則

**Exit Code `0` = 編譯成功；release 前仍需看第一屏 diagnostics summary 的 warnings。**

---

## Mac Catalyst 雷區（編譯過 ≠ 不崩）

Catalyst 是正式 target（Mac 走 Catalyst，非原生 macOS）。以下寫法**編譯通過但在 Catalyst runtime crash**，CI 由 `ops/catalyst_lint.sh` 擋：

- **`.popover` 掛在 `.toolbar` / `ToolbarItem` 的 Button 上** → present 過場走 UIKit `_pinInputViewsForKeyboardSceneDelegate`，scene 未就緒時 trap（`EXC_BREAKPOINT`，backtrace 全在 UIKitCore、無 app frame）。**改用 `.sheet`**（不同 presentation controller，亦免疫 popover resize 時的 willReposition recursion crash）。豁免：同行 `// catalyst-allow: <reason>`。
- 判讀法：`brk #1` + backtrace 唯一 app frame 是 `main` = framework trap，非 app force-unwrap；務必先取 lldb `bt`。

`ops/catalyst_lint.sh [--report|--strict]`，baseline 0 命中。

---

## iOS ops 統一入口（agent 優先）

新工作流優先走 `ops/ios_ops.sh`，底層 `ios_build.sh` / `ios_test.sh` / `ios_release.sh` 仍保留為 primitives。

```bash
./ops/ios_ops.sh status                 # project version/build + Organizer latest + TestFlight latest
./ops/ios_ops.sh doctor                 # release readiness: project/Organizer/TestFlight/signing/StoreKit/Sentry
./ops/ios_ops.sh doctor --json          # 同上，輸出 kg.ios.doctor.v1 結構化 JSON
./ops/ios_ops.sh build                  # 委派 ios_build.sh，結束即列 warnings/errors diagnostics
./ops/ios_ops.sh test --file FooTests.swift
./ops/ios_ops.sh archive                # archive + export，預設不上傳
./ops/ios_ops.sh archive --upload       # 明示才上傳 TestFlight
./ops/ios_ops.sh archives latest        # 本機 Organizer latest archive
./ops/ios_ops.sh issues --log <log>     # 解析既有 xcodebuild log
./ops/ios_ops.sh logs --since 5m        # runtime log，過濾常見 Apple framework 噪音
./ops/ios_ops.sh logs --json --limit 200 # 同上，輸出 kg.ios.logs.v1 結構化 JSON
./ops/ios_ops.sh sentry                 # iOS Sentry wiring 摘要
./ops/ios_ops.sh workflow release       # read-only 發版工作流：下一步命令 + todo/ready/block/warn/manual
./ops/ios_ops.sh workflow release --json # 同上，輸出 kg.ios.workflow.v1 結構化 JSON
./ops/ios_ops.sh gate release --json    # release hard-stop verdict:0 pass / 1 warn / 2 block
./ops/ios_ops.sh xcode --json           # Xcode/project/destination/simulator inventory:kg.ios.xcode.v1
./ops/ios_ops.sh simulator status --json # booted simulator + app data container/process:kg.ios.simulator.v1
./ops/ios_ops.sh simulator launch --json # launch installed app, then re-check process state
./ops/ios_ops.sh simulator terminate --json # stop installed app, then re-check process state
./ops/ios_ops.sh simulator screenshot --out build/sim/current.png --json # 本機截圖 artifact，不上傳
./ops/ios_ops.sh runs --json            # 最近 build/test verdict + log/xcresult artifact path + diagnostics
./ops/ios_ops.sh snapshot --json        # 一次拉 project/Organizer/TestFlight/readiness/workflow/gate/xcode/simulator/runs
./ops/ios_ops.sh snapshot --json --skip-xcode # 快速模式:不拉 Xcode destination/simulator inventory
./ops/ios_ops.sh snapshot --json --skip-simulator # 快速模式:不拉 booted simulator/app process
./ops/ios_ops.sh snapshot --json --include-logs --log-limit 50 # 同上,再內嵌 runtime logs
./ops/ios_ops.sh commands --json        # 自描述 CLI catalog:side-effect / schema / delegate
```

輸出契約:第一屏固定優先看 `[ios][issues]` / `[ios][summary]` / `[ios][next]` 類摘要;需要原始資料時再開 log path。

原則:優先組合 Xcode 官方 CLI,不重造輪子。`ios_build.sh`/`ios_ops.sh build` 與 `ios_release.sh` archive 會產生 `-resultBundlePath <*.xcresult>`,再用 `xcrun xcresulttool get build-results` 抽 warnings/errors;`ios_test.sh` 會用 `xcrun xcresulttool get test-results summary/tests` 抽 executed/failures。raw xcodebuild log parser 只作 fallback。

`ios_ops.sh doctor` 是 release readiness 儀表板:read-only 彙總 project `MARKETING_VERSION(CURRENT_PROJECT_VERSION)`、Organizer latest archive、TestFlight latest build、ASC version state、manual signing export options、StoreKit scheme/file、Sentry release wiring。ASC version-state 查詢有短 deadline，逾時只會 `status=warn`，不阻塞本機 readiness。`status=block` 代表發版前必修（例如 build number 未增加），`status=warn` 代表資訊缺失或 local artifact 落後。agent/CI 要少調用工具時用 `--json`，schema 為 `kg.ios.doctor.v1`，核心陣列是 `readiness[]`。

`ios_ops.sh workflow release` 是 read-only 發版操作編排:輸出 `[ios][workflow] step=N key=... status=todo|ready|block|warn|manual command="..." note="..."`。它不跑測試/編譯/archive/upload,只根據目前 project/Organizer/TestFlight/ASC state 列下一步命令;submit/resubmit 邊界仍標 `manual`，因為 ASC submit-for-review / 撤回送審刻意不做 CLI 寫入。agent/CI 要直接讀步驟時用 `--json`，schema 為 `kg.ios.workflow.v1`，核心陣列是 `steps[]`。

`ios_ops.sh gate release --json` 是 release hard-stop verdict:schema 為 `kg.ios.gate.v1`,重用 `doctor --json` + `workflow release --json`。exit code 固定為 `0=pass`、`1=warn`、`2=block`;`todo`/`manual` 會列入 `todos[]`/`manual[]` 供 agent 排下一步,但不讓 gate 永遠失敗。`block` 只來自 readiness/workflow 的 `status=block`（例如 TestFlight build number 未增加）。

`ios_ops.sh xcode --json` 是 Xcode Project Navigator / destination selector / Devices 視角的 read-only inventory:schema 為 `kg.ios.xcode.v1`,組合 `xcodebuild -version`、`xcode-select -p`、`xcodebuild -list -json`、`xcodebuild -showdestinations` 與 `xcrun simctl list devices --json`。輸出包含 Xcode 版本、DeveloperDir、project configurations/schemes/targets、destinations `available[]`/`ineligible[]`、simulator runtimes/devices 與 booted/available summary。各來源都有 `sources.*.status/exitCode/error`,頂層 `errors[]` 保留 CLI failure 診斷;來源失敗時仍輸出可解析 JSON。文字 alias `environment` 供人掃第一屏;agent 要選 `--destination` 或確認 booted simulator 時讀 JSON。

`ios_ops.sh simulator status --json` / `sim status --json` 是 Simulator GUI 狀態的窄面:schema 為 `kg.ios.simulator.v1`,組合 `xcrun simctl list devices --json`、`xcrun simctl get_app_container booted com.Max0228.BooksBrowser data` 與 `xcrun simctl spawn <device> pgrep -x BooksBrowser`,回傳 booted device、app data container、app process `running|stopped|skipped|unknown` 與 errors[]。app 沒在跑是觀測狀態(`process.status=stopped`,pgrep exit 1),不讓整體 status 失敗;沒有 booted simulator 才回穩定 JSON + exit 1。`ios_ops.sh simulator launch --json` / `terminate --json` 對齊 Xcode Run/Stop toolbar 的窄面:底層只呼叫官方 `xcrun simctl launch|terminate`,然後重新讀 BooksBrowser process,回傳 `app.lifecycle` 與 `app.process`。它不 build、不 install、不 boot、不改 ASC;launch 需要 app 已安裝。`ios_ops.sh simulator screenshot --out <png> --json` 只做本機 artifact side effect,底層是 `xcrun simctl io <device> screenshot <png>`。

`ios_ops.sh runs --json` 是 Xcode Report Navigator + Issue Navigator 的輕量對應面:schema 為 `kg.ios.runs.v1`,讀最近 `ios_build.sh` / `ios_test.sh` 寫出的 verdict file,回傳 build/test result、caller、elapsed、executed tests、log path、xcresult path、artifact 是否仍存在,並在每個 run 內嵌 `diagnostics`:`kg.ios.diagnostics.v1`。diagnostics 優先讀官方 `.xcresult`,不可讀時用 raw log fallback;缺 artifact 時給穩定 `source:"missing-artifacts"` 空摘要,不讓 `runs`/`snapshot` 中斷。新 verdict 優先讀 `.json`（避免含空白 path 被 legacy `KEY=value` 格式截斷）,舊單行 verdict 只作相容 fallback；含空白 path 的準確 artifact 判定以 JSON verdict 為準。它不重跑 build/test。

`ios_ops.sh logs --json` 是 Xcode Console 的輕量對應面:schema 為 `kg.ios.logs.v1`,資料源是 Apple Unified Logging 官方 CLI `/usr/bin/log show --style ndjson`。輸出包含 `summary.rawCount` / `filteredCount` / `emittedCount` / `byEventType` 與 `entries[]`（timestamp、eventType、processID、subsystem、category、message、sender）；常見 RunningBoard/WebKit assertion 噪音會先過濾。`--limit` 只限制輸出的 entries 數量,不重跑 app。

`ios_ops.sh snapshot --json` 是 agent 第一輪狀態入口:schema 為 `kg.ios.snapshot.v1`,合併 project、Organizer latest、TestFlight latest、`readiness[]`、release `workflow.steps[]`、release `gate` verdict、Xcode `xcode` inventory、Simulator `simulator` 狀態與最近 `runs`。頂層 `summary` 是第一屏判讀層:`summary.verdict=pass|warn|block`,`summary.counts` 聚合 gate/build/test/xcode/simulator/runtime counts,`summary.nextActions[]` 把 gate hard-stop/todo、build/test diagnostics、xcode/simulator observation errors 轉成可直接執行或檢查的 action。非 JSON 文字模式也共用同一份 snapshot JSON formatter,第一行固定是 `[ios][summary]`,後續先列 `[ios][next]`,不再輸出舊式 `phase=doctor` dump。`runs.build.diagnostics` / `runs.test.diagnostics` 仍保留完整 `kg.ios.diagnostics.v1`,讓第一輪 payload 就有可行動問題,不用再二次跑 `issues` 或 grep log。預設不查 unified log,所以 `logs` 欄位為 `null`;需要 Xcode Console 視角時加 `--include-logs --log-since 5m --log-limit 200`,snapshot 會內嵌同一份 `kg.ios.logs.v1`。預設會查 `kg.ios.xcode.v1` 讓 agent 第一輪就有 scheme/destination/simulator inventory 視角;需要快速 dashboard 時加 `--skip-xcode`,此時 `xcode:null`。預設也會查 `kg.ios.simulator.v1` 讓 agent 第一輪知道 booted device、app container 與 BooksBrowser process `running|stopped|skipped|unknown`;需要跳過 Simulator GUI 狀態時加 `--skip-simulator`,此時 `simulator:null`。沒有 booted simulator 時 snapshot 仍回 0 並把 `.simulator.status` 設為 `error`,避免 dashboard 因觀測缺口中斷;log provider 失敗則仍傳遞非零 exit。snapshot 只做觀測並回傳 gate 物件,不因 gate warn/block 自己失敗;需要 hard-stop exit code 時跑 `ios_ops.sh gate release --json`。它仍是 read-only，只組合既有 `doctor --json`、`workflow release --json`、gate helper、`xcode --json`、`simulator status --json`、`runs --json` 與可選 `logs --json`;人要看文字 dashboard 可用 `ios_ops.sh snapshot` 或 alias `dashboard`。

`ios_ops.sh commands --json` 是 agent capability catalog:schema 為 `kg.ios.commands.v1`,列每個 subcommand 的 `key`、`aliases`、`sideEffect`、固定 `delegate` 欄位（無委派為 `null`）、用途與輸出 JSON schema。新 agent 不確定能不能寫入或該讀哪個 schema 時先查這個,不要解析 help 文字。

## iOS 編譯 3 步驟 SOP

### Step 1：靜默編譯，直擊錯誤

```bash
./ops/ios_ops.sh build                 # 預設 iPhone Simulator
./ops/ios_ops.sh build --catalyst      # Mac Catalyst（platform=macOS,variant=Mac Catalyst）
./ops/ios_ops.sh build --destination '<xcodebuild destination>'  # 自訂 destination
```

- Exit Code `0` → 編譯成功;仍看 `[ios][issues] warnings=...`，release 前不可無視新增 warnings
- Exit Code 非 `0` → 第一屏 diagnostics 會列官方 `.xcresult` top errors/warnings + raw log path，進 Step 2
- 動到三平台 navigation / Catalyst 專屬路徑時，`--catalyst` 與預設各跑一次驗證（`--timeout` 預設 600s）

### Step 2：還原案發現場

**不要只看單行錯誤就動手改。** 根據錯誤的**檔名 + 行號**，讀取該行**上下至少 20 行**原始碼，結合 Swift/SwiftUI 語法特性完整分析脈絡。

常見需要讀上下文的場景：
- `@ViewBuilder` 限制（return type、條件分支問題）
- Optional unwrap 導致的型別不符
- `@State` / `@Binding` / `@ObservableObject` 使用錯誤
- `async/await` 上下文缺失

### Step 3：對症下藥並驗證

修復後立刻重跑 Step 1。反覆「編譯 → 讀上下文 → 修改」直到 Exit Code 歸零。

## iOS 測試入口（`ops/ios_ops.sh test` / `ops/ios_test.sh`）

`ops/ios_test.sh` 與 `ios_build.sh` 共用 `/tmp/kg-ios-build.lock`，避免多 worktree / 多 runner 同時碰同一份 DerivedData。長 UI 測試會每 30 秒輸出 heartbeat（elapsed / xcodebuild pid / log path / 最近 test event），不要讓 6 分鐘以上的 launch permutations 變黑盒。

**第一性原理流程**：測試系統已具備 scope、heartbeat、log preserve、false-green 防護與 DB lock retry；因此 iOS 開發不再採「不主動跑測試」的保守規則，而是採**最小足夠驗證**。

```bash
./ops/ios_ops.sh test --timeout 1200                       # 預設只跑 BooksBrowserTests unit target
./ops/ios_ops.sh test --file NotebookCoverContrastTests.swift
./ops/ios_ops.sh test -g "sanitizeOutbox"
./ops/ios_ops.sh test --ui --file BooksBrowserUITests.swift # 只跑 UI test 檔案
./ops/ios_ops.sh test --ui testLaunchShowsPrimaryTabs       # 只跑 UI test method
./ops/ios_ops.sh test --all-targets --timeout 1200          # scheme 全量：unit + UI
./ops/ios_ops.sh test --file FooTests.swift --list          # 只列 resolved -only-testing selectors
```

- 預設 scope 是 `unit`，會自動加 `-only-testing:BooksBrowserTests`；UI tests 不會被誤混進 unit full。
- `--ui` 會把 discovery target 切到 `BooksBrowserUITests`，支援 `--file` / method selector。
- `--all-targets` 跑整個 scheme TestAction，不能和 `--file` / `-g` / specific method 混用。
- 測試結束第一屏會列 `[ios][issues] source=xcresult-test-results` 與 `[ios][tests] tests=... passed=... failed=...`；false-green 執行數優先取官方 `.xcresult`，raw log 只作 fallback。
- 失敗或 inconclusive 時保留完整 xcodebuild log 與 `.xcresult`，stdout 會印出 log / xcresult path；成功時 verdict 也記錄 log / xcresult path。
- 若 Xcode 回 `build.db database is locked` / `unable to attach DB`，runner 會在同一把 repo lock 內短暫等待並重試，避免把 infrastructure lock 誤判成測試失敗。

### iOS 開發驗證梯度

| 變更 / 狀態 | 必跑 |
|---|---|
| 純註解 / doc-only | 不跑 iOS test;跑 docs gate 即可 |
| iOS 編譯面或簡單型別修正 | `./ops/ios_ops.sh build` |
| iOS model/service/presenter/test 邏輯 | `./ops/ios_ops.sh test --file <相關Tests.swift>` 或 `-g <pattern>` + `./ops/ios_ops.sh build` |
| UI / navigation / accessibility / app launch | 相關 unit test + `./ops/ios_ops.sh test --ui ...` + `./ops/ios_ops.sh build` |
| test runner / scheme / SwiftData model / sync lifecycle / 跨 feature 共用面 | `./ops/ios_ops.sh test --all-targets --timeout 1200` + `./ops/ios_ops.sh build` |
| 多個 test 失敗或原因不清 | `./ops/ios_test_matrix.sh --timeout 300 [--start-at File.swift]`,逐檔定位後再修 |
| release / cleanup all / 宣稱 iOS 全綠 | `./ops/ios_ops.sh test --all-targets --timeout 1200` + `./ops/ios_ops.sh build` |

原則:
- 不用 `--all-targets` 當第一反應;先跑最小可證明範圍,避免把多個根因混在一起。
- 不用 build 代替 test;build 只證明可編譯,不證明行為。
- 看到 tool failure / inconclusive / false green 先修 runner 或 invocation,不要將就。
- 長 UI permutations 正常會跑數分鐘;依 heartbeat 判斷進度,不要因短期無 test case output 就殺掉。

## 發版 / TestFlight（`ops/ios_release.sh`）

App Store / TestFlight 出 `.ipa`。用 App Store Connect API key 的簽章基建，**無需手動匯入 Apple Distribution 憑證**（cert/profile 已一次性建置，含重建步驟見 `~/.secrets/apple/README.md`）。

> 版號 bump / `ios/x.y.z` tag / changelog 走 **`ops/release.sh`**（`status`/`bump`/`changelog`/`publish`，單一入口；`publish` dry-run 預設、`--yes` 才 commit+tag+push）。本節的 `ios_release.sh`（出 build）與 `asc.sh`（App Store 文案/查詢）是**正交**設施——版號 tag 與出 build 互不依賴。注意目前無 tag-triggered CI，tag 僅為版本標記。

```bash
./ops/ios_ops.sh archive              # archive + export 出 .ipa（無對外副作用，預設）
./ops/ios_ops.sh archive --upload     # 額外上傳 → TestFlight（對外副作用，需明示）
./ops/ios_release.sh                  # primitive:同 archive
./ops/ios_release.sh --upload         # primitive:同 archive --upload
./ops/ios_release.sh --key 6Y7DC88RUY # 換 ASC API key（預設 TCXVHFRXMS / App Manager）
./ops/ios_release.sh --timeout 900    # 自訂 build lock 等待秒數
```

- **產物**：`ios/build/export/BooksBrowser.ipa`（git-ignored）。
- **diagnostics**：archive 階段保留 raw log 與 `Archive.xcresult`，並在第一屏用 `ios_diagnostics.py` 列 warnings/errors；archive 失敗時先看 `[ios][issues]` 與 `xcresult=` path。
- **簽章**：manual signing — Apple Distribution cert（keychain）+ `KG App Store` profile（`ios/ExportOptions.plist`）。`method=app-store`（Xcode 26 印 deprecated 警告但可用；新式 `app-store-connect` 即使 manual 仍強制 Xcode 內登入 ASC account，純 CLI 不適用）。
- **build-number guard**：`--upload` 前比對本機 `CURRENT_PROJECT_VERSION`（`-target BooksBrowser`）與 TestFlight 最新 build，重複即中止 — 須先 bump 版號。archive/export 不受此限。
- **keychain 免互動**：codesign 存取私鑰需 partition list 授權（一次性 `security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <登入密碼> ~/Library/Keychains/login.keychain-db`）；未設則互動 terminal 彈授權框、背景/CI 會 hang。
- **key 選擇**：`TCXVHFRXMS`(App Manager) 可送審;`6Y7DC88RUY`(Developer) 僅 TestFlight。後端訂閱驗簽用 `6Y7DC88RUY`，**勿 revoke**。
- 共用 `ios_build.sh` 的 `/tmp/kg-ios-build.lock`，多 worktree 安全。

### App Store Connect 控制台（`ops/asc.sh`）

`ios_release.sh` 出 build；`asc.sh` 補「ASC 全表面查詢 + metadata/結構讀寫」——近乎完整的 ASC 控制台（App 資訊 / 版本文案 / 審查資訊 / 評論回覆 / 無障礙 / 營利 / 發布控制 / 送審佇列）。主體是 codemagic CLI 包裝（同 `ios_release.sh` 的 `asc()` wrapper），無手刻 JWT；codemagic 暴露不到的物件由旁路 helper 補、JWT 只活在 helper、不污染主檔：唯讀走 `ops/asc_get.py`（GET），**寫入**走 `ops/asc_write.py`（一般化 PATCH/POST/DELETE，body 由 stdin 餵 JSON；4xx/5xx 回 `{_httpError,_detail}`、204 回 `{_ok}`，不裸 crash）。所有寫入經單一 `emit_write` gate：**預設 dry-run**（印舊→新 + copy-paste 指令），`--yes` 才真送。

批次審文案 / 重寫 / 上傳走 `ops/asc_text_bundle.py`: `dump --output asc.json` 一次拉 App 層文案、版本文案、版本 copyright、審查資訊、訂閱文字、截圖/價格/評論摘要；編輯 JSON 後 `apply asc.json` 先 dry-run diff，`apply asc.json --yes` 才 PATCH 低風險文字欄位。它不送審、不撤回、不上傳截圖、不改價格 / 發布控制。

```bash
# ── 唯讀查詢 ──
./ops/asc.sh versions / builds / info             # 版本+審查 state / TestFlight build / app 層級
./ops/asc_text_bundle.py dump -o asc.json         # 整包文案/審查資料 JSON
./ops/asc.sh metadata --locale zh-Hant            # 某版本某語系文案
./ops/asc.sh review-status / review-detail        # 審查提交 state / 審查聯絡+demo+送審備註
./ops/asc.sh submissions [N]                      # 送審佇列 reviewSubmissions + 每筆打包項目數
./ops/asc.sh screenshots / categories             # 截圖逐張 state / 可用分類 ID
./ops/asc.sh reviews [N] / accessibility          # 用戶評論+是否已回覆 / 無障礙宣告
./ops/asc.sh subscriptions / iap / pricing        # 訂閱群組→方案 / 一次性購買 / 基礎定價+供應
./ops/asc.sh sub-offers <subId>                   # 訂閱優惠：介紹性/促銷/兌換碼
./ops/asc.sh release-plan                         # 發布方式 releaseType + 分階段發布狀態
# ── 寫入（皆 dry-run 預設，--yes 才送）──
./ops/asc.sh set <field> <value>                  # 版本文案 appStoreVersionLocalization
./ops/asc.sh set-review <field> <value>           # 審查資訊 appStoreReviewDetail
./ops/asc.sh set-appinfo <field> <value>          # App 層本地化：name/subtitle/privacy-url
./ops/asc.sh set-eula <text> / set-content-rights <uses|none>
./ops/asc.sh set-category <primary|secondary> <ID> / set-rating <attr> <value>
./ops/asc.sh reply-review <reviewId> <text>       # 回覆用戶評論（POST/PATCH upsert）
./ops/asc.sh set-sub-name|set-sub-desc|set-sub-review-note <subId> <value>
./ops/asc.sh set-sub-price <subId> <territory> <customerPrice>   # ⚠ 動真實計費
./ops/asc.sh set-release-type <manual|auto|scheduled> [ISO8601]  # auto=審核過自動上架
./ops/asc.sh phased <start|pause|resume|complete|cancel>         # 分階段發布7天ramp
./ops/asc_text_bundle.py apply asc.json [--yes]   # 整包文案 diff / PATCH（dry-run 預設）
```

**物件邊界**（用錯子命令會互相指路）：`set`→`appStoreVersionLocalization`（逐語系版本文案）；`set-review`→`appStoreReviewDetail`（整版一份審查資訊）；`set-appinfo`→`appInfoLocalization`（App 層逐語系 name/subtitle/privacy-url）；另有 App 層結構寫入（EULA/內容版權/分類/年齡分級）、營利寫入（`set-sub-*` → subscriptionLocalization/Price，`set-sub-price` 用 `preserveCurrentPrice:true` 保護既有訂戶 + 印三重 ⚠，後端以 key `6Y7DC88RUY` 驗訂閱權益）、發布控制（`set-release-type` PATCH appStoreVersions、`phased` POST/PATCH/DELETE appStoreVersionPhasedReleases，complete/cancel 不可逆會警告）。dry-run header 印目標版本字串+state（如 `1.6 (REJECTED)`）避免誤寫。

- **set 可寫 field**：`description / keywords / whats-new / marketing-url / support-url / promotional-text`，空值被擋。
- **刻意不做**：submit-for-review / 撤回送審（避免誤送誤撤，走 GUI）；IAP 寫面（KG `inAppPurchasesV2=0` 無對象）；訂閱優惠建立/刪除（逐地區 price point 繁瑣高風險且罕見，走 GUI）。
- **key**：預設 `TCXVHFRXMS`（App Manager，可寫）；`.p8` 路徑 `${ASC_KEY_DIR:-~/.secrets/apple}/AuthKey_<KEY_ID>.p8`（CI/部署機可覆寫 `ASC_KEY_DIR`）。

#### GUI 可讀 vs API 可讀/可寫

| GUI 區塊 | `asc.sh` 能力 |
|---|---|
| 版本 / 審查 state / build / 文案 metadata / IAP / 分析數字 | ✅ codemagic 讀；文案 `set` 可寫 |
| App 副標/名稱/隱私URL、分類、年齡分級、EULA、內容版權 | ✅ raw 讀寫（set-appinfo/set-category/set-rating/set-eula/set-content-rights） |
| 審查聯絡/demo/送審備註、截圖逐張 state | ✅ raw 讀（review-detail/screenshots）；審查資訊另可寫（set-review） |
| 用戶評論、無障礙宣告 | ✅ 讀（reviews/accessibility）；評論可回覆（reply-review）；無障礙建立走 GUI |
| 訂閱方案/價格/優惠、基礎定價、發布方式、分階段發布、送審佇列 | ✅ raw 讀（subscriptions/pricing/sub-offers/release-plan/submissions）；訂閱名/描述/備註/價格、發布方式、分階段發布可寫 |
| **App 隱私權營養標**（資料蒐集/追蹤宣告） | ❌ public API 不提供，**只能 GUI** |
| **截圖/preview 上傳**、**供應地區設定** | ❌ 無 API/codemagic 命令，**GUI 或 Transporter** |
| **被拒原因（Resolution Center 對話文字）** | ❌ public API 不提供，**只能 GUI 看** |
| 截圖圖檔「內容」是否含已移除功能 | ⚠ API 只給 fileName/state，須 fetch 縮圖目視 |

#### App Store 改動的審核成本判斷

| 想改什麼 | 審核成本 / 流程 |
|---|---|
| `promotionalText` 促銷文 | 低。可不提交新版更新；仍需保持真實、不可宣稱未實作功能。 |
| 價格、供應地區、分階段發布、release type | 不走一般 App Review，但屬真實商務/發布控制；一律先 dry-run，價格變更須確認訂戶影響。 |
| support URL、privacy URL、review notes、demo account | 低到中。依當前 version/submission state 可改；review notes/demo 是審查員資訊，重送前必查是否過期。 |
| description、keywords、subtitle、marketing URL、copyright | 中。屬 metadata；`REJECTED` / `METADATA_REJECTED` / `PREPARE_FOR_SUBMISSION` 通常可修後重送同版，同一輪不可寫欄位以 ASC API 回 `STATE_ERROR` 為準。 |
| screenshots / app previews | 中高。送審中通常不能改；已上架版本核准後，主產品頁截圖/preview 更新通常要建下一個 app version 再送審。API 目前只列 state，不負責上傳。 |
| 訂閱名稱、描述、review note、review screenshot、intro offer | 中高。訂閱物件本身可能進 subscription review；文案必須和 paywall / StoreKit 顯示一致。價格/優惠尤其高風險，逐地區 GUI 檢查。 |
| app binary、功能、UI、權限、登入/IAP 實作 | 高。必須新 build + App Review；同 `MARKETING_VERSION` 重送也要 bump `CURRENT_PROJECT_VERSION`，並重新綁新 build。 |
| App Privacy nutrition labels、Resolution Center 對話 | GUI-only。public API 讀不到/寫不到；被拒原因一定要人工進 ASC GUI 看。 |

#### 被拒處理 SOP（resubmit-readiness 演練，每次重送跑一遍）

1. `./ops/asc.sh review-status` 確認最新提交為 `UNRESOLVED_ISSUES`。
2. 到 ASC GUI「App 審查 → 解決中心」讀 Apple 的拒絕理由（API 讀不到）。
3. **掃殘留**：被拒功能名若已移除，`asc.sh metadata` + `review-detail` + app 副標全 grep 一遍確認 0 命中；`asc.sh screenshots` 列出截圖、fetch 縮圖目視無殘影。
4. **查備註是否過期**：`asc.sh review-detail` 的 notes 常沿用上一輪舊文（KG 實例曾停在 3.1.2(c) EULA 而非當輪原因）；重送時若需更新送審備註，直接 `asc.sh set-review notes "..."`（dry-run 看舊→新，`--yes` 才寫）對應「本輪」原因；向審查員對話回覆仍須 GUI 解決中心。
5. 改 code/文案（`asc.sh set …` 或改 app 碼）→ bump `CURRENT_PROJECT_VERSION`（同 `MARKETING_VERSION` 重送只 bump build；`asc.sh builds` 確認新 build > TestFlight 現值即無衝突）→ `ios_release.sh --upload` → GUI 把新 build 綁上該版本 → 重送。
6. 加密合規順手：本專案 `GENERATE_INFOPLIST_FILE = YES`（無 source Info.plist），故設 build setting `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption = NO`（多數 app 免出口加密，省每次上傳被問）。

#### 已知缺口（待辦，本輪未工具化）

screenshots / app preview **上傳**（list 已做；上傳 codemagic 無命令，須 GUI 或 Transporter + raw multipart）、**多語 localizations**（現僅 `zh-Hant`，缺 `en-US` 易被拒）、`appStoreVersions create`（重送下一版前須先建版本 row）、App 隱私權營養標（無 public API，GUI-only）。submit-for-review / 撤回送審、IAP 寫面、訂閱優惠建立為**刻意不做**（非缺口，理由見上「刻意不做」）。

## App 架構速查

### 主要 Services

| Service | 職責 |
|---------|------|
| `AuthManager.swift` | 單例，Apple/Google SSO、Keychain token、登入狀態 |
| `KGService.swift` | 後端 API 呼叫（拆 10 個 extension：+Graph / +Health / +Models / +Notebook / +Request / +ServerURL / +Stats / +Sync / +UserConfig / +VocabCRUD） |
| `BackgroundSyncActor` | `@ModelActor`，背景同步（push review/stats、pull cards、flush bilateral ops） |
| `SyncCoordinator` | 同步協調（手動同步入口、orphan cleanup） |
| `BookshelfImportService` | Multi-format import（EPUB/TXT/MD/PDF） |
| `AppToastCoordinator` | Toast notification 管理（EnvironmentKey 注入） |
| `AppCrashReporting` | Sentry bootstrap；opt-in via `Info.plist` `SentryDSN`；`bootstrap()` 於 `BooksBrowserApp.init()` 第一步呼叫；`setUser(id:)` 連動 `authManager.isLoggedIn` 變化；`record(_:context:)` 手動 capture |

### 主要 Views

| View | 說明 |
|------|------|
| `Settings/SettingsView` | 登入登出、伺服器設定、第三方整合 |
| `Reader/ReaderView` | EPUB 閱讀器（iOS only），查詞 → batchAdd → triggerPipeline |
| `Reader/PDFReaderView` | PDF 閱讀器（iOS only） |
| `Vocabulary/` | 單字瀏覽、知識圖譜視覺化、手動同步、hide/unhide links |
| `Vocabulary/Scenes/StatsPresenter` | 統計總覽 + graph thumbnail + health blob |
| `Vocabulary/Scenes/TodayReviewPresenter` | 每日複習 |
| `Bookshelf/BookshelfView` | 書架 + multi-format import |
| `Welcome/WelcomeView` | 首次啟動 / guest 引導（含 login entry points） |

### iOS 資料同步流程

```
Reader 查詞
  → 暫存 VocabularyEntry（syncStatus=0, pending）
  → POST /api/vocab（batchAdd）→ 伺服器生成 embedding
  → POST /api/pipeline（fire-and-forget）→ 伺服器背景 Enrich/Link/Difficulty/Optional External Sync
  → GET /api/vocab?since=<上次同步>（pullCardsToLocal）→ 更新 SwiftData
```

### 認證流程

```
Apple/Google SSO
  → Google User ID 或自訂密語（存 Keychain）
  → 作為 Authorization: Bearer <token> 發給後端
  → 後端建立 data/users/<user_id>/ 隔離目錄
  → HTTP 401 → iOS 自動登出 + 清空 SwiftData
```

### Crash Reporting（Sentry）

**iOS env / Info.plist key / 取樣率（SoT）**：`docs/sop/deploy.md §Sentry 錯誤追蹤 → iOS env / Info.plist`。本段僅寫 iOS-side 程式碼層 wiring。

實作要點（`Services/AppCrashReporting.swift`）：
- SPM dep `sentry-cocoa` 透過 `canImport(Sentry)` 守門 — 缺套件即 pure no-op，dev / PR build 不卡編譯
- Bootstrap 順序：`AppCrashReporting.bootstrap()` 在 `BooksBrowserApp.init()` 第一步執行（早於 `ModelContainer` init，捕捉儲存初始化失敗）
- User 追蹤：`AppCrashReporting.setUser(id:)` 連動 `authManager.isLoggedIn` onChange — 登出時清除，避免多帳戶污染
- `beforeSend` 過濾：丟棄 `CancellationError` / `NSURLErrorCancelled` 噪音；HTTP breadcrumb 自動 strip query string

### Hot Reload（InjectionNext + Inject）

開發時免 build 即時更新 SwiftUI，把「改一行等 30 秒 build」縮到秒級。Debug-only，Release builds LLVM-strip 為 no-op，**production 零影響**。

**前置一次性設定**：
1. SPM dep：`https://github.com/krzysztofzablocki/Inject`（已加進 `BooksBrowser.xcodeproj`）
2. Build Settings → Debug → Other Linker Flags 含 `-Xlinker -interposable`（**只 Debug**）
3. 下載 [InjectionNext.app](https://github.com/johnno1962/InjectionNext) 放 `/Applications/`

**使用方式**：
1. 啟動 InjectionNext.app（menu bar 出現 icon）→ menu bar 點 **Launch Xcode** 開啟 BooksBrowser.xcworkspace
2. ⌘R 跑 Debug build 到 simulator，console 應出現 `💉 InjectionNext connected`
3. 改任何已加 `.enableInjection()` 的 SwiftUI view → 存檔 → simulator 1-2 秒內重渲染

**hot reload 範圍**：
- `Views/**/*.swift` 下所有 non-private `struct X: View`(排除 Debug/Scenarios、Readium/PDFReader bridging、ViewModifier、`#Preview` 內)已**全面注入三件套**(`import Inject` / `@ObserveInjection` / `.enableInjection()`)— 改任一 leaf view body 都能熱重載
- **可注入**：view body / modifier / layout / 文案 / `AppTheme` 色票 / padding / spacing / radius / shadow / opacity
- **不可注入(仍需 full build)**：stored property 增減、`@State` 初始值、function signature 改動、`enum` case 新增、`@Observable` macro 生成的 code(偶有時延)、Readium C++/ObjC++ bridging 改動、`UIViewRepresentable`

**自動化工具**：
- 新增 leaf view 後若忘加三件套,跑 `python3 ops/inject_codemod.py --apply` 自動補(idempotent)
- `ops/injection_lint.sh --strict` 守門:三規則 — (R1) 合格 View 必有 `@ObserveInjection`;(R2) 同檔 `@ObserveInjection` 數 == `.enableInjection()` 數;(R3) 有 `@ObserveInjection` 必有 `import Inject`
- 已知例外:body 為 `if` / `switch` 根 expression 時,codemod 跳過 — 手工包 `Group { ... }.enableInjection()`(現有 9 個 case 已處理完)

**故障排除**：
- console 無 `💉` 訊息 → InjectionNext.app 未啟、或 Xcode 不是從 menu bar 「Launch Xcode」開的
- 改 file 後 simulator 沒反應 → 看 console 是否報 `cannot inject ...`（多半是改到 stored property），需 ⌘R 重 build
- Release archive 報錯 → 確認 `-interposable` flag **只在 Debug 配置**，Release 維持原狀

### Playbook Catalog（SwiftUI 元件目錄）

DEBUG-only 元件 catalog，讓 simulator 啟動時直接進入「狀態矩陣牆」而非正常 app UI，給 CLI 截圖協作（Claude / simctl）用。Phase 1 hot reload + Phase 3 catalog 組合 = 視覺迭代閉環：你改 `AppTheme.swift` 色票 → InjectionNext 秒級重渲染 catalog → simctl 截圖讓 Claude 看到結果。

**啟用方式**：
1. Xcode → Product → Scheme → Edit Scheme → Run → Arguments → **Launch Arguments** → 加 `-catalog`
2. ⌘R 跑 Debug build，app 啟動時 `BooksBrowserApp` 偵測到 `-catalog` 改用 `CatalogScene()` 為 root view（取代正常 `ContentView`）
3. simulator 開啟即見 Playbook catalog 列表，左側分類 / 右側渲染

要回正常 app：scheme 移除 `-catalog` 即可（建議**保留兩個 scheme**：`BooksBrowser` 正常、`BooksBrowser-Catalog` 含 launch arg）。

**目錄結構**：
- `ios/BooksBrowser/Debug/CatalogScene.swift` — 入口 view + `static func buildPlaybook()`(BooksBrowserTests 也 reuse 同一份 surface registration)
- `ios/BooksBrowser/Debug/Scenarios/*Scenarios.swift` — 每個 surface 一檔，通過 `register(in:)` 加 scenarios

**目前涵蓋**（9 groups / 60 scenarios — 數字由 `CatalogCoverageTests` 把關，新增 surface 漏掉 `register(in:)` 會紅）：
- Settings × 6（Logged Out / Subscribed Active / Subscription Loading / Deleting Account / Pricing Unavailable / Debug Backend Local）
- Today Review × 4（Front / Back / Completed / Autoplay）
- Bookshelf × 5（Card Progress / Card Placeholder / Empty / With Books / Loading）
- Welcome × 4（Step 1 Capture / Step 2 Link / Step 3 Review / Step 3 Dark）
- Notebooks · Card × 4（Hero heavy / Hero fresh / Grid two-up / Hero long-name truncate）
- Notebooks · Stack × 22（stress / depth 1-4 層 / active·inactive × light·dark state / a11y / editorial seeds / cover composition）
- Notebook Detail · Row × 6（happy / long word truncate / long translation / 4-digit numbers / 320pt narrow / accessibility3）
- Notebook Detail · CTA Pill × 5（due only / unlearned only / both / large numbers / no-CTA）
- Design Tokens × 4（Palette light·dark / Typography / Radii & Spacing）

**未涵蓋**（留待 future phase）：
- Reader 本體（Readium SDK runtime 太重，需先抽 `ReaderViewPresenter` chrome layer）
- Podcast Player（需先拆 `PodcastPlayerPresenter`）
- Auth 多狀態（authenticating / error，需先把 `AuthManager` 抽 protocol）
- Vocab WordDetail（無現成 preview factory，待補 stub）

**新增 surface scenarios 範本**：

```swift
// ios/BooksBrowser/Debug/Scenarios/FooScenarios.swift
#if DEBUG
import Playbook
import SwiftUI

enum FooScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Foo") {
            Scenario("Loading", layout: .fill) {
                AppThemeContainer { FooView(state: .loading) }
                    .environmentObject(AppAppearanceStore.preview)
            }
            // ...
        }
    }
}
#endif
```

寫完別忘了在 `CatalogScene.buildPlaybook()` 加一行 `FooScenarios.register(in: pb)`，並把新 group 名加進 `CatalogCoverageTests.expectedGroups`（漏 register 會被該 test 擋紅）。

**simctl 截圖協作**：

```bash
./ops/ios_ops.sh simulator screenshot --out /tmp/kg-catalog-page.png --json
```

把 JSON 的 `artifact.path` 貼給 Claude 即可協作視覺迭代。所有 catalog 程式碼都包在 `#if DEBUG` 內，**production binary 不包含**。

### Catalog Snapshot Export（PlaybookSnapshot → PNG batch）

`BooksBrowserTests/CatalogSnapshotTests.swift` 提供 `generateAllScenarioPNGs` test，跑一次把 60 scenarios × 2 devices（iPhone15Pro portrait light/dark）渲染成 PNG，**不用人工逐頁截**。

**執行方式**（manual，**不要主動跑** — 遵守 CLAUDE.md 鐵律 7 `ios_test.sh` 規則）：

```bash
# 由使用者明確要求才跑：
KG_RUN_CATALOG_SNAPSHOTS=1 xcodebuild test \
  -project ios/BooksBrowser.xcodeproj \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  -only-testing:BooksBrowserTests/CatalogSnapshotTests
```

**從 simulator sandbox 撈 PNG**：

```bash
# 找 BooksBrowserTests host app 的 data container
container=$(./ops/ios_ops.sh simulator status --json | jq -r '.app.container.data // empty')
# PNG 在 NSTemporaryDirectory → tmp/kg-catalog-snapshots/<device>/<category>/<scenario>.png
find "$container/tmp/kg-catalog-snapshots" -name "*.png" 2>/dev/null
# 或直接複製到專案下供 Claude 讀
mkdir -p build/snapshots && cp -R "$container/tmp/kg-catalog-snapshots/." build/snapshots/
```

**為什麼 PlaybookSnapshot 而非 EmergeTools/SnapshotPreviews**：原本計畫用 EmergeTools 套件直接 snapshot 既有 `#Preview`，但 `playbook-ios` 內建 `PlaybookSnapshot` product 已能對 catalog scenarios 做同樣工作，且 catalog scenarios 明確、命名整齊、能注入 stub envObject — 比 raw `#Preview` 更可靠（後者常因缺 EnvironmentObject crash）。`#Preview` snapshot 留待 Phase 5 評估。

**閉環 demo**：
1. 你改 `AppTheme.swift` 一個 hue 值 + InjectionNext 秒級重渲染
2. 確認 catalog 樣式可接受後跑上述 `xcodebuild test`
3. 撈 PNG → 貼給 Claude → Claude 跨 scenario 比對找出視覺 regression
4. 不滿意回 step 1



## 參考文件

- `docs/sop/ui-design.md` — Motion Contract + 設計系統規範
- `docs/sop/backend.md` — backend 開發主入口；跨前後端資料流問題時一起看
- `docs/reference/ui/components.md` — 現有 component / pattern inventory，開新 UI 前先查
- `docs/reference/ui/state_matrix.md` — 各主畫面 state coverage matrix，補 UX 時先查有哪些狀態不能漏
- `docs/sop/architecture.md` — 完整 iOS ↔ 後端同步協議、認證架構、資料模型詳解
