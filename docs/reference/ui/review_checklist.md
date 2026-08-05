<!-- doc-meta
tier: reference
authority: derived
update_trigger: manual
scope:
  - ios/BooksAndVocab/
verified_against: afda0439c
-->
# UI Review Checklist

Date: 2026-03-10
Scope: `ios/BooksAndVocab`

文檔網絡：
- 設計規範主文檔：`docs/sop/ui-design.md`
- 元件 / pattern inventory：`docs/reference/ui/components.md`
- 狀態覆蓋矩陣：`docs/reference/ui/state_matrix.md`

## 用途

新增或修改 UI 時的最短自查清單。
不求完整，只求讓開發時有低負擔自查入口。

---

## Checklist

### 1. Token 與 Style

- [ ] 有沒有直接寫 raw color / font / spacing？
  → 優先用 `AppSkin`、`AppMetrics`、`ReaderPresentationMetrics`
- [ ] 有沒有直接寫 `.spring(...)` / `.easeOut(...)` 等 raw motion？
  → 優先用 `AppMotion` 語意 token

### 2. Component 復用

- [ ] 這個 UI 場景有沒有現成 pattern？
  → 查 `docs/reference/ui/components.md`
- [ ] 是否已有對應的 shared component？
  → Empty State → `AppEmptyState*` / `VocabEmptyState*`
  → State Message → `AppStateMessage*` / `VocabStateMessageCard`
  → Hero Status → `VocabStatusHero`
  → Panel / Overlay → `TranslationPanel` / `ReaderSettingsPanel` + motion tokens

### 3. State 覆蓋

- [ ] loading 狀態有覆蓋嗎？
- [ ] empty 狀態有覆蓋嗎？
- [ ] error 狀態有覆蓋嗎？
- [ ] success / completed 狀態是否需要明確 feedback？

### 4. Motion 一致性

- [ ] motion 是否沿用 `AppMotion` 與共享 `AnyTransition`？
  → panel 開合 → `panelState`
  → phase 切換 → `phaseChange`
  → feedback → `feedbackPulse` + `feedbackBadge`
  → overlay → `overlayFade`
- [ ] 同類互動跨 feature 是否共用同一 token？

### 5. Preview 驗證

- [ ] 關鍵狀態有對應的 `#Preview` 嗎？
- [ ] preview 是否能固定高價值狀態（不依賴真實登入或後端）？

### 6. Mochi pass（北極星五條）

對齊 `docs/sop/ui-design.md` 的 Mochi 化北極星：

- [ ] 頁面 bg 與 toolbar / tab bar 是否同色？（避免 chrome 改色分區）
- [ ] cards 是否預設無 border？分區是否改用 `AppMetrics.dividerAirMargin = 16` 的 hr-style divider？
- [ ] shadow 是否限制在 z0 / z1（list/resting）或 z3+（modal/overlay）？無 raw `.shadow(...)`？
- [ ] 強調色是否限制在四軸（`brandHero` / `ctaCritical` / `accent` / `inlineCode`）內？無第五色亂入？
- [ ] 非按鈕互動是否只動 bg-color / opacity，無 transform？

---

## 何時用

- 新增畫面或重大 UI 修改時，快速過一遍
- PR review 時作為 UI 面向的檢查參考
- 不需要逐項簽核，有意識地掃過即可
