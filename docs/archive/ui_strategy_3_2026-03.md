<!-- doc-meta
tier: archive
authority: frozen
update_trigger: none
scope:
  - ios/BooksAndVocab/
verified_against: frozen
-->
# UI Strategy 3: Verification & Governance

Date: 2026-03-10
Scope: `ios/BooksAndVocab`

文檔網絡：
- 主設計規範：`docs/sop/ui-design.md`
- 開發入口：`docs/sop/ios.md`
- 元件 / pattern inventory：`docs/reference/ui/components.md`
- 狀態矩陣：`docs/reference/ui/state_matrix.md`

## 這條策略要解決什麼

避免 design system 在未來幾週或幾個功能之後退化。

目前最大的風險不是沒有系統，而是：
- 已經有 token、motion、component、state 規範
- 但還缺少足夠強的驗證與治理層

結果就是：
- 某次 UI 調整很容易把舊畫面悄悄弄壞
- 新功能容易回到 literal + ad hoc animation
- 文檔存在，但不一定能約束實作

## 成功定義

- 關鍵畫面有快速視覺驗證入口
- 新增 UI 時有明確的採用規則
- 重要 state 與 motion 不再只能靠人工記憶維持

## 不包含什麼

- 不追求完整 snapshot infra 一次到位
- 不把所有 preview 都做到完美
- 不引入過重的流程工具

## 主要工作包

### Work Package A: Preview Matrix

優先畫面：
- Settings
- Subscription paywall
- Reader translation panel
- Reader settings panel
- Today Review
- Sync

每個畫面至少覆蓋：
- default
- loading
- empty
- error
- active / success / completed

要求：
- preview 要能固定高價值狀態
- 不依賴真實登入或真實後端回應

### Work Package B: Review Checklist

建立最短 UI review checklist：
- 有沒有直接寫 raw style / motion？
- 這個 state 是否已有現成 pattern？
- error / empty / loading 是否都被覆蓋？
- motion 是否沿用 `AppMotion` 與共享 transition？

這份 checklist 不求完整，只求讓開發時有低負擔自查。

### Work Package C: 文件治理

讓文件真的可用，而不是持續長大。

主文檔負責：
- `docs/sop/ui-design.md`
- `docs/sop/ios.md`
- `docs/sop/architecture.md`

附錄負責：
- inventory
- state matrix
- 各條優化策略

規則：
- 改規範，更新主文檔
- 改現況，更新附錄
- 小實作不要求每次同步改所有文件

## 執行順序

1. ✅ 補最有價值的 preview — 已完成，覆蓋 6 個核心畫面
2. ✅ 寫最短 checklist — `docs/reference/ui/review_checklist.md`
3. ✅ 把主文檔與附錄的責任切乾淨 — 主文檔已更新文檔網絡連結

## 可並行原因

這條線不需要等待：
- token 收斂完成
- state/motion 收斂完成

它可以先建立防退化護欄，與其他兩條策略同步推進。

## 風險

- preview 做太多，維護成本爆炸
- checklist 太重，反而沒人用
- 文件治理變成又一層官僚

## 降風險方式

- 只覆蓋高頻頁面與高風險 state
- checklist 維持在 5 到 8 個檢查點
- 主文檔控制入口，附錄只存細節

## 驗收指標

### 定量

- 核心畫面都有至少一組 preview matrix
- 新增 UI 時 raw token / motion 例外下降
- `docs/` 主入口維持少量、高槓桿

### 定性

- 改 token 或 layout 後，能快速知道哪個畫面受影響
- 團隊或未來的自己，不需要重新從頭理解整套 UI 規則

## 完成後的產出

- 可持續維護的 UI 驗證層
- 更低的 regression 風險
- 更低的認知負擔與更高的開發一致性
