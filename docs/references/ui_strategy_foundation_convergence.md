# UI Strategy 1: Foundation Convergence

Date: 2026-03-10
Scope: `booksbrowser_ios/BooksBrowser`

文檔網絡：
- 主設計規範：`docs/ui-design.md`
- 元件 / pattern 現況：`docs/references/ui_component_pattern_inventory.md`
- 狀態矩陣：`docs/references/ui_state_matrix.md`
- 架構脈絡：`docs/architecture.md`

## 這條策略要解決什麼

把目前已經存在的 token、shared shell、feature skin，收斂成更穩的基礎設施。

核心問題不是「沒有 design system」，而是：
- Vocabulary 很成熟
- Reader / Settings / Bookshelf 仍有局部 literal
- app-wide shared layer 滲透率還不夠高

這條策略的目標是讓新畫面更難繞過系統，讓舊畫面更容易回收到系統。

## 成功定義

- `Reader / Settings / Bookshelf` 的高頻區塊優先使用 shared component 或 feature wrapper
- raw `.font(.system...)` 收斂到 0
- `AppSectionHeader`、shared state card、shared row / card container 的採用率明顯提升
- 新增 UI 時，不再先從 literal 開始拼，而是先從 token / component 選型

## 不包含什麼

- 不重做產品流程
- 不新增商業邏輯
- 不先碰 backend entitlement 或 API
- 不把所有 feature 視覺強行拉成同一風格

## 主要工作包

### Work Package A: Shared Shell 擴展

目標：
- 把現在只在少數畫面使用的 shared shell 擴成 app-wide 常用基礎

優先抽象：
- section shell
- settings/info row
- inline action group
- card header + footer
- key-value / status row

落點檔案：
- `BooksBrowser/UIComponents/AppShellComponents.swift`
- `BooksBrowser/UIComponents/AppSurface.swift`
- `BooksBrowser/UIComponents/MorandiButtonStyle.swift`

### Work Package B: Reader / Settings Literal 清理

目標：
- 把剩餘 hardcoded 字級、paper color、局部 spacing 收回 token 或 style layer

優先清理：
- `ReaderSettingsVocabPresenter.swift`
- `ReaderSettingsPanelPresenter.swift`
- `ReaderViewPresenter.swift`
- `SettingsPresenter.swift`

規則：
- 若屬於 feature 風格，收回 `ReaderContentStyle` 或 `VocabSkin`
- 若屬於 app-wide chrome，收回 `AppTheme` / `AppShellMetrics`

### Work Package C: Shared Component 採用遷移

目標：
- 不只建立元件，還要把現有畫面改成真的採用

優先畫面：
- Settings
- Reader settings panel
- Reader translation states
- Bookshelf shell / placeholder / loading overlay

## 執行順序

1. 凍結 shared component vocabulary
2. 清 Reader / Settings 最高頻 literal
3. 把 Settings / Bookshelf / Reader 的 section shell 換成 shared layer
4. 再補零碎 feature wrapper

## 可並行原因

這條線主要在前端基礎層，不依賴：
- backend API 更動
- 商業流程改版
- 資料模型調整

它可以和 state/motion 收斂、preview/governance 同步進行。

## 風險

- 過度抽象，導致 shared layer 反而難用
- 把 feature-specific 視覺誤抽成 app-wide 通用元件
- 一次收太多 component，反而讓命名混亂

## 降風險方式

- 先抽 pattern，不先抽所有樣式變體
- shared layer 只放高頻重複結構
- feature wrapper 保持存在，不把 Vocabulary 風格塞回 app shell

## 驗收指標

### 定量

- raw `.font(.system...)` 檔案數：`2 -> 0`
- shared section / state message / card container 的採用檔案數持續上升
- `Reader / Settings / Bookshelf` 的 literal 命中數下降

### 定性

- 新增一個 settings-like section 時，不需要再手拼 row/card/header
- Reader 與 Settings 的基礎 chrome 不再是兩套完全獨立語法

## 完成後的產出

- 更穩的 app-wide shared component vocabulary
- 更乾淨的 Reader / Settings style layer
- 更高的 UI 可重用性與維護效率
