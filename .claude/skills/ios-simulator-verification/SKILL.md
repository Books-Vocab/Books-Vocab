---
name: ios-simulator-verification
description: "KG iOS Simulator 與 UITest 驗證工作流，涵蓋 UI World 隔離、Simulator lease、行為與視覺證據、xcresult/log 診斷及可重現 handoff。當任務需要操作或檢查 iOS Simulator、執行 BooksAndVocab UI test、驗證 SwiftUI 畫面／互動／非同步狀態，或保存 UIreview 證據時使用。"
---

# iOS Simulator Verification

## 目的與邊界

用這個 skill 把「畫面看起來對」拆成可追溯的證據鏈：source tree → UI World → 指定 Simulator → test verdict → 視覺產物。它適用於 KG repo 的 `ios/`、`ops/ios_ops.sh`、`ios/BooksAndVocabUITests/` 與 `ops/fixtures/ui_worlds/`。

它驗證的是 Simulator 與 UI test，不等同真機、TestFlight、App Store 或 production release 證據；那些流程另走 `docs/sop/ios.md` 與 release skill。

## 不變量

- 先確認 worktree、branch、HEAD、dirty 狀態；不要在 primary `main` 編輯。
- UI test 一律帶 `--dataset` 或 `--dataset-file`；沒有 UI World 就停止，不用真 backend 或任意舊 simulator 狀態代替。
- 平行／agent 執行預設用 `--lease`。helper 的 `--device` 只接受 canonical UDID，不接受名稱；被 Apple ID、系統設定對話框或其他 worktree 佔用的裝置不可作證據。
- helper 只在 clean source、`status=result=ok`、`exit=0`、`executed>0`、source/dataset/device identity 全相符，且五類視覺 artifact 真實存在時回 `0`；不能以 process exit 或可解析 JSON 代替 verdict。
- 任何 UI test 若會在 test body 寫入 evidence context，必須由 `ios_ops.sh test --ui --json`／本 skill helper 執行；producer 會把同一個 pinned `KG_IOS_VERDICT_FILE` 注入 scoped `.xctestrun`，讓 runner 與 host 讀到同一份 invocation verdict。缺少這個 binding 必須 fail-closed，不能在 test 內自行猜 latest verdict。
- 視覺 artifact 還必須通過 `ops/uitest_evidence_contract.py validate`：manifest 至少一個真實 step、每個 PNG 有尺寸／byteSize／SHA-256 且與檔案一致，contact/quick4/video/UIreview 非空，並帶同一個 source commit、UI World ID/hash、Simulator UDID provenance。只有路徑存在不算 evidence。
- 一個 evidence bundle 對應一個明確 selector；要比較 P1–P15 狀態時，每個 requirement／state variant 都要有獨立 run record，不能用一個泛用 `--file` 的混合截圖冒充全覆蓋。單一 requirement 可以由多個 exact selector bundle 組成 evidence union，但每個 bundle 都要獨立通過 machine contract、source/dataset/device provenance 與全步驟 visual attestation；`record-many` 只接受 union 中每個 logical required/counterexample state 恰好一次且 asset 不重疊的結果。
- `build/snapshots/uitest-runs/index.json` 是 append-only history；同一 flow/variant 的新 run 只更新 cockpit 的 latest status，不得刪除舊的 fail／inconclusive record。
- tap 成功不是行為證據。非同步設定、store round-trip、導航、載入／錯誤／空狀態要斷言結果；必要時用 UI test attachment 或 app log 證明資料流。
- 任何會多次 `launch`、序列化大量 AX attachment、或預估超過 60 秒的 evidence test，必須在該 `XCTestCase` 明確設定 `executionTimeAllowance`（依實測選 150／180／240／300 秒）；`KG_IOS_TEST_MAX_EXECUTION_TIME_ALLOWANCE` 只提供 xcodebuild 上限，不會改掉 XCTest 預設 60 秒，也不會覆寫 test case 自己的較短 allowance。逾時要標為 execution-inconclusive，不能當成產品 PASS/FAIL。
- 零步驟的 fixture decoder、manifest schema、projection unit test 不是視覺證據；它們應直接走 unit／focused test，不能用 evidence helper 產生空 screenshot bundle，也不能把「沒有 UI step」記成 visual pass。真正的 UI evidence 必須有至少一個使用者可見狀態與對應 interaction/assertion。
- iOS 26 SwiftUI `Slider` 的 endpoint 是已知的 XCTest edge case：從任一端直接呼叫 `adjust(toNormalizedSliderPosition: 0|1)`，API 可能回傳而值不變；直接 tap track 也可能只產生事件。Page Object 必須先把 slider 調到 bounded interior（下端 `0.05/0.15/0.25`、上端 `0.95/0.85/0.75`），每次等待 AX `value` 確實改變，再調到 endpoint 並等待精確目標值；有限次 staged retry 仍只用語意 Slider API，不可把 tap／coordinate drag 當成未驗證 fallback。coordinate press/drag 在此情境曾造成 XCTest test body 長時間無輸出，應分類為 inconclusive 並清理 process/lock 後重跑。
- 每個 helper run 都會保存 `build/snapshots/uitest-evidence/<run>/verdict.json`、`upstream-verdict.json`、command、runner log；upstream 有提供的 UIreview HTML、contact sheet、quick4、manifest、video、xcresult 也會複製到同一 bundle。runner 失敗或 verdict 不合約時仍讀這個 normalized bundle，但只能標 fail／inconclusive，不能宣稱畫面通過。

## 標準流程

### 1. Preflight

在 repo root 執行：

```bash
hostname -s
git branch --show-current
git rev-parse HEAD
git status --short
./ops/ios_ops.sh xcode --json
./ops/ios_ops.sh simulator status --json
```

若要跑 UI test，先確認 UI World：

```bash
./ops/ui_world_manifest.py validate ops/fixtures/ui_worlds/marketing_demo.json
```

不要以 `simctl list` 中「剛好 booted」的裝置直接當乾淨環境；它可能正在被另一條 build/test 使用，或有帳號／系統 prompt。

### 1.1 多日收斂與 agent 分工

P1–P15 是一個持續數日的收斂計畫，不是 15 個獨立的像素修補。每一波固定經過：

1. 根因／方案審查：重新讀報告圖、現行程式、既有測試與 UI World，先寫出 confirmed、candidate、blocked。
2. 單一 ownership 實作：每個 agent 只擁有一個 P 區或一個明確的 fixture／evidence 工具檔案集合；不得跨線改測試來掩蓋失敗。
3. unit／projection／compile gate：先證明狀態機、資料投影與 round-trip，再開 Simulator。
4. exact-selector runtime：一個 run 只對應一個 flow、dataset、variant、device 與 selector；失敗 run 保留，不借用上一輪綠燈。
5. 視覺審查與反例：檢查 full steps、contact sheet、quick4、UIreview、video，以及 loading／empty／error／長資料／Dynamic Type／深色／極值。
6. adversarial review 與 rework：獨立 reviewer 針對 false-green、語意漂移、父容器 AX identifier、fixture hardcode、截圖覆寫提出 BLOCK；修正後重跑同一 selector。
7. 只有 machine contract 與人工 attestation 都通過，才用控制面記錄該列；下一波才能消費其證據。

平行 agent 數量服從共享資源而不是反過來：read-only／source review／fixture schema 可以大量平行；Xcode build、Simulator lease、UI run 必須由 runner lock 排隊，且每個長命令要保留 heartbeat、PID、log、xcresult。禁止多個 worktree 同時對同一個 `--file` 做寬泛 UI run；若需要重跑，使用 exact `--method`。

#### 長命令期間不得閒置

協調者不能把整個 turn 只用在輪詢長命令。啟動 build／UI run 後，立即推進不競爭同一 Xcode／device lock 的工作：讀 stable failure bundle、定位第一個根因、審查 source diff、驗證 UI World／matrix、整理已完成 run 的視覺證據、準備下一個 exact selector，或跑非衝突的 static／unit gate。輪詢只保留 bounded heartbeat，並回報 elapsed／PID／alive／last log；不要用密集輪詢取代工作。

若同一 runner lock 尚未釋放，不要為了假裝平行再排另一個會排隊的 Xcode 命令；改做 read-only／報告／contract 工作，或使用明確隔離且可取得的另一個 lease。長命令結束後，先讀 normalized verdict 與 machine contract，再把相同 selector 綁定到 visual review；任何失敗先做一個窄根因修正再重跑，不同時堆疊未驗證 patch。

### 1.2 UI World 注入契約

每個 requirement 的 `requiredFixtureIDs` 是可執行資料契約，不是測試註解。新增或修正 flow 時：

- fixture 必須由 UI World／`FixtureDatasetStore` 注入，production code 不可為了截圖塞 hardcoded preview rows；test 開始時要能從 app log／AX 可觀察到 dataset identity。
- rich dataset 至少覆蓋正常、空、載入、錯誤／重試、長文案、混合角色／狀態、邊界數值；每一個反例必須有獨立 state label 與 screenshot asset。
- seed 的語意欄位要能驅動真實 projection，例如角色、review eligibility、due／unlearned、history、provider provenance、Reader preference、時計與 timezone；只改文字而不改狀態來源不算 injection。
- UI test 斷言投影後的 rows、counts、CTA、selection、error recovery 與 round-trip；截圖只證明畫面，不取代行為斷言。
- 修改 UI World schema、seed 或 validator 時，必須同時跑 recursive inheritance／override／cross-reference tests，防止 host validator 與 runtime 解析器各自接受不同資料。

### 2. 選擇驗證層

- 行為回歸、非同步狀態、導航：用指定 test selector。
- SwiftUI layout／glass／截斷／狀態卡：用 UI test 的 screenshot、contact sheet、video 與 `UIreview.html`，再以 `view_image` 檢查關鍵畫面。
- 互動探索或找入口：用 `./ops/ios_ops.sh catalog open --dataset ...`，記下 session，檢查後用 `catalog capture`，最後必須 `catalog close`。
- 編譯或靜態契約：先跑對應 lint／unit；它們不能取代 runtime UI 證據。

### 3. 執行 UI test

單一 test 的推薦入口：

```bash
./.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --dataset marketing_demo \
  --file SettingsFlowUITests.swift \
  --json-out /tmp/settings-flow-verdict.json
```

同一 helper 也支援：

```bash
./.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --dataset marketing_demo --grep OverviewFlowUITests
./.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --dataset marketing_demo --method ReaderFlowUITests/testReaderFlowRendersRealBook
```

`--method` 會轉成底層 `ios_test.sh` 真正支援的 positional `Class/method` selector；它不是不存在的 `ios_test.sh --method` flag。若要指定裝置，傳 UUID：

```bash
./.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --dataset marketing_demo --device 43FA3E1B-16F8-4144-B17D-53D5E4728FC6 \
  --file SettingsFlowUITests.swift
```

需要直接控制時，保持相同契約：

```bash
./ops/ios_ops.sh test --ui --dataset marketing_demo --lease \
  --file SettingsFlowUITests.swift --json
```

`--lease` 由 runner 負責 pool claim、boot、execution lock 與 release；不要自己 erase／刪除 simulator data 來「修」測試污染。`--build-lock-timeout` 只控制底層 build/device lock 等待，不是 XCTest 的 test timeout；XCTest timeout 由 `ios_test.sh` 的 runner 契約管理。

單一 helper invocation 不接受 `--output-dir`：它會自行建立不可覆寫的 stable bundle。需要一次 build、跑多個 exact selectors 並集中輸出到指定目錄時，才由 `ops/ios_ui_run_many.py run --output-dir ... --summary-out ...` 編排；每個 selector 仍必須產生獨立 bundle，不能用混合 `--file` 截圖替代。

### 3.1 視覺證據機器 gate

`run_ui_evidence.sh` 會把 upstream run 複製到 stable per-run bundle，然後執行：

```bash
uv run --python 3.13 python ops/uitest_evidence_contract.py validate \
  --screenshot-dir <stable-ui-review-root> \
  --manifest <stable-ui-review-root>/review_manifest.json \
  --contact-sheet <stable-ui-review-root>/contact_sheet.png \
  --quick4-sheet <stable-ui-review-root>/quick4_contact_sheet.png \
  --video <stable-ui-review-root>/uitest-videos/<run>.mp4 \
  --review-html <stable-ui-review-root>/UIreview.html \
  --source-commit <HEAD> --dataset-id <datasetID> \
  --dataset-sha256 <datasetSHA256> --device <Simulator-UDID>
```

validator fail 時 helper 回 `70/inconclusive`，即使 XCTest upstream 回 `0` 也不可宣稱 UI pass。讀 `artifacts/ui-evidence-contract.json`；它是 machine verdict，不取代人工檢查。

### 4. 讀完整證據

成功或失敗都讀：

1. stable bundle 的 `artifacts/delegate.stderr.log`、`verdict.json` 與 `upstream-verdict.json`（若 upstream 沒輸出 JSON，讀 `upstream-verdict.raw`）。
2. normalized verdict 的 `status/result/exit/reason`、`executed`、`options.sourceCommit`、`options.sourceTreeDirty`、`options.datasetID/datasetSHA256`、`device`。
3. normalized `artifacts.log` 與 `artifacts.xcresult`；兩者必須指向 stable bundle 內仍存在的檔案／目錄。
4. UI run 的 `artifacts.uiReviewHtml`、`uiContactSheet`、`uiQuick4Sheet`、`uiVideo`、`uiVisualReviewManifest`，以及 `uiVisualReview.*Exists == true`。
5. 關鍵 step screenshot；有遮罩、系統 prompt、錯誤 overlay 或畫面未到達時，標記證據缺口。

不要只讀最後一行「tests passed」。若 test 失敗，先讀第一個 assertion 及其附件，再讀 app log／source data flow；不要先改測試斷言。

### 5. 結果分類與回報

- `0 / status=ok`：helper 已證明 clean source、非零 tests、identity 一致與視覺 artifact 存在；仍要親自檢查 contact sheet／HTML。
- `1 / status=fail`：test 紅；先讀 stable bundle 的 upstream status、stderr、xcresult／UI artifacts，再修根因後重跑同一 selector。
- `65 / status=inconclusive`：runner／preflight、contract evidence 或 compile/build 不足；stable bundle 是診斷來源，不是 pass 證據，先看 compiler diagnostics／upstream status。
- `143` 等 `128+N`：被訊號中止，不是綠也不是產品紅；確認 lock／process cleanup 後重跑。
- Simulator 被 prompt、其他 app、其他 worktree 或不可識別狀態污染：`inconclusive`，換 `--lease` 裝置重跑。

### 5.1 人工視覺收斂

機器 gate 綠後仍逐 run 檢查 full contact sheet、quick4、UIreview step 順序與 video；至少檢查 loading/empty/error、長資料、深色／字級／Dynamic Type、互動後狀態與反例。人工結果要寫入 run 的 `review_state.json`（reviewer、時間、判定、檢查過的 assetID、notes、manifest root hash）；沒有人工 attestation 只能報「runtime evidence 已產生，visual review pending」，不能報「視覺驗證完成」。

記錄完整 run 的人工通過判定：

```bash
uv run --python 3.13 python ops/uitest_review_attest.py \
  build/snapshots/uitest-evidence/<run>/artifacts/ui-review \
  --reviewer codex --status pass --all-steps \
  --notes '檢查 full/quick4/UIreview/video；確認狀態順序與反例'
```

只檢查部分 step 時可用 `--asset-id`，但只能記錄 `fail`／partial review，不能當成整個 run 的 visual pass。

回報至少包含：

```text
source: <branch> <HEAD> dirty=<true|false>
dataset: <id> [sha256 if present]
device: <UDID>
selector: <exact selector>
verdict: <status> exit=<code> reason=<reason>
behavior: <asserted result>
visual: <UIreview.html/contact sheet/video paths and inspection result>
raw: <log> <xcresult>
```

## 失敗診斷捷徑

- 找不到 accessibility identifier：先檢查父容器 `.accessibilityIdentifier` 是否覆蓋子節點；不要先改 selector。
- Page Object 的 query property 必須無副作用：不得在 getter 內用 `count`／`XCTFail` 阻止後續 `waitUntilExists`；startup、Readium WebView、SwiftUI transient sheet 先等待 materialize，再對已存在節點做唯一性與 scope assertion。SwiftUI 父容器要保留子 selector 時，明確使用 `.accessibilityElement(children: .contain)`。
- tap 後值沒有改：沿 binding setter → async Task → coordinator → store → view projection 驗證；assert store round-trip，而非只依賴原生 Toggle 的瞬時值。
- SwiftUI Slider 在任一端直接跳 endpoint：先確認不是產品 binding／store 根因；若 interior action 可動而 exact endpoint 不動，將 endpoint action 封裝在 Page Object 內做有限候選 staged adjustment（下端 `0.05/0.15/0.25 → 0.0`、上端 `0.95/0.85/0.75 → 1.0`），每次都對 interior 與最終 AX value 加 bounded wait。不要改成只點軌道、只拖座標，或把預期值改成目前洩漏的值。
- UI test 突然超時且第一個 assertion 很晚才出現：檢查 AX query 是否在錯誤頁／prompt 上反覆重試、裝置是否被另一 run 佔用、以及 `deviceRunLockWaitMs`。
- UI screenshot 有 Apple 帳號驗證、登入、權限或鍵盤遮罩：這是環境污染證據，不能當 UI pass。
- `build.db database is locked`：先視為共用 build lock／另一 worktree 的基礎設施問題，讀 runner heartbeat 和 lock wait；不要刪 DerivedData 或改測試。
- helper contract regression：執行 `./.claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh`，它會驗證 selector translation、false-green 拒絕、canonical device 與 stable retention。

詳細 verdict 欄位、artifact retention 與常見 exit code 見 [`references/evidence-contract.md`](references/evidence-contract.md)。

## 收尾

完成 code／test 修改後，依 worktree-flow 停在：最小充分驗證 → commit → `./ops/worktree_registry.py hand-back --json`。不要在 child 自行 integrate、cutover、resolve、sync 或 deploy。回報中把每個 PDF／UI requirement 對應到 source、unit、UI behavior、visual artifact；沒有 live／pixel／physical evidence 就明確標出缺口。
