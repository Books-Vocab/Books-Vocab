<!-- doc-meta
tier: reference
scope:
  - ios/BooksBrowser
  - backend/src/kg
verified_against: 4eaa92b
-->
# iOS Smoke Test Checklist

每次發版前 15 分鐘內跑完一輪。

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

- [ ] 詞庫頁「待收錄」tab 顯示剛加入的詞
- [ ] 同步到 KG 後，「知識庫」tab 顯示
- [ ] 「關聯圖」tab 顯示圖譜
- [ ] 複習按鈕觸發 TodayReview
- [ ] 滑動歸類正常（認識 / 模糊 / 不認識）

## 5. 登入 / 訂閱 / 刪帳號

- [ ] 設定頁登入（Google / Apple）
- [ ] 登入後訂閱狀態正確顯示
- [ ] 訂閱 paywall 可開啟
- [ ] 危險操作區域「刪除帳號」有二次確認
- [ ] 登出後狀態清除正確
