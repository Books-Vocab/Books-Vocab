---
description: 分析變更並執行版號發布（backend / iOS）—— 薄路由到 ops/release.sh
---

# Release

你是 KG 發布管理員。**編排邏輯的單一真相是 `ops/release.sh`，本檔只負責路由 + 守住「使用者確認」這道關。** 不要把流程重抄成 prose。

## 流程

1. **看待發版**：跑 `./ops/release.sh status`。若目標是 iOS，再跑 `./ops/release.sh shipped ios`（唯讀 dry-run，向 ASC 查目前 `READY_FOR_SALE` 的 (version, build)）與 `./ops/asc.sh versions` / `review-status`：先判斷上一個 marketing version 是否已完成審查，再談新版本號；git 的 semver 建議不能取代 ASC lifecycle 真相。**版號事實的 owner 表見 `docs/sop/release.md`「版號事實 SoT 表」。**

2. **等使用者定版號**。**絕不自行決定版號或自動 tag/release**。使用者說了才動：
   - 「好 / 按建議」→ backend 可用 status 建議；iOS 只有上一版已完成審查才可採新版本建議
   - 「只發 backend」/「版本改 2.0.0」→ 照使用者指定

3. **bump + 預覽 changelog**（本地，無對外副作用）：
   ```bash
   ./ops/release.sh bump <api|ios> <x.y.z> --yes  # 改版號檔（無 --yes 為 dry-run 印舊→新）
   ./ops/release.sh changelog <api|ios>            # 印 changelog 給使用者看
   ```
   把 changelog 貼給使用者確認。

4. **在 tag-only 與 release 二選一，不可依序都跑。** `tag` 只做版本標記；`release` 已內含 tag。iOS 新版本正常走 4b、同版重送走 4c，direct tag 只用於已上傳 binary 的恢復／補標記。

   **iOS 兩種 tag 別混**：`ios/<x.y.z>` = **上架**那顆 commit，只由 `shipped ios` 依 ASC 查證後物化（步驟 6）；`ios/<x.y.z>+<build>` = 該 (version, build) 的**封版** commit，由 `tag`/`release`/`resubmit` 產生。`--new-version-after-ready` **已移除**（傳入 hard-error），guard 改為直接讀 repo 的 tag 自己檢查。

4a. **tag-only**（原名 `publish`，別名保留；dry-run 預設）：先**不帶 --yes** 跑一次給使用者看計畫：
   ```bash
   ./ops/release.sh tag api <x.y.z>     # → api/<x.y.z>
   ./ops/release.sh tag ios <x.y.z>     # → ios/<x.y.z>+<build>（封版，非上架）
   ```
   使用者明確同意後，才加 `--yes` 真送（commit 版號檔 + 打 tag + push origin main）：
   ```bash
   ./ops/release.sh tag api <x.y.z> --yes
   ./ops/release.sh tag ios <x.y.z> --yes
   ```
   **`tag` 不碰生產**——要真正上生產（backend 部署 / iOS 上傳）走下面的 `release`。

4b. **release**（三平面統一發布，**碰生產、須使用者明確同意**；dry-run 預設）：
   ```bash
   ./ops/release.sh release backend <x.y.z>
   ./ops/release.sh release backend <x.y.z> --yes
   ./ops/release.sh release ios <x.y.z>
   ./ops/release.sh release ios <x.y.z> --yes
   ```
   - `release backend`：bump→tag→`deploy`（推 **origin/prod** → felix reconciler 健康 gate 部署 wordnexus.lol）。
   - `release ios`：guard 先檢查「有上架 tag、新版嚴格遞增、不跳過任何有 build tag 卻無上架 tag 的版本」；再 bump→`ios_release.sh --upload`→成功後才封 `ios/<x.y.z>+<build>` 並 push。被 guard 擋下先跑 `shipped ios` 補上架事實，不要繞。同版重送走 4c。
   - 執行 `release` 前不可先跑 4a tag-only；否則 release 會因 build tag 已存在於另一顆 commit 而拒絕。
   三平面 develop/backup/release 動詞語意與切換 runbook 見 `docs/sop/release.md`。

4c. **resubmit**（iOS 同版號、新 build 重送；**碰外部不可逆上傳、須使用者明確同意**；dry-run 預設）：
   ```bash
   ./ops/release.sh resubmit ios
   ./ops/release.sh resubmit ios --yes
   ```
   marketing 版號不動、不吃版本號參數、刻意不產生 `ios/<x.y.z>`。取代舊的「`bump-build ios --yes` + `ios_release.sh --upload`」兩步手動路徑（那條不留任何紀錄）。

5. **回報**：`tag --yes` 後 tag 已推到 origin/main（版本標記，非部署）；`release --yes` 後才真正上生產（backend 已部署 / iOS 已上傳 TestFlight）。**注意：目前沒有 tag-triggered CI workflow**，tag 只是版本標記，GitHub Release 須到 GitHub 手動建（別宣稱「CI 正在發版」）。iOS 上傳 ≠ 上架，別把 `release ios --yes` 說成「已上架」。

6. **上架後補記錄**（iOS 專屬）：App Store 實際開賣後跑 `./ops/release.sh shipped ios`（dry-run）→ `--yes`，依 ASC 查證後物化 `ios/<x.y.z>` 並推 origin。任何歧義它都 refuse 不猜；`--commit <sha>` 是人工斷言的逃生口，需使用者拍板。

## iOS App Store / TestFlight（正交，與版號 tag 無關）

實際出 build 與改 App Store 內容走獨立 ops 腳本：

- 出 build → `./ops/ios_release.sh`（archive+export；`--upload` 推 TestFlight，對外副作用須明示）
- App Store Connect 全表面（查版本/審查/送審佇列/評論/訂閱/定價/發布方式，改文案/審查資訊/App 資訊/分類/年齡分級/EULA/訂閱/發布控制）→ `./ops/asc.sh`。唯讀：`versions`/`builds`/`info`/`metadata`/`review-status`/`review-detail`/`submissions`/`screenshots`/`categories`/`reviews`/`accessibility`/`subscriptions`/`iap`/`pricing`/`sub-offers`/`release-plan`。寫入（皆 dry-run 預設、`--yes` 才真送）：`set`/`set-review`/`set-appinfo`/`set-eula`/`set-content-rights`/`set-category`/`set-rating`/`reply-review`/`set-sub-name|desc|review-note|price`/`set-release-type`/`phased`。**刻意不做** submit-for-review。`asc.sh help` 看完整用法、`docs/sop/ios.md §發版` 看物件邊界
- 被拒同 `MARKETING_VERSION` 重送 → `./ops/release.sh resubmit ios`（步驟 4c）。裸 primitive `bump-build ios` 只改版號檔、不留封版紀錄，僅供拆步／修補
- 被拒處理、GUI vs API 可讀範圍、加密合規、重送演練 → `docs/sop/ios.md §發版`

## 鐵則

- **絕不跳過使用者確認**（版號、changelog、`tag`/`release`/`resubmit`/`shipped` --yes 三關都要）。`release` 碰生產、`resubmit` 碰外部不可逆上傳，確認尤其不可省。
- **不代替 repo 宣稱上架**：`ios/<x.y.z>` 只能由 `shipped ios` 從 ASC 查證後產生。
- `tag`/`release` 前 working tree 若有非版號檔的雜變更，先問使用者。
