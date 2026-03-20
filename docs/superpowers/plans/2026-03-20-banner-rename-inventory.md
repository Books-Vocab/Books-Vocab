# AppBanner 改名 + Inventory 更新

Branch: `worktree-banner-rename`
Depends on: none
Commit Prefix: `ios:`
## Model: sonnet

## 問題

1. AppBanner 與 AppStateMessage* 系列命名不一致
2. 新元件（VocabSceneShell、AppSheetModifier）未記錄在 ui_component_pattern_inventory.md

## Tasks

### Task 1: 讀取現有 inventory
讀取 `docs/references/ui_component_pattern_inventory.md`

### Task 2: 更新 inventory
在適當的層級下新增：

**App Shell Layer**:
- `AppBanner` — 內嵌狀態橫幅（網路/同步/錯誤），支援 retry + dismiss 按鈕
- `AppSheetModifier` — `.appSheet(.large/.medium/.adaptive)` 統一 sheet presentation

**Vocabulary Skin Layer**:
- `VocabSceneShell` — 四態容器（loading/empty/error/content），統一 Vocabulary 場景狀態管理

**Presentation Layer**:
- `ReaderSettingsPresenter` — 閱讀器設定，variant enum 分派 glass/vocab 佈局

**Models/Tokens**:
- `RetryPolicy` — 網路重試策略（指數退避 + Retry-After）
- Animation convenience methods（`.animatePhaseChange()` 等）

### Task 3: 編譯驗證（無需，只改 .md）

## 注意
- 不改名 AppBanner（改名的代價高於收益，保持現狀但在 inventory 中標註其用途）
- inventory 格式遵循現有風格

## Files Modified
- `docs/references/ui_component_pattern_inventory.md`
