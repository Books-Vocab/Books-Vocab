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
- 視覺 artifact 還必須通過 `ops/uitest_evidence_contract.py validate`：manifest 至少一個真實 step、每個 PNG 有尺寸／byteSize／SHA-256 且與檔案一致，contact/quick4/video/UIreview 非空，並帶同一個 source commit、UI World ID/hash、Simulator UDID provenance。只有路徑存在不算 evidence。
- 一個 evidence bundle 對應一個明確 selector；要比較 P1–P15 狀態時，每個 requirement／state variant 都要有獨立 run record，不能用一個泛用 `--file` 的混合截圖冒充全覆蓋。
- `build/snapshots/uitest-runs/index.json` 是 append-only history；同一 flow/variant 的新 run 只更新 cockpit 的 latest status，不得刪除舊的 fail／inconclusive record。
- tap 成功不是行為證據。非同步設定、store round-trip、導航、載入／錯誤／空狀態要斷言結果；必要時用 UI test attachment 或 app log 證明資料流。
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
- tap 後值沒有改：沿 binding setter → async Task → coordinator → store → view projection 驗證；assert store round-trip，而非只依賴原生 Toggle 的瞬時值。
- UI test 突然超時且第一個 assertion 很晚才出現：檢查 AX query 是否在錯誤頁／prompt 上反覆重試、裝置是否被另一 run 佔用、以及 `deviceRunLockWaitMs`。
- UI screenshot 有 Apple 帳號驗證、登入、權限或鍵盤遮罩：這是環境污染證據，不能當 UI pass。
- `build.db database is locked`：先視為共用 build lock／另一 worktree 的基礎設施問題，讀 runner heartbeat 和 lock wait；不要刪 DerivedData 或改測試。
- helper contract regression：執行 `./.claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh`，它會驗證 selector translation、false-green 拒絕、canonical device 與 stable retention。

詳細 verdict 欄位、artifact retention 與常見 exit code 見 [`references/evidence-contract.md`](references/evidence-contract.md)。

## 收尾

完成 code／test 修改後，依 worktree-flow 停在：最小充分驗證 → commit → `./ops/worktree_registry.py hand-back --json`。不要在 child 自行 integrate、cutover、resolve、sync 或 deploy。回報中把每個 PDF／UI requirement 對應到 source、unit、UI behavior、visual artifact；沒有 live／pixel／physical evidence 就明確標出缺口。
