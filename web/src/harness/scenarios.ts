// Harness scenario taxonomy — mirrors the iOS Catalog addressing
// ({surface, scenario, appearance}) so parity capture URLs map 1:1 onto
// Catalog snapshot PNGs. Scenario ids correspond to the iOS Debug scenario
// files (ios/BooksAndVocab/Debug/Scenarios/*Scenarios.swift)。

/** 每個 surface 自帶 scenario taxonomy；首位 = 該 surface 的預設 scenario。 */
export const SURFACE_SCENARIOS = {
  bookshelf: ['populated', 'single', 'empty'],
  settings: ['subscribed-active', 'logged-out', 'pricing-unavailable'],
  notebook: ['populated', 'single'],
  // Reader surface — chrome（R1，6 態）+ Translation panel（R2）+ 面板群（R3）。
  //   chrome：對齊 ReaderChromeScenarios.swift（paper 色帶在 fixture，與 light/dark
  //     appearance 軸正交）。首位 reading-compact = 預設 scenario。
  //   translation（R2，6 態）：對齊 ReaderScenarios.swift「Reader · Translation」
  //     （layout .fill = scrim + bottom-sheet panel，無 reader 本體）。
  //   R3 面板（toc-/settings-/notebook- 前綴）：對齊 ReaderScenarios.swift（TOC /
  //     Settings）與 ReaderNotebookPickerScenarios.swift。各面板 catalog 以 .fill
  //     佈局渲染，故 web 也 full-bleed 還原（非 docked 在 live chrome 上）。
  reader: [
    'reading-compact',
    'reading-expanded',
    'loading-render',
    'loading-vocab',
    'reading-translation',
    'error-open-failed',
    // Translation panel（R2，ReaderScenarios.swift · Reader · Translation 6 態）
    'translation-expanded',
    'translation-collapsed',
    'translation-loading',
    'translation-error',
    'translation-explain-only',
    'translation-explanation-error',
    // TOC（ReaderScenarios.swift · Reader · TOC 4 態）
    'toc-loaded',
    'toc-loading',
    'toc-empty',
    'toc-failed',
    // Settings（ReaderScenarios.swift · Reader · Settings 3 態，bounds-max = PR #929）
    'settings-normal',
    'settings-bounds-min',
    'settings-bounds-max',
    // Notebook picker（ReaderNotebookPickerScenarios.swift 4 態）
    'notebook-follow-global',
    'notebook-one-bound',
    'notebook-stress',
    'notebook-empty',
  ],
  // Selection Toolbar — 對齊 SelectionToolbarScenarios.swift 3 態（vocab 多選
  // 底欄；selectionCount 0 全灰 disabled，>0 啟用 archive+delete）。首位
  // selection-multiple = 預設 scenario。
  'selection-toolbar': ['selection-multiple', 'selection-single', 'selection-none'],
  // Reader Selection Tile — 對齊 ReaderSelectionTileScenarios.swift 3 態
  // （chrome tile：selected mutedFill+primaryText / unselected pageBackground+
  // secondaryText / 並排對比）。首位 selection-pair = 預設 scenario。
  'selection-tile': ['selection-pair', 'selection-selected', 'selection-unselected'],
  // Vocab Shell 原語層（atom）— 對齊 VocabShellComponentsScenarios.swift。
  //   sort-pill（3 態）：arrow.up.arrow.down + 當前排序 label（複習優先/字母序/
  //     難度），muted-fill Capsule。catalog scene 畫布透明、layout .compressed
  //     intrinsic 裁切，故 web 走 crop=component + transparent capture。
  'vocab-sort-pill': ['default', 'alphabetical', 'difficulty'],
  // Vocab Shell/Components primitive (atom) layer — all透明 catalog component scenes,
  // crop=component capture. SoT: VocabShellChromeScenarios / VocabShellComponentsScenarios /
  // VocabComponentScenarios. See each surface dir for fidelity notes.
  'vocab-accessory-icon-button': ['default'],
  'vocab-slider-row': ['interactive'],
  'vocab-tone-chip': ['variants', 'long-text'],
  'vocab-chrome-icon-button': ['close', 'toned-filter'],
  'vocab-inline-action-button': ['accent-default', 'toned'],
  'vocab-search-field': ['empty', 'with-query'],
  'vocab-section-header': ['title-only', 'icon-trailing'],
  'vocab-review-progress-bar': ['ratios', 'detail-only', 'over-100'],
  'vocab-review-cta-pill': ['both-types', 'due-only', 'unlearned-only'],
  'vocab-tab-selector': ['no-counts', 'with-counts', 'zero-counts'],
  'vocab-toolbar-glyph': ['plain', 'with-badge', 'badge-stress'],
  'vocab-empty-state': ['card-no-action', 'card-with-action', 'content-basic', 'content-guidance-action'],
  // Composite layer (batch-2): collocation sheet (.fill transparent full-frame) /
  // KG empty state (.fill opaque full-frame).
  // NOTE: banner-review deferred (task #8) — opaque card on transparent tight-crop is
  // hypersensitive to card-edge scaling; web card height vs ref (serif/CJK line-metric
  // delta) pushed RMSE to 0.26 (> 0.25 ceiling). Re-derive with font-metric height tuning.
  'collocation-explain': ['loaded-short', 'loaded-long', 'loaded-with-delete'],
  'kg-empty-state': ['no-entries-cta', 'no-entries-logged-out', 'search-no-match', 'single-filter-due', 'multi-filter'],
  vocabulary: ['populated', 'single', 'empty'],
  'today-review': ['front', 'back', 'production-front', 'production-back'],
  podcast: ['preview-player', 'locked-gate'],
  // Overview（統計儀表板）— 對齊 StatsViewScenarios.swift 2 態（Stats View）。
  //   populated：graph card（catalog 內 WKWebView no-op → loading spinner）+ 連續/
  //     最長學習雙卡（10/10 天）+ 學習日曆 heatmap（trailing「J」叢集）+ 複習預測
  //     section header（chart 本體在 2556 fold 之下被 capture 裁掉）。fixture 凍結
  //     0608 catalog 的 now-relative 渲染輸出（streak=10、heatmap trailing 叢集），
  //     非重算日期邏輯——參考 PNG 已凍結，故 fixture 鏡射其像素輸出而非 seed。
  //   empty：尚無學習資料置中空卡（chart.bar.xaxis）。
  overview: ['populated', 'empty'],
} as const

export type SurfaceId = keyof typeof SURFACE_SCENARIOS
export type ScenarioId<S extends SurfaceId = SurfaceId> = (typeof SURFACE_SCENARIOS)[S][number]

export const APPEARANCES = ['light', 'dark'] as const
export type Appearance = (typeof APPEARANCES)[number]

/** Discriminated union（以 surface 鍵窄化）：路由端 switch(config.surface)
 *  後 scenario 自動收斂為該 surface 的合法 id。 */
export type HarnessConfig = {
  [S in SurfaceId]: { surface: S; scenario: ScenarioId<S>; appearance: Appearance }
}[SurfaceId]

/** 無 ?surface 參數時固定 bookshelf：第一刀的 capture URL（只有
 *  ?scenario/?appearance）必須持續解析到同一頁，parity manifest 不必回填。 */
const DEFAULT_SURFACE: SurfaceId = 'bookshelf'

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

/** Capture URLs are generated by the parity pipeline; unknown values fall back
 *  to the defaults instead of hard-failing so a bad URL still renders a frame
 *  (the parity diff will catch the mismatch). Scenario 合法性以 surface 為界：
 *  跨 surface 的 scenario id 視同未知，落回該 surface 的預設。 */
export function resolveHarnessConfig(search: string): HarnessConfig {
  const params = new URLSearchParams(search)
  const surface = pick(params.get('surface'), Object.keys(SURFACE_SCENARIOS) as SurfaceId[], DEFAULT_SURFACE)
  const scenarios = SURFACE_SCENARIOS[surface]
  return {
    surface,
    scenario: pick(params.get('scenario'), scenarios, scenarios[0]),
    appearance: pick(params.get('appearance'), APPEARANCES, 'light'),
  } as HarnessConfig // surface 與 scenario 由同一 surface 取值，配對恆合法
}
