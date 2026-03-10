# UI Strategy 2: State & Motion Experience

Date: 2026-03-10
Scope: `booksbrowser_ios/BooksBrowser`

文檔網絡：
- 主設計規範：`docs/ui-design.md`
- 狀態矩陣：`docs/references/ui_state_matrix.md`
- 元件 / pattern inventory：`docs/references/ui_component_pattern_inventory.md`

## 這條策略要解決什麼

把「有動畫、有 state」提升成「狀態可預期、過場有語意、回饋一致」。

目前的基礎已存在：
- `AppMotion` 已建立
- Reader / Review / Sync 主幹已有 motion token
- state card / empty state / hero status pattern 已成形

但還有幾個落差：
- 有些錯誤仍只是文案，不是明確 error state
- 有些 fallback 只是 detail text，不是正式 state
- partial failure / empty / silent success 還不一致

## 成功定義

- 高頻 flow 的每個關鍵 state 都有明確 presentation
- 同一類 state 在不同 feature 使用相同語法
- motion 不只是好看，而是能強化 continuity、hierarchy、feedback

## 不包含什麼

- 不做大規模視覺重設計
- 不先追求新動畫，而是先追求一致
- 不處理低頻 debug-only 畫面

## 主要工作包

### Work Package A: State Gap Closure

優先補齊：
- Reader translation empty state
- Reader translation / explanation error state
- Today Review persistence failure
- Settings subscription unavailable / fallback pricing
- Sync partial failure 的層級化呈現

原則：
- `empty`、`error`、`retryable`、`partial success` 不可以只靠一行字帶過

### Work Package B: Motion Policy Completion

目標：
- 讓 motion token 變成互動規則，而不是數值倉庫

優先規則：
- panel open / close
- state card appear / disappear
- success / save feedback
- review card swap
- sync phase transition

要求：
- 有 visual feedback 的地方，優先搭配 haptic policy
- 不為了「更會動」而新增沒有語意的動畫

### Work Package C: Paywall / Access State Clarity

這次 entitlement 已區分：
- `app_store`
- `admin`

接下來要把來源差異更清楚落到 UX：
- active / trial / inactive / admin-granted
- restore 可用與不可用
- 來源說明與管理動作分層

## 執行順序

1. 先補最影響信任感的 missing state
2. 再統一 motion policy
3. 最後把 paywall / access state 文案與層級收乾淨

## 可並行原因

這條線主要處理：
- state presentation
- motion consistency
- UX feedback policy

它與 foundation convergence 只有少量共享元件依賴，可平行進行。

## 風險

- 把所有錯誤都做成大卡片，造成資訊過重
- 過度套用 motion，反而影響閱讀與操作節奏
- 把 admin / App Store 來源差異顯示得太複雜

## 降風險方式

- 大狀態用 hero / card，小狀態維持 inline message
- 只在 state change 與操作回饋點加動畫
- paywall 只顯示對使用者有用的來源差異，不暴露實作細節

## 驗收指標

### 定量

- `ui_state_matrix` 中高頻缺口數下降
- 主要 flow 的 critical states 全部轉為顯式 presentation
- 高頻互動不再出現明顯 silent failure

### 定性

- 使用者能清楚知道：
  - 現在在哪個 state
  - 這個 state 能做什麼
  - 下一步是什麼

## 完成後的產出

- 更順、更可信的主流程體驗
- 更一致的 state language
- 更成熟的 motion semantics
