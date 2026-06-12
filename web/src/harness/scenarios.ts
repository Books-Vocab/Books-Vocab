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
  // Composite layer (batch-3): Sync (.fill opaque full-frame, bookshelf pattern) /
  // Notebooks·Card (opaque component crop, editorial book-row) / KG Vocab Row
  // (WordRow molecule, transparent component crop, varying width).
  sync: ['ready', 'running', 'completed', 'partial', 'full'],
  'notebooks-card': ['grid-two', 'hero-fresh', 'hero-long-name', 'hero-heavy'],
  'kg-vocab-row': ['default', 'highlighted'],
  // Composite layer (batch-4): Book Card (transparent component crop, bookshelf cell) /
  // Subscription Gate Card (opaque component crop, ProAccessGateCard) / Account
  // Section (transparent full-frame, settings auth/subscription rows).
  'book-card': ['placeholder-epub', 'pdf-badge', 'progress-mid', 'progress-complete', 'long-title', 'a11y3'],
  'subscription-gate-card': ['happy-path', 'long-copy-stress', 'narrow-width-320pt', 'dynamic-type-accessibility3'],
  // account-section（transparent .fill full-frame）：iOS catalog 在真實裝置幀渲染，
  // ScrollView 內容落在 in-app chrome 之下。逐列掃 ios-normalized：header glyph top
  // ≈240 capture px、card top ≈320（與 settings-preferences 同 catalog 同位）。修正前
  // 全 5 case RMSE 0.33–0.36（單位混淆：把 capture px 當 CSS px），改 surface 頂部
  // inset 75 CSS px（=225 capture px）對齊後過 ceiling。SoT: SettingsAccountSection.swift。
  'account-section': ['logged-out', 'logged-out-auth-error', 'subscribed-active', 'subscription-loading', 'pricing-unavailable'],
  // Composite layer (batch-5): Review Fold trio（皆 .fill transparent full-frame，
  // sampleCard/segment over transparent，shots transparent:true）。SoT:
  // ReviewFoldScenarios.swift（Chevron Pill / Paper Fold / Segment）。
  'review-fold-chevron': ['collapse-handle', 'on-card-backdrop'],
  'review-fold-paper': ['expanded', 'three-quarter', 'half', 'quarter', 'nearly-folded'],
  'review-fold-segment': ['single', 'stacked-group'],
  // Composite layer (batch-6): Podcast cards — Continue Card（component crop transparent，
  // 5 action 投影）+ Episode Row（full-frame transparent，單一 variants 列表）+ Series Card
  // （component crop transparent，封面+host）。SoT: PodcastContinueCard/Row/SeriesCard scenarios。
  'podcast-continue-card': ['in-progress', 'fresh', 'completed', 'free-preview', 'gated'],
  'podcast-episode-row': ['variants'],
  'podcast-series-card': ['normal', 'long-host', 'narrow', 'a11y3'],
  // Composite layer (batch-7): Notebook Cover（component crop transparent，封面 pattern/色）+
  // Notebooks Stack（full-frame：single 透明 / grid 不透明）+ Word Detail Card（component
  // crop 不透明 page-bg，CardDocument）。SoT: NotebookCover/NotebookList/WordDetail scenarios。
  'notebook-cover': ['all-patterns-blue', 'color-swatches', 'solid-no-pattern', 'long-name-truncate', 'shows-name-false', 'image-fallback'],
  'notebooks-stack': ['state-active', 'state-inactive', 'd1-cover-basic', 'depth-100', 'd1-empty'],
  'word-detail-card': ['full', 'compact', 'no-example'],
  // Composite layer (batch-8): Settings sections — Preferences/Review（full-frame transparent，
  // section over transparent）+ Subscription（component crop transparent，ProAccess section）。
  'settings-preferences': ['with-auto-sync', 'auto-sync-off', 'logged-out'],
  'settings-review': ['intensive', 'relaxed', 'frozen', 'custom'],
  'settings-subscription': ['pro-active', 'loading', 'pricing-unavailable', 'inactive-free'],
  // Composite layer (batch-9): Podcast Bubble Cell（component crop transparent，字幕泡泡）+
  // Podcast Hero（full-frame transparent，series hero）+ Rail Card（component crop transparent）。
  'podcast-bubble-cell': ['highlighted-active', 'idle-non-current', 'right-aligned-speaker', 'vocab-highlighted'],
  'podcast-hero': ['full-meta', 'long-title-multi-host', 'fresh-no-meta', 'episodes-only', 'a11y3'],
  'podcast-rail-card': ['resume', 'no-progress', 'long-title', 'large-numbers', 'a11y3'],
  // Composite layer (batch-10): Account Auth Summary（full-frame transparent 垂直置中）+
  // Login Sheet（full-frame opaque page）+ Welcome（full-frame opaque onboarding）。
  'account-auth-summary': ['initials-free', 'initials-pro', 'long-name-email-overflow'],
  'login-sheet': ['default', 'authenticating', 'error'],
  'welcome': ['step-1-capture', 'step-2-link', 'step-3-review', 'step-3-dark'],
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
