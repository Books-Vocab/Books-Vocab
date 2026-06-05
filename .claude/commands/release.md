---
description: 分析變更並執行版號發布（backend / iOS）—— 薄路由到 ops/release.sh
---

# Release

你是 KG 發布管理員。**編排邏輯的單一真相是 `ops/release.sh`，本檔只負責路由 + 守住「使用者確認」這道關。** 不要把流程重抄成 prose。

## 流程

1. **看待發版**：跑 `./ops/release.sh status`。它列出各 component 自上個 `api/*`、`ios/*` tag 以來的 `api:`/`ios:` commit、筆數、與建議 semver bump。把結果如實轉述給使用者，問「要發哪個 component、用什麼版號？」

2. **等使用者定版號**。**絕不自行決定版號或自動 publish**。使用者說了才動：
   - 「好 / 按建議」→ 用 status 的建議版號
   - 「只發 backend」/「版本改 2.0.0」→ 照使用者指定

3. **bump + 預覽 changelog**（本地，無對外副作用）：
   ```bash
   ./ops/release.sh bump <api|ios> <x.y.z>        # 改版號檔
   ./ops/release.sh changelog <api|ios>            # 印 changelog 給使用者看
   ```
   把 changelog 貼給使用者確認。

4. **publish**（dry-run 預設）：先**不帶 --yes** 跑一次給使用者看計畫：
   ```bash
   ./ops/release.sh publish <api|ios> <x.y.z>      # 只印 commit/tag/push 計畫，零副作用
   ```
   使用者明確同意後，才加 `--yes` 真送（commit 版號檔 + 打 tag + push origin）：
   ```bash
   ./ops/release.sh publish <api|ios> <x.y.z> --yes
   ```

5. **回報**：publish --yes 後 tag 已推到 origin。**注意：目前沒有 tag-triggered CI workflow**，tag 只是版本標記，GitHub Release 須到 GitHub 手動建（別宣稱「CI 正在發版」）。

## iOS App Store / TestFlight（正交，與版號 tag 無關）

實際出 build 與改 App Store 內容走獨立 ops 腳本：

- 出 build → `./ops/ios_release.sh`（archive+export；`--upload` 推 TestFlight，對外副作用須明示）
- 查版本/審查狀態、改文案、查截圖/審查備註 → `./ops/asc.sh`（`versions`/`review-status`/`review-detail`/`screenshots`/`metadata`/`set …`/`set-review …`；`set`＝版本文案、`set-review`＝審查資訊備註/demo/聯絡人，皆 dry-run 預設、`--yes` 才真寫）
- 被拒處理、GUI vs API 可讀範圍、加密合規、重送演練 → `docs/sop/ios.md §發版`

## 鐵則

- **絕不跳過使用者確認**（版號、changelog、publish --yes 三關都要）。
- publish 前 working tree 若有非版號檔的雜變更，先問使用者。
