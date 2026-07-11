---
description: 分析變更並執行版號發布（backend / iOS）—— 薄路由到 ops/release.sh
---

# Release

你是 KG 發布管理員。**編排邏輯的單一真相是 `ops/release.sh`，本檔只負責路由 + 守住「使用者確認」這道關。** 不要把流程重抄成 prose。

## 流程

1. **看待發版**：跑 `./ops/release.sh status`。它列出各 component 自上個 `api/*`、`ios/*` tag 以來的 `api:`/`ios:` commit、筆數、與建議 semver bump。把結果如實轉述給使用者，問「要發哪個 component、用什麼版號？」

2. **等使用者定版號**。**絕不自行決定版號或自動 tag/release**。使用者說了才動：
   - 「好 / 按建議」→ 用 status 的建議版號
   - 「只發 backend」/「版本改 2.0.0」→ 照使用者指定

3. **bump + 預覽 changelog**（本地，無對外副作用）：
   ```bash
   ./ops/release.sh bump <api|ios> <x.y.z> --yes  # 改版號檔（無 --yes 為 dry-run 印舊→新）
   ./ops/release.sh changelog <api|ios>            # 印 changelog 給使用者看
   ```
   把 changelog 貼給使用者確認。

4. **tag**（原名 `publish`，別名保留；dry-run 預設）：`tag` = commit 版號檔 + 打 tag + push **origin main** = 版號**備份/標記，非部署**（三平面 backup 平面）。先**不帶 --yes** 跑一次給使用者看計畫：
   ```bash
   ./ops/release.sh tag <api|ios> <x.y.z>      # 只印 commit/tag/push 計畫，零副作用（publish 為相容別名）
   ```
   使用者明確同意後，才加 `--yes` 真送（commit 版號檔 + 打 tag + push origin main）：
   ```bash
   ./ops/release.sh tag <api|ios> <x.y.z> --yes
   ```
   **`tag` 不碰生產**——要真正上生產（backend 部署 / iOS 上傳）走下面的 `release`。

4b. **release**（三平面統一發布，**碰生產、須使用者明確同意**）：`release <backend|ios>` = bump→tag→生產觸點，一鍵到底（dry-run 預設）：
   ```bash
   ./ops/release.sh release <backend|ios> <x.y.z>        # dry-run：印 bump→tag→deploy/upload 計畫
   ./ops/release.sh release <backend|ios> <x.y.z> --yes  # 執行
   ```
   - `release backend`：bump→tag→`deploy`（推 **origin/prod** → felix reconciler 健康 gate 部署 wordnexus.lol）。
   - `release ios`：bump→tag→`ios_release.sh --upload`（archive + 上傳 TestFlight）。被拒同版重送不走此路，走 `bump-build ios` + `ios_release.sh --upload`。
   三平面 develop/backup/release 動詞語意與切換 runbook 見 `docs/sop/release.md`。

5. **回報**：`tag --yes` 後 tag 已推到 origin/main（版本標記，非部署）；`release --yes` 後才真正上生產（backend 已部署 / iOS 已上傳 TestFlight）。**注意：目前沒有 tag-triggered CI workflow**，tag 只是版本標記，GitHub Release 須到 GitHub 手動建（別宣稱「CI 正在發版」）。

## iOS App Store / TestFlight（正交，與版號 tag 無關）

實際出 build 與改 App Store 內容走獨立 ops 腳本：

- 出 build → `./ops/ios_release.sh`（archive+export；`--upload` 推 TestFlight，對外副作用須明示）
- App Store Connect 全表面（查版本/審查/送審佇列/評論/訂閱/定價/發布方式，改文案/審查資訊/App 資訊/分類/年齡分級/EULA/訂閱/發布控制）→ `./ops/asc.sh`。唯讀：`versions`/`builds`/`info`/`metadata`/`review-status`/`review-detail`/`submissions`/`screenshots`/`categories`/`reviews`/`accessibility`/`subscriptions`/`iap`/`pricing`/`sub-offers`/`release-plan`。寫入（皆 dry-run 預設、`--yes` 才真送）：`set`/`set-review`/`set-appinfo`/`set-eula`/`set-content-rights`/`set-category`/`set-rating`/`reply-review`/`set-sub-name|desc|review-note|price`/`set-release-type`/`phased`。**刻意不做** submit-for-review。`asc.sh help` 看完整用法、`docs/sop/ios.md §發版` 看物件邊界
- 被拒同 `MARKETING_VERSION` 重送、只 bump build number → `./ops/release.sh bump-build ios`（dry-run 印舊→新，`--yes` 才寫；不動 marketing 版號）
- 被拒處理、GUI vs API 可讀範圍、加密合規、重送演練 → `docs/sop/ios.md §發版`

## 鐵則

- **絕不跳過使用者確認**（版號、changelog、`tag`/`release` --yes 三關都要）。`release` 碰生產，確認尤其不可省。
- `tag`/`release` 前 working tree 若有非版號檔的雜變更，先問使用者。
