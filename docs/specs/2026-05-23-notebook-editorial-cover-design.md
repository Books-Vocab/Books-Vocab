<!-- doc-meta
tier: reference
authority: derived
update_trigger: design-decision
scope:
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCoverPatterns.swift
  - ios/BooksAndVocab/Views/Vocabulary/Components/NotebookStackedCoverView.swift
  - ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookListView.swift
  # VocabReviewBanner.swift: 不修檔,但 NotebookListView 解除引用
verified_against: HEAD
-->
# Notebook Editorial Cover & List — Design Spec

## Context

緊接 `2026-05-23-notebook-editorial-stack-design.md`(stack 立體層 + Morandi palette 已落地),本 spec 解決使用者對 **NotebookListView 整體頁** 在 editorial 維度仍未到位的回饋:

| 使用者抱怨 | 根因（驗證後） |
|---|---|
| Cover 像 placeholder 色塊 | Cover composition = 純色 + 中央白字 name,沒有「書封」應有的資訊層次。Palette 已是 editorial Morandi(本 spec 不動),問題在 **cover 構圖太薄** |
| 「使用中」藍 pill 跟整體色系衝突 | `skin.palette.accent`(Morandi blue) 與奶黃 CTA / cream paper 不同族;pill 形態本身也與 editorial book metaphor 不符 |
| 「今日複習」橫卡擠了 4 件事 | 標題 + 副標 stats + filter chip + 黃色 CTA 並排,違反 editorial 克制原則 |
| 「2 本 notebook + 1 個 + 卡」構圖失衡 | 偶數本時 `NotebookAddCard` 自佔一 row,與 toolbar 既存 `+` 入口重複 |
| 卡片底部 5 項 metadata 過密 | `cardCount` / `pendingCount` / `ProgressCapsule` / `dueCount` chip / `unlearnedCount` chip 並排,與 editorial cover 上下打架 |

使用者明示路線 = 「乾淨簡約、少文字數字、細框線 editorial、滿版不要太多留白」,且**前三張畫面(單字本詳情、Sync、總覽)為基準保留**,本次只重做 NotebookListView 整頁。

## Goals

1. Cover 從「色塊 + 中央白字」升級成自帶資訊層次的 editorial book cover
2. 卡片底部 metadata 收斂到「進度條 + 條件渲染的到期 chip」,真正落地「少文字數字」
3. 「使用中」狀態以 spine hairline 靜默化,移除 accent blue pill
4. 「今日複習」入口從橫卡降級為 section header + inline brandHero pill,與單字本詳情頁 `VocabReviewCTAPill` 同視覺族群
5. 網格永遠對稱:移除 inline `NotebookAddCard`,`+` 收斂到 toolbar 單一入口
6. 維持既有 editorial stack(cream paper ghost、deterministic rotation、Morandi palette)不動

## Non-Goals

- 不重做 hero variant 的整體 layout(單本 21:10 寬扁 cover 保留,僅套用本 spec 的 cover composition + 底部 metadata 收斂)
- 不動 Morandi palette / pattern 渲染管線 / stack metric
- 不改 `NotebookEditSheet` 編輯流程
- 不改 sync / 資料模型 / coordinator
- 不動其他 feature(VocabularyListView 內頁、Library、總覽、Sync sheet)

## Design Decisions

### D1 — Cover Composition: editorial book-cover layout

Cover 內容由「整面色塊 + 中央白字 name」改為以下 layout:

```
┌─────────────────────────────────────┐
│ ▎                                   │  ← spine hairline (only if isActive)
│ ▎                                   │
│ ▎   Notebook Name                   │  ← serif, 左對齊, padding s3
│ ▎   ─────────────                   │  ← hairline rule (1pt, cover color darken 1 階)
│ ▎                                   │
│ ▎                       240 詞      │  ← monoLabel, 右下對齊, padding s3
└─────────────────────────────────────┘
```

**Composition hosting decision(避免 NotebookStackedCoverView 既有 rotation/jitter 邏輯外露):**

Editorial composition(name / rule / count / spine)以 **`.overlay` modifier** 套在既有 cover view 之上,而非塞進 `NotebookStackedCoverView` / `NotebookCoverView` 內部。Overlay 是頂層 cover layer 的 child(整個 stacked overlay 容器套在頂層 stacked 卡之上;非 sibling),因此自動跟隨 `NotebookCard.coverRotation` 的 ±1.5° 旋轉。

| 變體 | Host view | 套法 |
|---|---|---|
| `.grid` | `NotebookStackedCoverView`(已 render 頂層彩色封面) | `.overlay { EditorialCoverComposition(...) }` 直接掛該 view |
| `.hero` | `NotebookCoverView`(平面 21:10) | 同樣 `.overlay { EditorialCoverComposition(...) }` |

新增私有 view `EditorialCoverComposition`(僅 `NotebookCard.swift` 內部使用,不導出),參數 = `name / cardCount / coverColor / isActive / style`。內部用 `ZStack(alignment: .topLeading)` 排 spine + name + rule + count。

**規格:**

| 元素 | Token / 規格 |
|---|---|
| Name typography | `AppFonts.serif(size: 22, bold: true)`(grid) / `AppFonts.serif(size: 32, bold: true)`(hero);`lineLimit(2)` + `.truncationMode(.tail)` |
| Name 對齊 | leading + top,padding `AppSpacing.s3`(grid) / `AppSpacing.s4`(hero) |
| Name 字色 | `skin.palette.primaryText`(scheme-aware,light = `#37352F`,dark = `#E6E6E3`)。**fallback rule** 見下 |
| Hairline rule | name 下方 `AppSpacing.s2` gap,寬度 = cover 寬 × 0.25,色 = `coverColor.darken(0.3)`(HSB brightness ×0.7,helper 加進 `NotebookPalette` 作為 `static func darken(_ color: Color, by amount: Double) -> Color`);厚度 `AppMetrics.dividerStandard` |
| cardCount | `skin.typography.monoLabel`(=`AppFonts.mono(size: 10, bold: true)`),字色 `skin.palette.secondaryText`;格式 `L10n.format("%@ 詞", "\(count)")` 例如 `240 詞`;`.monospacedDigit()`;trailing + bottom 對齊,padding `AppSpacing.s3` |
| cardCount = 0 處理 | 整行隱藏(0 詞 = 空殼,顯示反而強調空狀態) |
| Pattern overlay | 維持 opt-in;有 pattern 時其 opacity 從 0.3 降到 0.18(在 `NotebookCoverPatterns.swift` 渲染處改),讓 serif name 為視覺主角 |
| 老卡片白字 fallback | **不保留**;legacy notebook cover 一律 render 為新 layout |

**AA Contrast — 文字色 fallback rule:**

`skin.palette.primaryText` light(`#37352F`)對 Morandi palette 12 色 cover 對比實測:

| 色 | hex | 對 `#37352F` 比 | AA pass |
|---|---|---|---|
| 森林 | `#B1C5AE` | 8.1:1 | ✓ |
| 海洋 | `#AFC2D3` | 8.0:1 | ✓ |
| 琥珀 | `#DEC69C` | 9.4:1 | ✓ |
| 紫藤 | `#C5B2D0` | 7.9:1 | ✓ |
| 珊瑚 | `#DCABA4` | 8.3:1 | ✓ |
| 石墨 | `#AFB2B7` | 7.1:1 | ✓ |
| 薄荷 | `#B7D2C9` | 8.8:1 | ✓ |
| 靛藍 | `#ADABCB` | 7.0:1 | ✓ |
| 玫瑰 | `#DEBAC2` | 8.5:1 | ✓ |
| 焦糖 | `#D2B69D` | 8.4:1 | ✓ |
| 天空 | `#C5DAE2` | 9.0:1 | ✓ |
| 薰衣草 | `#C3BCCF` | 8.0:1 | ✓ |

全部 ≥ AA 4.5:1。**dark mode**:`primaryText` dark(`#E6E6E3`)對 Morandi 色覆蓋 cover 時對比下降,但 cover 在 dark mode 仍走相同 hex(NotebookPalette 不分 scheme),最低色(琥珀對 `#E6E6E3`)約 ~2.2:1 fail AA。**dark mode fallback**:Cover 色在 dark mode 套 `.brightness(-0.2)` 自動加深,實測後最差色仍 ≥ AA。實作時加 unit test `NotebookCoverContrastTests` 鎖回歸。

Hairline rule 對 cover 對比若 < 3:1(以 `coverColor.darken(0.3)` 預設配比已 ≥ 3:1),不再額外 fallback。

### D1.1 — Pattern Overlay Opacity 0.18

`NotebookCoverPatterns.swift` 內 6 種 pattern Canvas 渲染,opacity 從原本 0.3 改為 0.18(加 token `NotebookStackMetrics.patternOpacity = 0.18`,單一來源)。改動範圍 = pattern Canvas 內 `.fill(...).opacity(...)` 統一引此 token。

### D2 — Bottom Metadata: ProgressCapsule + conditional due chip

卡片底部從 5 項 metadata 收斂到最多 2 項:

```
┌─ cover area ─────────────────────┐
│  (D1)                            │
└──────────────────────────────────┘
  ── hairline ──────────────────────  ← AppMetrics.dividerStandard
  ████████░░░░░░░░░░  ⏰ 12 到期       ← ProgressCapsule + conditional chip
```

**規格:**

| 元素 | 規格 |
|---|---|
| `cardCount` 顯示位置 | 已在 cover D1,**底部不重複**(若 cover 因 count=0 隱藏,底部也不補) |
| ProgressCapsule | 維持既有元件,高度 5pt,色 = `skin.palette.accent`(track) + cover color(fill);**永遠 render** 保 row 高度;`totalSynced = 0` 時 progress = 0(track only) |
| Due chip | `dueCount > 0` 時 render `Label("\(dueCount) 到期", systemImage: "clock.badge")`,`skin.typography.monoLabel` + `.monospacedDigit()`,色 `skin.palette.warning`;`dueCount = 0` 時整 chip 移除(不 opacity=0 占位 — 底部 row 已由 ProgressCapsule 撐高,move-out 不破節奏) |
| **移除** | `pendingCount` chip / `unlearnedCount` chip / cardCount label(已上移) |
| Layout | `HStack(spacing: AppSpacing.s2)`,ProgressCapsule `.frame(maxWidth: .infinity)`,chip `.fixedSize(horizontal: true, vertical: false)` |
| Padding | `.horizontal, AppSpacing.s3` + `.vertical, AppSpacing.s2`(原 `cardPadding * 0.8` 改實值) |

**Rationale — 為何 unlearned / pending 移除而非保留:**
- `unlearnedCount` 進入 notebook 內頁(`VocabularyListView`)即在 stats row 顯示,首頁不需重複
- `pendingCount` 是 sync 狀態,出現在 hero `today review` 流程或 Sync sheet,首頁卡片不是合適位置
- `dueCount` 唯一保留 — 是 user 在 list view **唯一的 actionable signal**(決定點哪本進去複習)

### D3 — Active Indicator: spine hairline (replace pill)

移除「使用中」capsule pill。改以 cover 左邊緣 spine hairline 條:

```
spine = vertical strip on cover left edge
  width: 3pt (narrower than NotebookStackMetrics.layerInsetX = 4pt)
  color: NotebookPalette.darken(coverColor, by: 0.4) (HSB brightness ×0.6)
  height: cover 全高(從 cover top 至 cover bottom,不延伸至 metadata 區)
  zIndex: above pattern, below name/rule/count
  isActive == false → spine 不 render
```

**Placement(套 rotation):**

Spine 是 `EditorialCoverComposition` 內的 sibling(同 `ZStack`),因此跟 name/rule/count 一起在 `.overlay` 容器內,自動跟隨 `coverArea` 的 ±1.5° rotation 一起傾斜,不會脫離 cover 邊界。

**Rationale:**
- 書架書本的 spine 視覺信號是 editorial 族群最自然的「這本被使用」標記
- 3pt(< `layerInsetX` 4pt)確保 spine 視覺上明顯窄於下層 ghost 露出的紙頁寬,不會跟 ghost edge 視覺融合
- 不浪費 cover 內版面給 pill,name + count 可放大佔版

**Hero 例外**: hero(單本)永遠是 active,spine 不 render(冗餘)。

### D4 — Top Section: "今日複習" 入口

移除 `VocabReviewBanner` 卡片框,改用 page-level section header + inline `VocabReviewCTAPill`:

```
┌──── page top ────┐
│ 單字本           │  ← navigationTitle (large)
├──────────────────┤
│ 今日複習     ▶ 539│  ← section header row (no card frame)
│                  │
│ ┌──┐ ┌──┐        │  ← notebook grid
│ │  │ │  │        │
│ └──┘ └──┘        │
```

**規格:**

| 元素 | 規格 |
|---|---|
| 容器 | 無卡片;`HStack` 直接放在 `ScrollView` content,`.padding(.horizontal, pageHorizontalInset)` |
| 標題 | `Text("今日複習")` + `AppFonts.sectionTitle`(serif) + `skin.palette.primaryText` |
| Pill | 復用 `VocabReviewCTAPill`(已存在於 `VocabShellComponents+Actions.swift`),回傳值同 banner 三個 callback;`hasBothTypes` 時 Menu 拆全部/到期/未學;單型態時直接 button |
| Spacer | `Spacer(minLength: 8)` 中間 |
| 條件渲染 | `totalDueCount + totalUnlearnedCount == 0` 時整 row 隱藏(無事可做就不顯示入口) |
| Filter chip | 多 notebook 時的 `NotebookFilterChip` **移除自此 row**,改進 toolbar(見 D6) |

**Hero(單本)行為**: 不變,本 spec 不改 hero 內部 review 入口處理(hero 卡片身就是 entry point,未來 hero 可獨立設計);但 hero 場景的 banner 同樣套用此 section header 化(若有 due/unlearned)。

### D5 — Grid Balance: remove inline NotebookAddCard

`+` 入口收斂到 toolbar 唯一:

| 場景 | `+` 位置 |
|---|---|
| `notebooks.isEmpty` | `emptyState` 內 `VocabSceneShell` 的 primary CTA(維持既有) |
| `notebooks.count == 1`(hero) | toolbar `+`(維持既有) |
| `notebooks.count ≥ 2`(grid) | toolbar `+` 唯一;**移除 `NotebookAddCard` inline 卡** |

`NotebookAddCard` 元件本身**不刪除**(留作 future use,例如 onboarding empty state 變體),只是不再從 `NotebookListView` grid 呼叫。

### D6 — Filter Chip 安置

`NotebookFilterChip`(全部 / 有待複習 / 已學完 / 自訂排序)從 banner 內移出後:
- 多 notebook 時:進 toolbar 變一顆 `line.3.horizontal.decrease.circle` icon `Menu`,內容 = 原 `NotebookFilterChip` 的同一組 4 個 option(Picker binding 到 `reviewFilter`)。Toolbar `Menu` 而非 `Button`,因為這是「選項切換」非「動作」。
- 單 notebook 時:不顯示(scope filter 無意義,維持既有邏輯;`if notebooks.count >= 2` gate)

### D7 — Toolbar 最終形

```
[funnel?] [sort] [archive] [+]
```

Order(leading → trailing):
1. `line.3.horizontal.decrease.circle` filter Menu — **只在 `notebooks.count >= 2` 顯示**(D6)
2. `arrow.up.arrow.down` sort Menu — 始終顯示,但 `notebooks.isEmpty` 時 `.disabled(true)`(維持既有)
3. `archivebox` archive button — 始終顯示
4. `plus` create button — `.disabled(!authManager.isLoggedIn)`(維持既有)

四顆都已存在或從別處移入,不新增 SF Symbol。

### D8 — Sync Sheet Entry Point 保留性

`VocabReviewBanner` 解除引用後,Sync 流程的進入點仍維持透過 `TipView(SyncPendingTip())`(`NotebookListView.swift:72-74`,當 `pendingEntries.isEmpty == false` 時顯示)+ Settings → Sync 兩個既有路徑,**本 spec 不影響**。`pendingCount` 的視覺強提示由 TipView 承擔,首頁卡片上不再重複呈現。

## State Matrix

| 狀態 | Top section | Grid | Card 內容 | Toolbar |
|---|---|---|---|---|
| `notebooks.isEmpty`(未登入) | hidden | hidden | `VocabSceneShell.empty` 走登入 CTA | `[sort disabled] [archive] [+ disabled]` |
| `notebooks.isEmpty`(已登入) | hidden | hidden | `VocabSceneShell.empty` 走建立第一本 CTA | `[sort disabled] [archive] [+]` |
| `count == 1` 無 due/unlearned | hidden | hero card | D1 cover + D2 bottom(due chip 不 render) | `[sort] [archive] [+]` |
| `count == 1` 有 due/unlearned | `今日複習 ▶ N` | hero card | D1 + D2 + due chip | `[sort] [archive] [+]` |
| `count ≥ 2` 全部無 due/unlearned | hidden | grid (D5,無 add card) | D1 + D2(僅 progress) + D3 spine on active | `[filter] [sort] [archive] [+]` |
| `count ≥ 2` 有 due/unlearned | `今日複習 ▶ N` | grid (D5) | 同上 + chip when due > 0 | `[filter] [sort] [archive] [+]` |
| `count ≥ 2` filter active | `今日複習 ▶ N`(套 filter 後數字) | grid (D5) | 同上 | `[filter active state] [sort] [archive] [+]` |

## Acceptance Criteria

1. **Cover 視覺**: serif name 左上、hairline rule、`N 詞` 右下;pattern overlay 不蓋過 name;spine 只在 active grid card 顯示
2. **Active 標識**: 完全沒有 `Text("使用中")` 出現在 list view 任何位置;active 純靠 spine
3. **Bottom metadata**: 沒有 `cardCount` / `pendingCount` / `unlearnedCount` 字樣在底部;只有 ProgressCapsule + 可能的 due chip
4. **Top banner**: `VocabReviewBanner` 元件**不再被 NotebookListView 引用**(元件本身不刪,留作他用);頂部入口是 `Text("今日複習") + VocabReviewCTAPill` 直接放 `ScrollView` content,無卡片背景
5. **Grid**: `count ≥ 2` 時最後一格不再出現 plus 卡;`+` 只在 toolbar
6. **Toolbar**: 多 notebook 時顯示 funnel filter button;單 notebook 不顯示
7. **既有 editorial stack 不變**: cream paper ghost / Morandi palette / deterministic rotation / NotebookDeckButtonStyle press 互動全保留
8. **Hero 變體**: 套用 D1 cover composition + D2 bottom metadata,但**不**渲染 spine(D3 例外),且**不**改既有 21:10 比例
9. **A11y**: Cover serif name `accessibilityLabel` 仍是 notebook name;due chip `accessibilityLabel` 含「N 張到期」;spine 純視覺、`accessibilityHidden(true)`
10. **i18n**: 「今日複習」/「到期」/「詞」走 `L10n` / `.localized`;不新增 raw 中文字串

## Visual Mockup(ASCII)

### Grid card (active, with due)

```
┌──────────────────────────┐
│▎                         │  ← spine 4pt, cover color darken
│▎ 我的單字本               │  ← serif 22pt semibold, primaryText
│▎ ────                    │  ← hairline rule, cover color darken
│▎                         │
│▎              627 詞      │  ← mono caption, secondaryText
├──────────────────────────┤  ← cardBorder hairline (既有)
│ ████████░░░░░  ⏰ 538 到期│  ← ProgressCapsule + due chip
└──────────────────────────┘
```

### Grid card (inactive, no due)

```
┌──────────────────────────┐
│                          │  ← (no spine)
│  Sec                     │
│  ────                    │
│                          │
│               18 詞       │
├──────────────────────────┤
│ ████░░░░░░░░░░           │  ← progress only (chip omitted)
└──────────────────────────┘
```

### Page top (multi-notebook, with due)

```
單字本                       [⏷] [↕] [📦] [+]
今日複習                       ▶ 539
┌────────┐  ┌────────┐
│ 我的... │  │ Sec    │
│ 627 詞  │  │ 18 詞   │
│ ░██ ⏰  │  │ ░░     │
└────────┘  └────────┘
```

## Doc Sync(per CLAUDE.md doc-as-code)

實作 PR 必須同步更新以下 doc:

| Doc | 更新內容 |
|---|---|
| `docs/reference/feature_boundary/notebook.md` | `NotebookCard.swift` 行數 / 結構描述更新(加 `EditorialCoverComposition` 私有 view);`NotebookAddCard` 註記為「unused from list, kept for future onboarding empty state」 |
| `docs/reference/ui/state_matrix.md` | 加 Notebook list 狀態覆蓋表(對齊本 spec State Matrix) |
| `docs/reference/ui/components.md` | 移除/標記「`VocabReviewBanner` 已從 NotebookListView 解除引用」;補「`VocabReviewCTAPill` 現亦用於 list view」 |
| `docs/reference/product_surface.md` | Notebook bookshelf 段補:editorial cover composition / spine active indicator |

## Open Questions

(無 — 設計細節已透過對話釐清完畢)

## Out of Scope (跟進 spec)

- Hero 變體獨立 design pass(目前僅套用 D1/D2 cover composition,hero layout 整體未重做)
- VocabularyListView 內頁(單字本詳情)editorial 一致性 review
- Library tab / 總覽 tab 的 editorial 化(user 表態前兩者已可接受)

## References

- `2026-05-23-notebook-editorial-stack-design.md` — 立體堆卡 + Morandi palette 前置
- `docs/sop/ui-design.md` — design token 規範
- `docs/reference/feature_boundary/notebook.md` — Notebook feature scope
- `ios/BooksAndVocab/Views/Vocabulary/Components/VocabShellComponents+Actions.swift:144` — `VocabReviewCTAPill` 既有元件
- `ios/BooksAndVocab/Views/Vocabulary/Components/VocabReviewBanner.swift` — 將被 NotebookListView 解除引用的舊 banner
