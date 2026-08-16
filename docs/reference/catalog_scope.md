<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Debug/
  - ios/BooksAndVocab/Support/Fixtures/Core/
  - ops/demo/emit_ios.py
  - ops/fixtures/ui_worlds/
  - ops/lib/ios_ops_catalog.sh
  - ops/ui_world_manifest.py
verified_against: 3bb37a6f7c54
-->
# iOS Catalog：Agent UI 工作台（SoT）

Catalog 只有一個定位：讓 agent 在開發、debug 或與使用者討論 UI 時，把指定的 UI World 注入真實 app，開啟一個既有 scenario，並擷取模擬器實際顯示的畫面。

## 核心模型

- **UI World 是結構化畫面狀態**：`kg.fixture.dataset.v2` 同時描述資料、登入、權益、preferences、SwiftData rows 與檔案資產。Catalog 不另造第二套假資料。
- **`scenarioContext` 有兩種精確 wire shape**：既有世界可保留三鍵 legacy（`reviewClock`／`readerPassage`／`wordDetail`，clock 可為 `null` 或 `frozenNow` 形狀）；canonical 世界則必須一次提供五鍵，且 `reviewClock` 明示 `now`／`timeZone`／`frozenEpoch`／`anchorDay`／`source`，並同時帶 `dictionary` 與 `surfaceContracts`，缺鍵、混用或部分 canonical 形狀一律 fail closed。canonical contract 另驗 dictionary lookup/materialization/coverage、`explore`／`settings` required surface、asset ID↔inode 一對一與 review history 時間一致性；host validator、demo emitter、Swift decoder 與 repo fixture tests 共守此契約，與 Catalog scenario 數量解耦。
- **Scenario 是可選入口**：新 UI 不必註冊；只有 agent 預期會反覆檢查、debug 或展示某個狀態時，才在 `Debug/Scenarios/` 加 scenario 並登錄到 `CatalogScene`。
- **Explore fixture proof 是單一、可重放的 evidence contract**：`sharedDecks.fixtures.<id>.assetIDs` 必須恰有一個 asset。materializer 與 `ExploreFixtureAssetProof` 都走 manifest 安裝快照；找不到、驗證失敗或 image decode 失敗直接 fail-loud，不能以 optional snapshot、generic first 或 `EmptyView` 產生看似成功的證據。
- **一個工具，服務 agent 的即時觀察**：Catalog 只在需要時開啟指定 UI World 與 scenario，讓 agent 讀取真實 simulator window；觀察結束後只留下必要的短型 receipt。
- **真實 compositor 取圖**：app 必須在 disposable iOS Simulator 的真 window 顯示，`capture` 再用 `simctl io screenshot` 擷取。禁止回到 `CALayer.render(in:)`；後者繞過系統 compositor，無法正確呈現 iOS 26 Liquid Glass、backdrop sampling、部分 WebKit/系統材質與陰影。

## Agent 工作流

```bash
# 列出這份 UI World 可開的 runtime scenarios；命令結束會釋放 simulator
./ops/ios_ops.sh catalog list --dataset marketing_demo

# 開互動式 Catalog；也可用 --scenario 'Reader View · Chrome/Reading · Compact Header' 直達
./ops/ios_ops.sh catalog open --dataset marketing_demo

# open 會回 session id；agent 需要看畫面時擷取到暫存（預設有 TTL）
./ops/ios_ops.sh catalog capture --session <session-id> --json

# 只有人類報告真的需要二進位畫面時才明確提升
./ops/ios_ops.sh catalog capture --session <session-id> \
  --out build/ios-report/retained/<batch>/catalog/example.png --retain

# 使用完一定關閉，釋放該 session 擁有的 disposable simulator
./ops/ios_ops.sh catalog close --session <session-id>
```

`open` 的 keeper 預設存活 1800 秒（沿用 simulator pool TTL）；可用 `KG_IOS_CATALOG_SESSION_MAX_SECONDS` 縮短或延長。keeper 到期後 lease 進入可回收狀態，遺忘／崩潰的 agent 不會永久佔住 slot；若 slot 已被重新租用，舊 session 的 `capture`／`close` 會在碰 simulator 前拒絕。capture PNG 預設在系統暫存目錄並於 TTL 後回收；只有明確指定保留時才提升到報告保留區。

自動化 consumer 應加 `--json`，不要解析人類輸出。`list` / `open` 必須明示 `--dataset <name>` 或 `--dataset-file <path>`；host 會先以 `ops/ui_world_manifest.py validate` 驗證，再用 deflate-base64 注入 app。

## 安全邊界

- Catalog 只在 `DEBUG && targetEnvironment(simulator)` 編譯；真機與 Release build 沒有 Catalog 入口。
- 每次 `open` 都租用 disposable simulator；資料、Documents、UserDefaults 與 Keychain 不接觸日常 app/simulator 狀態。
- Catalog 不帶 `-isolatedAuthSession`，不會觸發 persistent auth purge。
- 預設 server 指向 `127.0.0.1:9`，封閉網路副作用；UI World 無效、app 未 ready、session 不存在或 screenshot 失敗都 fail loud。
- cleanup、`capture`、`close` 都必須同時核對 lease directory、UDID 與 owner token；lease handoff 前先解除 destructive trap，不操作已轉手的 simulator。

## 維護原則

新增 scenario 是選擇，不是 UI 完成條件，也沒有 coverage gate。既有 scenario 若因 production UI 改動而失效，只有仍有實際 debug/展示價值才修；否則直接刪除。UI World schema/fixture 本身仍由它自己的 validator 與測試管理，與 Catalog scenario 數量解耦。
