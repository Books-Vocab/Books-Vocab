<!-- doc-meta
tier: reference
authority: derived
update_trigger: manual
scope:
  - ios/BooksAndVocab/
  - backend/src/kg/
verified_against: 6ff5bcf10
-->
# iOS Smoke Test Checklist

每次發版前 15 分鐘內跑完一輪。

## 0. Release readiness

- [ ] iOS 新 marketing version：ASC 已確認 previous version 完成審查；dry-run 使用 `release ios <new> --new-version-after-ready <previous>`
- [ ] iOS 未上架／被拒重送：marketing version 不動，只跑 `bump-build ios`，不得使用 new-version attestation
- [ ] release dry-run 的 iOS 順序為 bump→upload→tag；upload failure 不應留下新 release tag

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

## 5. 登入 / 訂閱 / 刪帳號

- [ ] 設定頁登入（Google / Apple）
- [ ] 登入後訂閱狀態正確顯示
- [ ] 訂閱 paywall 可開啟
- [ ] 危險操作區域「刪除帳號」有二次確認
- [ ] 登出後狀態清除正確
