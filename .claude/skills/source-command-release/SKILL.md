---
name: "source-command-release"
description: "分析變更並執行版號發布（backend / iOS）—— 薄路由到 ops/release.sh"
---

# source-command-release

Use this skill when the user asks to run the migrated source command `release`.

## Command Template

# Release

你是 KG 發布管理員。**編排邏輯的單一真相是 `ops/release.sh`，本檔只負責路由 + 守住「使用者確認」這道關。** 不要把流程重抄成 prose。

## 流程

1. **看待發版**：跑 `./ops/release.sh status`。它列出各 component 自上個 `api/*`、`ios/*` tag 以來的 `api:`/`ios:` commit、筆數、與建議 semver bump。若目標是 iOS，再跑 `./ops/asc.sh versions` / `review-status`：先判斷上一個 marketing version 是否已完成審查，再談新版本號；git 的 semver 建議不能取代 ASC lifecycle 真相。

2. **等使用者定版號**。**絕不自行決定版號或自動 tag/release**。使用者說了才動：
   - 「好 / 按建議」→ backend 可用 status 建議；iOS 只有上一版已完成審查才可採新版本建議
   - 「只發 backend」/「版本改 2.0.0」→ 照使用者指定

3. **bump + 預覽 changelog**（本地，無對外副作用）：
   ```bash
   ./ops/release.sh bump <api|ios> <x.y.z> --yes  # 改版號檔（無 --yes 為 dry-run 印舊→新）
   ./ops/release.sh changelog <api|ios>            # 印 changelog 給使用者看
   ```
   把 changelog 貼給使用者確認。

4. **在 tag-only 與 release 二選一，不可依序都跑。** `tag` 只做版本標記；`release` 已內含 tag。iOS 新版本正常走 4b，direct tag 只用於已上傳 binary 的恢復／補標記。

4a. **tag-only**（原名 `publish`，別名保留；dry-run 預設）：`tag` = commit 版號檔 + 打 tag + push **origin main** = 版號**備份／標記，非部署**（三平面 backup 平面）。先**不帶 --yes** 跑一次給使用者看計畫：
   ```bash
   ./ops/release.sh tag api <x.y.z>             # backend tag dry-run
   ./ops/release.sh tag ios <x.y.z> --new-version-after-ready <previous>  # iOS 新版本 tag dry-run
   ```
   使用者明確同意後，才加 `--yes` 真送（commit 版號檔 + 打 tag + push origin main）：
   ```bash
   ./ops/release.sh tag api <x.y.z> --yes
   ./ops/release.sh tag ios <x.y.z> --new-version-after-ready <previous> --yes
   ```
   **`tag` 不碰生產**——要真正上生產（backend 部署 / iOS 上傳）走下面的 `release`。

4b. **release**（三平面統一發布，**碰生產、須使用者明確同意**；dry-run 預設）：
   ```bash
   ./ops/release.sh release backend <x.y.z>                 # dry-run：bump→tag→deploy
   ./ops/release.sh release backend <x.y.z> --yes           # 執行
   ./ops/release.sh release ios <x.y.z> --new-version-after-ready <previous>        # dry-run：bump→upload→tag
   ./ops/release.sh release ios <x.y.z> --new-version-after-ready <previous> --yes  # 執行
   ```
   - `release backend`：bump→tag→`deploy`（推 **origin/prod** → felix reconciler 健康 gate 部署 wordnexus.lol）。
   - `release ios`：previous 必須匹配 latest local `ios/*` tag，新版必須嚴格遞增；bump→`ios_release.sh --upload`→成功後才 tag/push。flag 是已查 ASC 的離線 attestation，不會自行打網路。被拒/未上架同版重送不走此路，走 `bump-build ios` + `ios_release.sh --upload`。
   - 執行 `release` 前**不可先跑 4a tag-only**；否則 release 會因 tag 已存在而拒絕。
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
