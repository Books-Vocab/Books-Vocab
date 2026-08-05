<!-- doc-meta
tier: reference
authority: derived
update_trigger: manual
scope:
  - ios/BooksAndVocab/
  - backend/src/kg/
verified_against: 0a90b4f8e
-->
# iOS Smoke Test Checklist

每次發版前 15 分鐘內跑完一輪。

## 0. Release readiness

- [ ] iOS 新 marketing version：`./ops/release.sh release ios <new>` dry-run 通過。guard 直接讀 repo 的上架 tag / build tag 自行檢查，**沒有 attestation flag 可帶**（`--new-version-after-ready` 已移除，傳了會 hard-error）；被擋就代表真的有版本狀態未確認，先跑 `./ops/release.sh shipped ios`
- [ ] iOS 未上架／被拒重送：marketing version 不動，走 `./ops/release.sh resubmit ios`（bump-build→upload→封 build tag），不走 `release`
- [ ] release / resubmit dry-run 的 iOS 順序為 bump→upload→封 `ios/<x.y.z>+<build>`；upload failure 不應留下 commit/tag/push
- [ ] `./ops/release.sh status` 的 ios 段沒有「目前的 (version, build) 沒有 build tag」警告（有＝這顆 build 出去了卻沒留 build→commit 紀錄，事後不可重建）
- [ ] 上架後補跑 `./ops/release.sh shipped ios --yes`，依 ASC 物化 `ios/<x.y.z>`（版號事實 owner 表見 `docs/sop/release.md`）

## 1. 首次啟動與 Welcome

- [ ] 冷啟動顯示 Welcome 頁面
- [ ] 四個 feature 介紹頁面可滑動
- [ ] 「開始使用」導向書架
- [ ] 「先體驗看看」進入 Demo Mode

## 2. 匯入書籍到閱讀

- [ ] 書架點擊 + 按鈕觸發檔案選擇器
- [ ] 選擇 EPUB 後匯入成功，書籍出現在書架
- [ ] 點擊書籍封面進入 Reader
- [ ] Reader loading 動畫正常，頁面渲染完成

## 3. Reader 查詞 / 翻譯 / 加入詞庫

- [ ] 長按選詞，翻譯面板彈出
- [ ] 翻譯結果顯示（或 quota 提示）
- [ ] 詞彙自動加入「待收錄」
- [ ] 底線標記出現在頁面上
- [ ] 再次點擊已標記詞彙，面板彈出（已儲存狀態）

## 4. Vocabulary Review Flow

- [ ] 詞庫頁顯示剛加入的詞（同步前為「待收錄」狀態）
- [ ] 同步到 KG 後，詞出現在 review-state tab（未學習 / 待複習 / 已複習）
- [ ] 圖譜入口開啟，關聯圖正常顯示
- [ ] 複習按鈕觸發 TodayReview
- [ ] 滑動歸類正常（認識 / 模糊 / 不認識）

## 4b. Explore（共享牌組庫）

> 2026-08-05 起 `exploreEnabled` 在 Release 亦為 true，Release shell 因此多一個頂層 tab。
> 空目錄是可能的出貨狀態（官方牌組注入是獨立的 approval-gated 步驟），故空狀態必驗。

- [ ] 「探索」tab 出現在 tab bar，可進入且被選中
- [ ] **未登入**也能瀏覽目錄（不跳登入牆、不出現錯誤橫幅）
- [ ] 目錄為空時顯示**空狀態**（不是錯誤態）；有牌組時 grid 正常渲染
- [ ] 點入牌組 detail：卡數 / 範例卡 / 官方 badge 顯示
- [ ] 未登入時複製 CTA 停用並說明原因；登入後可複製進指定單字本，卡片即時可複習
- [ ] macOS（Catalyst）側邊欄同樣有「探索」，工具列刷新鈕可用

## 5. 登入 / 訂閱 / 刪帳號

- [ ] 設定頁登入（Google / Apple）
- [ ] 登入後訂閱狀態正確顯示
- [ ] 訂閱 paywall 可開啟
- [ ] 危險操作區域「刪除帳號」有二次確認
- [ ] 登出後狀態清除正確
