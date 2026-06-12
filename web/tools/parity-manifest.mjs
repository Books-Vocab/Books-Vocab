/**
 * parity-manifest.mjs — single source of truth for the web-app ⟷ iOS parity
 * case list, shared by shots.mjs (capture URLs), compare.mjs and
 * parity-audit.mjs.
 *
 * `ref` addresses the iOS counterpart by Catalog taxonomy (see
 * design-system/parity/ios-ref.mjs); `params` drives the harness URL
 * (?surface/?scenario/?appearance — web/src/harness/scenarios.ts) so capture
 * and reference stay addressed by one entry. `params.surface` 省略 = bookshelf
 * （harness 的向後相容預設）。
 */
export const PARITY = [
  {
    case: 'bookshelf-populated-light',
    params: { scenario: 'populated', appearance: 'light' },
    ref: { surface: 'Bookshelf View', scenario: 'Populated · mixed formats', appearance: 'light' },
    note: '書架 populated (light)',
  },
  {
    case: 'bookshelf-single-light',
    params: { scenario: 'single', appearance: 'light' },
    ref: { surface: 'Bookshelf View', scenario: 'Single book', appearance: 'light' },
    note: '書架 single (light)',
  },
  {
    case: 'bookshelf-empty-light',
    params: { scenario: 'empty', appearance: 'light' },
    ref: { surface: 'Bookshelf View', scenario: 'Empty shelf', appearance: 'light' },
    note: '書架 empty (light)',
  },
  {
    case: 'bookshelf-populated-dark',
    params: { scenario: 'populated', appearance: 'dark' },
    ref: { surface: 'Bookshelf View', scenario: 'Populated · mixed formats', appearance: 'dark' },
    note: '書架 populated (dark)',
  },
  {
    case: 'bookshelf-single-dark',
    params: { scenario: 'single', appearance: 'dark' },
    ref: { surface: 'Bookshelf View', scenario: 'Single book', appearance: 'dark' },
    note: '書架 single (dark)',
  },
  {
    case: 'bookshelf-empty-dark',
    params: { scenario: 'empty', appearance: 'dark' },
    ref: { surface: 'Bookshelf View', scenario: 'Empty shelf', appearance: 'dark' },
    note: '書架 empty (dark)',
  },
  {
    case: 'settings-subscribed-light',
    params: { surface: 'settings', scenario: 'subscribed-active', appearance: 'light' },
    ref: { surface: 'Settings', scenario: 'Subscribed Active', appearance: 'light' },
    note: '設定 subscribed (light)',
  },
  {
    case: 'settings-logged-out-light',
    params: { surface: 'settings', scenario: 'logged-out', appearance: 'light' },
    ref: { surface: 'Settings', scenario: 'Logged Out', appearance: 'light' },
    note: '設定 logged-out (light)',
  },
  {
    case: 'settings-pricing-light',
    params: { surface: 'settings', scenario: 'pricing-unavailable', appearance: 'light' },
    ref: { surface: 'Settings', scenario: 'Pricing Unavailable', appearance: 'light' },
    note: '設定 pricing-unavailable (light)',
  },
  {
    case: 'settings-subscribed-dark',
    params: { surface: 'settings', scenario: 'subscribed-active', appearance: 'dark' },
    ref: { surface: 'Settings', scenario: 'Subscribed Active', appearance: 'dark' },
    note: '設定 subscribed (dark)',
  },
  {
    case: 'settings-logged-out-dark',
    params: { surface: 'settings', scenario: 'logged-out', appearance: 'dark' },
    ref: { surface: 'Settings', scenario: 'Logged Out', appearance: 'dark' },
    note: '設定 logged-out (dark)',
  },
  {
    case: 'settings-pricing-dark',
    params: { surface: 'settings', scenario: 'pricing-unavailable', appearance: 'dark' },
    ref: { surface: 'Settings', scenario: 'Pricing Unavailable', appearance: 'dark' },
    note: '設定 pricing-unavailable (dark)',
  },
  {
    case: 'notebook-populated-light',
    params: { surface: 'notebook', scenario: 'populated', appearance: 'light' },
    ref: { surface: 'Notebook List View', scenario: 'Populated · multiple notebooks', appearance: 'light' },
    note: '單字本 populated (light)',
  },
  {
    case: 'notebook-single-light',
    params: { surface: 'notebook', scenario: 'single', appearance: 'light' },
    ref: { surface: 'Notebook List View', scenario: 'Single notebook', appearance: 'light' },
    note: '單字本 single (light)',
  },
  {
    case: 'notebook-populated-dark',
    params: { surface: 'notebook', scenario: 'populated', appearance: 'dark' },
    ref: { surface: 'Notebook List View', scenario: 'Populated · multiple notebooks', appearance: 'dark' },
    note: '單字本 populated (dark)',
  },
  {
    case: 'notebook-single-dark',
    params: { surface: 'notebook', scenario: 'single', appearance: 'dark' },
    ref: { surface: 'Notebook List View', scenario: 'Single notebook', appearance: 'dark' },
    note: '單字本 single (dark)',
  },
  // Reader chrome（R1）— ReaderChromeScenarios.swift 6 態，皆 light appearance
  // （catalog 在 light 渲染；reader paper sepia 帶在 fixture，與 appearance 軸正交）。
  {
    case: 'reader-reading-compact-light',
    params: { surface: 'reader', scenario: 'reading-compact', appearance: 'light' },
    ref: { surface: 'Reader View · Chrome', scenario: 'Reading · Compact Header', appearance: 'light' },
    note: 'Reader compact header (light)',
  },
  {
    case: 'reader-reading-expanded-light',
    params: { surface: 'reader', scenario: 'reading-expanded', appearance: 'light' },
    ref: { surface: 'Reader View · Chrome', scenario: 'Reading · Expanded Header', appearance: 'light' },
    note: 'Reader expanded header (light)',
  },
  {
    case: 'reader-loading-render-light',
    params: { surface: 'reader', scenario: 'loading-render', appearance: 'light' },
    ref: { surface: 'Reader View · Chrome', scenario: 'Loading · Render', appearance: 'light' },
    note: 'Reader loading render (light)',
  },
  {
    case: 'reader-loading-vocab-light',
    params: { surface: 'reader', scenario: 'loading-vocab', appearance: 'light' },
    ref: { surface: 'Reader View · Chrome', scenario: 'Loading · Mark Vocab', appearance: 'light' },
    note: 'Reader loading mark-vocab (light)',
  },
  {
    case: 'reader-reading-translation-light',
    params: { surface: 'reader', scenario: 'reading-translation', appearance: 'light' },
    ref: { surface: 'Reader View · Chrome', scenario: 'Reading · Translation Overlay', appearance: 'light' },
    note: 'Reader translation overlay chrome (light) — panel 屬 R2',
  },
  {
    case: 'reader-error-open-failed-light',
    params: { surface: 'reader', scenario: 'error-open-failed', appearance: 'light' },
    ref: { surface: 'Reader View · Chrome', scenario: 'Error · Open Failed', appearance: 'light' },
    note: 'Reader error open-failed (light)',
  },
  // Selection Toolbar（R4）— SelectionToolbarScenarios.swift 3 態（vocab 多選底欄）。
  // 元件級 scene：iOS catalog 自 0611 起把 SelectionToolbar 以 intrinsic 高度
  // 緊裁切擷取（1179×192 = 64pt，純元件、無 in-app safe-area）。故 web 也以
  // `crop` 選元件 DOM 擷取（`?crop=component` 令 surface 收掉 44.7pt safe-area
  // padding，元件還原至同等 64pt intrinsic bounds），令 ref/shot 同界對比，
  // 不再把 192px 元件硬拉到全 2556px frame（拉伸即量測框架失配，舊 RMSE 0.87）。
  {
    case: 'selection-toolbar-multiple-light',
    params: { surface: 'selection-toolbar', scenario: 'selection-multiple', appearance: 'light', crop: 'component' },
    crop: '.selection-toolbar-surface',
    ref: { surface: 'Selection Toolbar', scenario: 'Multiple selected', appearance: 'light' },
    note: 'Selection toolbar multiple selected (light)',
  },
  {
    case: 'selection-toolbar-single-light',
    params: { surface: 'selection-toolbar', scenario: 'selection-single', appearance: 'light', crop: 'component' },
    crop: '.selection-toolbar-surface',
    ref: { surface: 'Selection Toolbar', scenario: 'Single selected', appearance: 'light' },
    note: 'Selection toolbar single selected (light)',
  },
  {
    case: 'selection-toolbar-none-light',
    params: { surface: 'selection-toolbar', scenario: 'selection-none', appearance: 'light', crop: 'component' },
    crop: '.selection-toolbar-surface',
    ref: { surface: 'Selection Toolbar', scenario: 'No selection (disabled)', appearance: 'light' },
    note: 'Selection toolbar disabled (light)',
  },
  // Reader Selection Tile（R4，stacked on PR #929）— ReaderSelectionTileScenarios.swift
  // 3 態（chrome tile：selected mutedFill / unselected pageBackground / 並排對比）。
  {
    case: 'selection-tile-pair-light',
    params: { surface: 'selection-tile', scenario: 'selection-pair', appearance: 'light' },
    ref: { surface: 'Reader Selection Tile', scenario: 'Selected vs Unselected', appearance: 'light' },
    note: 'Reader selection tile selected-vs-unselected (light)',
  },
  {
    case: 'selection-tile-selected-light',
    params: { surface: 'selection-tile', scenario: 'selection-selected', appearance: 'light' },
    ref: { surface: 'Reader Selection Tile', scenario: 'Selected', appearance: 'light' },
    note: 'Reader selection tile selected (light)',
  },
  {
    case: 'selection-tile-unselected-light',
    params: { surface: 'selection-tile', scenario: 'selection-unselected', appearance: 'light' },
    ref: { surface: 'Reader Selection Tile', scenario: 'Unselected', appearance: 'light' },
    note: 'Reader selection tile unselected (light)',
  },
  // Vocab Shell · Sort Pill（元件庫原語層第一個 atom）— VocabShellComponentsScenarios.swift
  // 3 態。catalog 元件 scene 畫布透明（component-isolated，layout .compressed
  // intrinsic 388×209@dpr3 ≈ pill 81×22pt + padding 24）。web crop=component 截
  // `.vocab-shell-component-surface`（pill + padding 24 intrinsic box），
  // transparent:true → shots omitBackground 截圖，使 ref/shot 同為
  // pill-over-transparent（faint muted-fill 4% 不需 refCrop：refComponentBbox
  // 6% 閾值抓不到 4% 膠囊，反而會誤裁成只剩 icon+text）。
  {
    case: 'vocab-sort-pill-default-light',
    params: { surface: 'vocab-sort-pill', scenario: 'default', appearance: 'light', crop: 'component' },
    crop: '.vocab-shell-component-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Sort Pill', scenario: 'Default (複習優先)', appearance: 'light' },
    note: 'Vocab sort pill · default 複習優先 (light)',
  },
  {
    case: 'vocab-sort-pill-alphabetical-light',
    params: { surface: 'vocab-sort-pill', scenario: 'alphabetical', appearance: 'light', crop: 'component' },
    crop: '.vocab-shell-component-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Sort Pill', scenario: 'Alphabetical', appearance: 'light' },
    note: 'Vocab sort pill · alphabetical 字母序 (light)',
  },
  {
    case: 'vocab-sort-pill-difficulty-light',
    params: { surface: 'vocab-sort-pill', scenario: 'difficulty', appearance: 'light', crop: 'component' },
    crop: '.vocab-shell-component-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Sort Pill', scenario: 'Difficulty', appearance: 'light' },
    note: 'Vocab sort pill · difficulty 難度 (light)',
  },
  // Translation panel（R2）— ReaderScenarios.swift「Reader · Translation」6 態
  // （layout .fill = scrim + bottom-sheet panel，gorgeous / adj.）。皆 light。
  //
  // 元件級量測（honest panel-crop，消滅黑底假 floor）：iOS catalog 這 6 態以
  // *透明* backdrop + 極淡 scrim（黑 α≈0.024）擷取 bottom-sheet 白卡；parity
  // normalize 的 `-alpha off` 把整片透明 void 壓成近黑，白卡對「~70% 黑底全幅」
  // 的 RMSE 被灌成 0.20–0.27 的 *合成假 floor*（真實 app 那片是活的 reader 頁、
  // 根本不渲染黑）。故兩端皆裁到元件本身再比：
  //   web 側 `crop: '.translation-panel'` → shots.mjs 直接截 panel DOM；
  //   ref 側 `refCrop: 'panel'` → parity-core 取 ref 不透明 bounding box 裁切
  //   （閾值清掉 α≈0.024 scrim）。黑 void 不進分母。沿用 selection-toolbar（#958）
  // 的元件級對比哲學，差別在 translation 的 catalog ref 仍是全幅，故由引擎在
  // audit 時做等效裁切。panel 浮在 34pt home-indicator 安全區上（iOS VStack 不
  // ignoresSafeArea），web 已對應補 `.reader-bottom-overlay` 底 inset。
  {
    case: 'reader-translation-expanded-light',
    params: { surface: 'reader', scenario: 'translation-expanded', appearance: 'light' },
    crop: '.translation-panel',
    refCrop: 'panel',
    ref: { surface: 'Reader · Translation', scenario: 'Expanded', appearance: 'light' },
    note: 'Translation panel expanded (light)',
  },
  {
    case: 'reader-translation-collapsed-light',
    params: { surface: 'reader', scenario: 'translation-collapsed', appearance: 'light' },
    crop: '.translation-panel',
    refCrop: 'panel',
    ref: { surface: 'Reader · Translation', scenario: 'Collapsed', appearance: 'light' },
    note: 'Translation panel collapsed (light)',
  },
  {
    case: 'reader-translation-loading-light',
    params: { surface: 'reader', scenario: 'translation-loading', appearance: 'light' },
    crop: '.translation-panel',
    refCrop: 'panel',
    ref: { surface: 'Reader · Translation', scenario: 'Loading', appearance: 'light' },
    note: 'Translation panel loading (light)',
  },
  {
    case: 'reader-translation-error-light',
    params: { surface: 'reader', scenario: 'translation-error', appearance: 'light' },
    crop: '.translation-panel',
    refCrop: 'panel',
    ref: { surface: 'Reader · Translation', scenario: 'Error', appearance: 'light' },
    note: 'Translation panel translation-error (light)',
  },
  {
    case: 'reader-translation-explain-only-light',
    params: { surface: 'reader', scenario: 'translation-explain-only', appearance: 'light' },
    crop: '.translation-panel',
    refCrop: 'panel',
    ref: { surface: 'Reader · Translation', scenario: 'Explain Only', appearance: 'light' },
    note: 'Translation panel explain-only (light)',
  },
  {
    case: 'reader-translation-explanation-error-light',
    params: { surface: 'reader', scenario: 'translation-explanation-error', appearance: 'light' },
    crop: '.translation-panel',
    refCrop: 'panel',
    ref: { surface: 'Reader · Translation', scenario: 'Explanation Error', appearance: 'light' },
    note: 'Translation panel explanation-error (light)',
  },
  {
    case: 'vocabulary-populated-light',
    params: { surface: 'vocabulary', scenario: 'populated', appearance: 'light' },
    ref: { surface: 'Vocabulary List View', scenario: 'Populated · mixed sync states', appearance: 'light' },
    note: '單字列表 populated (light)',
  },
  {
    case: 'vocabulary-single-light',
    params: { surface: 'vocabulary', scenario: 'single', appearance: 'light' },
    ref: { surface: 'Vocabulary List View', scenario: 'Single card', appearance: 'light' },
    note: '單字列表 single (light)',
  },
  {
    case: 'vocabulary-empty-light',
    params: { surface: 'vocabulary', scenario: 'empty', appearance: 'light' },
    ref: { surface: 'Vocabulary List View', scenario: 'Empty · zero data', appearance: 'light' },
    note: '單字列表 empty (light)',
  },
  {
    case: 'vocabulary-populated-dark',
    params: { surface: 'vocabulary', scenario: 'populated', appearance: 'dark' },
    ref: { surface: 'Vocabulary List View', scenario: 'Populated · mixed sync states', appearance: 'dark' },
    note: '單字列表 populated (dark)',
  },
  {
    case: 'vocabulary-single-dark',
    params: { surface: 'vocabulary', scenario: 'single', appearance: 'dark' },
    ref: { surface: 'Vocabulary List View', scenario: 'Single card', appearance: 'dark' },
    note: '單字列表 single (dark)',
  },
  {
    case: 'vocabulary-empty-dark',
    params: { surface: 'vocabulary', scenario: 'empty', appearance: 'dark' },
    ref: { surface: 'Vocabulary List View', scenario: 'Empty · zero data', appearance: 'dark' },
    note: '單字列表 empty (dark)',
  },
  {
    case: 'today-review-front-light',
    params: { surface: 'today-review', scenario: 'front', appearance: 'light' },
    ref: { surface: 'Today Review', scenario: 'Front', appearance: 'light' },
    note: '今日複習 recognition front (light)',
  },
  {
    case: 'today-review-back-light',
    params: { surface: 'today-review', scenario: 'back', appearance: 'light' },
    ref: { surface: 'Today Review', scenario: 'Back', appearance: 'light' },
    note: '今日複習 recognition back (light)',
  },
  {
    case: 'today-review-production-front-light',
    params: { surface: 'today-review', scenario: 'production-front', appearance: 'light' },
    ref: { surface: 'Today Review', scenario: 'Production · Front', appearance: 'light' },
    note: '今日複習 production front (light)',
  },
  {
    case: 'today-review-production-back-light',
    params: { surface: 'today-review', scenario: 'production-back', appearance: 'light' },
    ref: { surface: 'Today Review', scenario: 'Production · Back', appearance: 'light' },
    note: '今日複習 production back (light)',
  },
  {
    case: 'today-review-front-dark',
    params: { surface: 'today-review', scenario: 'front', appearance: 'dark' },
    ref: { surface: 'Today Review', scenario: 'Front', appearance: 'dark' },
    note: '今日複習 recognition front (dark)',
  },
  {
    case: 'today-review-back-dark',
    params: { surface: 'today-review', scenario: 'back', appearance: 'dark' },
    ref: { surface: 'Today Review', scenario: 'Back', appearance: 'dark' },
    note: '今日複習 recognition back (dark)',
  },
  {
    case: 'today-review-production-front-dark',
    params: { surface: 'today-review', scenario: 'production-front', appearance: 'dark' },
    ref: { surface: 'Today Review', scenario: 'Production · Front', appearance: 'dark' },
    note: '今日複習 production front (dark)',
  },
  {
    case: 'today-review-production-back-dark',
    params: { surface: 'today-review', scenario: 'production-back', appearance: 'dark' },
    ref: { surface: 'Today Review', scenario: 'Production · Back', appearance: 'dark' },
    note: '今日複習 production back (dark)',
  },
  {
    case: 'podcast-player-light',
    params: { surface: 'podcast', scenario: 'preview-player', appearance: 'light' },
    ref: { surface: 'Podcast Player View', scenario: 'Preview episode · player', appearance: 'light' },
    note: '播客播放器 preview (light)',
  },
  {
    case: 'podcast-locked-light',
    params: { surface: 'podcast', scenario: 'locked-gate', appearance: 'light' },
    ref: { surface: 'Podcast Player View', scenario: 'Locked · sign-in gate', appearance: 'light' },
    note: '播客 locked gate (light)',
  },
  {
    case: 'podcast-player-dark',
    params: { surface: 'podcast', scenario: 'preview-player', appearance: 'dark' },
    ref: { surface: 'Podcast Player View', scenario: 'Preview episode · player', appearance: 'dark' },
    note: '播客播放器 preview (dark)',
  },
  {
    case: 'podcast-locked-dark',
    params: { surface: 'podcast', scenario: 'locked-gate', appearance: 'dark' },
    ref: { surface: 'Podcast Player View', scenario: 'Locked · sign-in gate', appearance: 'dark' },
    note: '播客 locked gate (dark)',
  },
  // Overview（統計儀表板）— StatsViewScenarios.swift（Stats View），populated/empty
  // × light/dark。populated fixture 凍結 0608 catalog 的 now-relative 渲染輸出
  // （streak=10、heatmap trailing 叢集、graph card loading spinner、forecast header
  // 之下 chart 被 capture 裁掉），非重算日期邏輯。
  {
    case: 'overview-populated-light',
    params: { surface: 'overview', scenario: 'populated', appearance: 'light' },
    ref: { surface: 'Stats View', scenario: 'Populated', appearance: 'light' },
    note: '總覽統計 populated (light)',
  },
  {
    case: 'overview-empty-light',
    params: { surface: 'overview', scenario: 'empty', appearance: 'light' },
    ref: { surface: 'Stats View', scenario: 'Empty', appearance: 'light' },
    note: '總覽統計 empty (light)',
  },
  {
    case: 'overview-populated-dark',
    params: { surface: 'overview', scenario: 'populated', appearance: 'dark' },
    ref: { surface: 'Stats View', scenario: 'Populated', appearance: 'dark' },
    note: '總覽統計 populated (dark)',
  },
  {
    case: 'overview-empty-dark',
    params: { surface: 'overview', scenario: 'empty', appearance: 'dark' },
    ref: { surface: 'Stats View', scenario: 'Empty', appearance: 'dark' },
    note: '總覽統計 empty (dark)',
  },
  // Reader 面板群（R3）— TOC（ReaderScenarios.swift · Reader · TOC，4 態）。
  {
    case: 'reader-toc-loaded-light',
    params: { surface: 'reader', scenario: 'toc-loaded', appearance: 'light' },
    ref: { surface: 'Reader · TOC', scenario: 'Loaded', appearance: 'light' },
    note: 'Reader TOC loaded (light)',
  },
  {
    case: 'reader-toc-loading-light',
    params: { surface: 'reader', scenario: 'toc-loading', appearance: 'light' },
    ref: { surface: 'Reader · TOC', scenario: 'Loading', appearance: 'light' },
    note: 'Reader TOC loading (light)',
  },
  {
    case: 'reader-toc-empty-light',
    params: { surface: 'reader', scenario: 'toc-empty', appearance: 'light' },
    ref: { surface: 'Reader · TOC', scenario: 'Empty', appearance: 'light' },
    note: 'Reader TOC empty (light)',
  },
  {
    case: 'reader-toc-failed-light',
    params: { surface: 'reader', scenario: 'toc-failed', appearance: 'light' },
    ref: { surface: 'Reader · TOC', scenario: 'Failed', appearance: 'light' },
    note: 'Reader TOC failed (light)',
  },
  // Settings（ReaderScenarios.swift · Reader · Settings，3 態；bounds-max = PR #929）。
  {
    case: 'reader-settings-normal-light',
    params: { surface: 'reader', scenario: 'settings-normal', appearance: 'light' },
    ref: { surface: 'Reader · Settings', scenario: 'Normal', appearance: 'light' },
    note: 'Reader Settings normal (light)',
  },
  {
    case: 'reader-settings-bounds-min-light',
    params: { surface: 'reader', scenario: 'settings-bounds-min', appearance: 'light' },
    ref: { surface: 'Reader · Settings', scenario: 'Bounds (min)', appearance: 'light' },
    note: 'Reader Settings bounds-min 0.75x (light)',
  },
  {
    case: 'reader-settings-bounds-max-light',
    params: { surface: 'reader', scenario: 'settings-bounds-max', appearance: 'light' },
    ref: { surface: 'Reader · Settings', scenario: 'Bounds (max)', appearance: 'light' },
    note: 'Reader Settings bounds-max 2.0x (light, PR #929)',
  },
  // Notebook Picker（ReaderNotebookPickerScenarios.swift，4 態）。對齊當前 source
  // （NotebookBindingList，無 follow-global 列 / 無「預設」副標）。
  {
    case: 'reader-notebook-follow-global-light',
    params: { surface: 'reader', scenario: 'notebook-follow-global', appearance: 'light' },
    ref: { surface: 'Reader Notebook Picker', scenario: 'With notebooks · follow global', appearance: 'light' },
    note: 'Reader Notebook picker, none bound (light)',
  },
  {
    case: 'reader-notebook-one-bound-light',
    params: { surface: 'reader', scenario: 'notebook-one-bound', appearance: 'light' },
    ref: { surface: 'Reader Notebook Picker', scenario: 'With notebooks · one bound', appearance: 'light' },
    note: 'Reader Notebook picker, one bound (light)',
  },
  {
    case: 'reader-notebook-stress-light',
    params: { surface: 'reader', scenario: 'notebook-stress', appearance: 'light' },
    ref: { surface: 'Reader Notebook Picker', scenario: 'Many notebooks (stress)', appearance: 'light' },
    note: 'Reader Notebook picker, many (light)',
  },
  {
    case: 'reader-notebook-empty-light',
    params: { surface: 'reader', scenario: 'notebook-empty', appearance: 'light' },
    ref: { surface: 'Reader Notebook Picker', scenario: 'Empty — no notebooks', appearance: 'light' },
    note: 'Reader Notebook picker, empty (light)',
  },
  // --- Vocab primitive (atom) layer — 28 transparent component scenes (wf-vocab-atoms) ---
  {
    case: 'vocab-accessory-icon-button-default-light',
    params: { surface: 'vocab-accessory-icon-button', scenario: 'default', appearance: 'light', crop: 'component' },
    crop: '.vocab-accessory-icon-button-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Accessory Icon Button', scenario: 'Default fill', appearance: 'light' },
    note: 'chromeButtonSize(32) 方形 muted-fill RoundedRectangle(tiny=6) + SF trash(iconToolbar 15/medium) 系統紅 tone；scene 透明畫布，surface = button + .padding(24) intrinsic box（dpr3 240×240）',
  },
  // Vocab Shell · Slider Row（VocabShellChromeScenarios.swift 唯一態「Interactive」）。
  // 滿寬互動列、catalog scene 透明畫布（corner srgba 0,0,0,0），crop=component +
  // transparent omitBackground 截圖 → row-over-transparent。
  {
    case: 'vocab-slider-row-interactive-light',
    params: { surface: 'vocab-slider-row', scenario: 'interactive', appearance: 'light', crop: 'component' },
    crop: '.vocab-slider-row-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Slider Row', scenario: 'Interactive', appearance: 'light' },
    note: 'Vocab slider row · 間隔 0.6 interactive (light)',
  },
  // VocabToneChip（VocabComponents.swift:55）— 「Vocab Components · Tone Chip」2 態。
  // catalog component scene 畫布透明（corner srgba 0,0,0,0）→ crop=component +
  // transparent capture，crop 到 .vocab-tone-chip-surface（.padding(24) intrinsic box）。
  // Variants = VStack(spacing 16) 4 chips（blue/green/red/purple）；Long text = 單 indigo chip。
  {
    case: 'vocab-tone-chip-variants-light',
    params: { surface: 'vocab-tone-chip', scenario: 'variants', appearance: 'light', crop: 'component' },
    crop: '.vocab-tone-chip-surface',
    transparent: true,
    ref: { surface: 'Vocab Components · Tone Chip', scenario: 'Variants', appearance: 'light' },
    note: 'Vocab tone chip · variants 4 系統色 chip (light)',
  },
  {
    case: 'vocab-tone-chip-long-text-light',
    params: { surface: 'vocab-tone-chip', scenario: 'long-text', appearance: 'light', crop: 'component' },
    crop: '.vocab-tone-chip-surface',
    transparent: true,
    ref: { surface: 'Vocab Components · Tone Chip', scenario: 'Long text', appearance: 'light' },
    note: 'Vocab tone chip · long-text indigo capsule 隨內容延展 (light)',
  },
  {
    case: 'vocab-chrome-icon-button-close-light',
    params: { surface: 'vocab-chrome-icon-button', scenario: 'close', appearance: 'light', crop: 'component' },
    crop: '.vocab-chrome-icon-button-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Chrome Icon Button', scenario: 'Close', appearance: 'light' },
    note: 'Vocab chrome icon button · Close (xmark, secondaryText tone) light',
  },
  {
    case: 'vocab-chrome-icon-button-toned-filter-light',
    params: { surface: 'vocab-chrome-icon-button', scenario: 'toned-filter', appearance: 'light', crop: 'component' },
    crop: '.vocab-chrome-icon-button-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Chrome Icon Button', scenario: 'Toned (filter)', appearance: 'light' },
    note: 'Vocab chrome icon button · Toned filter (line.3.horizontal.decrease, .accentColor system blue) light',
  },
  // Vocab Shell · Inline Action Button（VocabShellChromeScenarios.swift 2 態）—
  // 純文字 Button(.plain)，font = appSkin.typography.body = sans 15
  // (= --text-subhead，非 --text-body=17)。component scene 透明 (corner srgba 0)。
  // Accent default = palette.accent；Toned = SwiftUI 系統 Color.secondary
  // (secondaryLabel rgba(60,60,67,0.6)，非 appSkin secondaryText)。
  {
    case: 'vocab-inline-action-button-accent-default-light',
    params: { surface: 'vocab-inline-action-button', scenario: 'accent-default', appearance: 'light', crop: 'component' },
    crop: '.vocab-inline-action-button-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Inline Action Button', scenario: 'Accent default', appearance: 'light' },
    note: 'Vocab inline action button · accent default 全部選取 (light)',
  },
  {
    case: 'vocab-inline-action-button-toned-light',
    params: { surface: 'vocab-inline-action-button', scenario: 'toned', appearance: 'light', crop: 'component' },
    crop: '.vocab-inline-action-button-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Inline Action Button', scenario: 'Toned', appearance: 'light' },
    note: 'Vocab inline action button · toned 取消 (Color.secondary) (light)',
  },
  {
    case: 'vocab-search-field-empty-light',
    params: { surface: 'vocab-search-field', scenario: 'empty', appearance: 'light', crop: 'component' },
    crop: '.vocab-search-field-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Search Field', scenario: 'Empty · prompt visible', appearance: 'light' },
    note: 'Vocab search field · empty prompt visible (light)',
  },
  {
    case: 'vocab-search-field-with-query-light',
    params: { surface: 'vocab-search-field', scenario: 'with-query', appearance: 'light', crop: 'component' },
    crop: '.vocab-search-field-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Search Field', scenario: 'With query', appearance: 'light' },
    note: 'Vocab search field · with query + clear button (light)',
  },
  // Vocab Shell · Section Header（VocabShellChromeScenarios.swift 2 態，.fillH 滿寬列）。
  // catalog component scene 透明（corner srgba 0）→ transparent:true，crop 到滿寬列盒
  // (.vocab-section-header-surface = wrapWide .frame(maxWidth:.infinity).padding(24)，
  // ref 1179×191 = 393×63.67pt@dpr3)。
  {
    case: 'vocab-section-header-title-only-light',
    params: { surface: 'vocab-section-header', scenario: 'title-only', appearance: 'light', crop: 'component' },
    crop: '.vocab-section-header-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Section Header', scenario: 'Title only', appearance: 'light' },
    note: 'Vocab section header · title only 已收錄 (light)',
  },
  {
    case: 'vocab-section-header-icon-trailing-light',
    params: { surface: 'vocab-section-header', scenario: 'icon-trailing', appearance: 'light', crop: 'component' },
    crop: '.vocab-section-header-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Section Header', scenario: 'Icon + trailing count', appearance: 'light' },
    note: 'Vocab section header · clock.badge + trailing 5 待複習 (light)',
  },
  // Vocab Components · Review Progress Bar — VocabComponentScenarios.swift 3 態
  // （VocabReviewProgressBar：detailLabel(mono 10 bold) + Capsule track(progress-track)
  //  + ReviewGradient fill，width 104 / height 5）。catalog scene 透明（corner srgba 0）
  //  → crop=component + transparent:true，crop 到 .vocab-review-progress-bar-surface。
  {
    case: 'vocab-review-progress-bar-ratios-light',
    params: { surface: 'vocab-review-progress-bar', scenario: 'ratios', appearance: 'light', crop: 'component' },
    crop: '.vocab-review-progress-bar-surface',
    transparent: true,
    ref: { surface: 'Vocab Components · Review Progress Bar', scenario: 'Ratios', appearance: 'light' },
    note: 'Vocab review progress bar · ratios 0/0.33/0.75/1.0 四條 (light)',
  },
  {
    case: 'vocab-review-progress-bar-detail-only-light',
    params: { surface: 'vocab-review-progress-bar', scenario: 'detail-only', appearance: 'light', crop: 'component' },
    crop: '.vocab-review-progress-bar-surface',
    transparent: true,
    ref: { surface: 'Vocab Components · Review Progress Bar', scenario: 'Detail only (no bar)', appearance: 'light' },
    note: 'Vocab review progress bar · ratio nil，僅 detailLabel 文字 (light)',
  },
  {
    case: 'vocab-review-progress-bar-over-100-light',
    params: { surface: 'vocab-review-progress-bar', scenario: 'over-100', appearance: 'light', crop: 'component' },
    crop: '.vocab-review-progress-bar-surface',
    transparent: true,
    ref: { surface: 'Vocab Components · Review Progress Bar', scenario: 'Over 100% (clamped)', appearance: 'light' },
    note: 'Vocab review progress bar · ratio 1.5 fill clamp 至 100% (light)',
  },
  // Vocab Shell · Review CTA Pill（VocabShellComponentsScenarios.swift「Vocab Shell ·
  // Review CTA Pill」3 態，layout .compressed = intrinsic pill）。catalog component
  // scene 透明畫布（corner srgba 0,0,0,0）→ transparent crop，同 vocab-sort-pill。
  // brandHero capsule + onBrandHero 前景；icon 依 due/unlearned 切 play.fill /
  // clock.badge / sparkles，count = monospacedDigit。
  {
    case: 'vocab-review-cta-pill-both-types-light',
    params: { surface: 'vocab-review-cta-pill', scenario: 'both-types', appearance: 'light', crop: 'component' },
    crop: '.vocab-review-cta-pill-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Review CTA Pill', scenario: 'Both types (menu)', appearance: 'light' },
    note: 'Vocab review CTA pill · both types (play.fill, 17) (light)',
  },
  {
    case: 'vocab-review-cta-pill-due-only-light',
    params: { surface: 'vocab-review-cta-pill', scenario: 'due-only', appearance: 'light', crop: 'component' },
    crop: '.vocab-review-cta-pill-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Review CTA Pill', scenario: 'Due only', appearance: 'light' },
    note: 'Vocab review CTA pill · due only (clock.badge, 5) (light)',
  },
  {
    case: 'vocab-review-cta-pill-unlearned-only-light',
    params: { surface: 'vocab-review-cta-pill', scenario: 'unlearned-only', appearance: 'light', crop: 'component' },
    crop: '.vocab-review-cta-pill-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Review CTA Pill', scenario: 'Unlearned only', appearance: 'light' },
    note: 'Vocab review CTA pill · unlearned only (sparkles, 8) (light)',
  },
  // Vocab Shell · Tab Selector（VocabShellComponentsScenarios.swift）— review-state
  // segmented bar，layout .fillH（全裝置寬 393pt）。catalog 元件 scene 畫布透明
  // （corner srgba 0）：transparent:true → shots omitBackground，使 ref/shot 同為
  // bar-over-transparent。crop 目標 = surface 自身（.vocab-tab-selector-surface，
  // bar + padding 24 的全寬 box）。selected pill = mutedFill 4%，三段均分寬。
  {
    case: 'vocab-tab-selector-no-counts-light',
    params: { surface: 'vocab-tab-selector', scenario: 'no-counts', appearance: 'light', crop: 'component' },
    crop: '.vocab-tab-selector-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Tab Selector', scenario: 'No counts · unlearned selected', appearance: 'light' },
    note: 'Vocab tab selector · no counts, unlearned selected (light)',
  },
  {
    case: 'vocab-tab-selector-with-counts-light',
    params: { surface: 'vocab-tab-selector', scenario: 'with-counts', appearance: 'light', crop: 'component' },
    crop: '.vocab-tab-selector-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Tab Selector', scenario: 'With counts · due selected', appearance: 'light' },
    note: 'Vocab tab selector · counts 12/5/38, due selected (light)',
  },
  {
    case: 'vocab-tab-selector-zero-counts-light',
    params: { surface: 'vocab-tab-selector', scenario: 'zero-counts', appearance: 'light', crop: 'component' },
    crop: '.vocab-tab-selector-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Tab Selector', scenario: 'Zero counts · reviewed selected', appearance: 'light' },
    note: 'Vocab tab selector · counts 0/0/0, reviewed selected (light)',
  },
  // Vocab Shell · Toolbar Glyph（VocabShellChromeScenarios.swift「Vocab Shell ·
  // Toolbar Glyph」3 態，layout .compressed = intrinsic glyph）。元件 scene 畫布
  // 透明（corner srgba 0,0,0,0）→ transparent:true + crop 到 component-surface。
  // AppToolbarGlyph(.vocab)：HStack(s1)[icon iconToolbar/secondaryText + 可選
  // destructive Capsule badge（monoLabel white，5h/2v）]。皆 light。
  {
    case: 'vocab-toolbar-glyph-plain-light',
    params: { surface: 'vocab-toolbar-glyph', scenario: 'plain', appearance: 'light', crop: 'component' },
    crop: '.vocab-toolbar-glyph-component-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Toolbar Glyph', scenario: 'Plain', appearance: 'light' },
    note: 'Vocab toolbar glyph · plain（無 badge）(light)',
  },
  {
    case: 'vocab-toolbar-glyph-with-badge-light',
    params: { surface: 'vocab-toolbar-glyph', scenario: 'with-badge', appearance: 'light', crop: 'component' },
    crop: '.vocab-toolbar-glyph-component-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Toolbar Glyph', scenario: 'With badge', appearance: 'light' },
    note: 'Vocab toolbar glyph · with badge "5" (light)',
  },
  {
    case: 'vocab-toolbar-glyph-badge-stress-light',
    params: { surface: 'vocab-toolbar-glyph', scenario: 'badge-stress', appearance: 'light', crop: 'component' },
    crop: '.vocab-toolbar-glyph-component-surface',
    transparent: true,
    ref: { surface: 'Vocab Shell · Toolbar Glyph', scenario: 'Badge stress (99+)', appearance: 'light' },
    note: 'Vocab toolbar glyph · badge stress "99+" (light)',
  },
  // Vocab · Empty State（VocabComponentScenarios.swift「Vocab Components · Empty
  // State」4 態）— AppEmptyStateContent/Card .vocab(skin)。scene = 元件
  // .frame(maxWidth:.infinity).padding(24)，catalog canvas 透明（corner srgba 0,0,0,0），
  // 故 crop=component + transparent + omitBackground，crop 目標 = surface 自身。
  {
    case: 'vocab-empty-state-card-no-action-light',
    params: { surface: 'vocab-empty-state', scenario: 'card-no-action', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Vocab Components · Empty State', scenario: 'Card — no action', appearance: 'light' },
    note: 'Vocab empty state · Card 找不到符合的單字（magnifyingglass，無 CTA）(light)',
  },
  {
    case: 'vocab-empty-state-card-with-action-light',
    params: { surface: 'vocab-empty-state', scenario: 'card-with-action', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Vocab Components · Empty State', scenario: 'Card — with action', appearance: 'light' },
    note: 'Vocab empty state · Card 詞庫是空的（tray，outline「開始閱讀」CTA）(light)',
  },
  {
    case: 'vocab-empty-state-content-basic-light',
    params: { surface: 'vocab-empty-state', scenario: 'content-basic', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Vocab Components · Empty State', scenario: 'Content — basic', appearance: 'light' },
    note: 'Vocab empty state · Content 尚無單字（book.closed，無 chrome）(light)',
  },
  {
    case: 'vocab-empty-state-content-guidance-action-light',
    params: { surface: 'vocab-empty-state', scenario: 'content-guidance-action', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Vocab Components · Empty State', scenario: 'Content — guidance + action', appearance: 'light' },
    note: 'Vocab empty state · Content 今天沒有要複習的單字（checkmark.circle，guidance@0.7 + outline「查看全部單字」CTA）(light)',
  },
  // Vocab Scene Shell — Vocabulary 統一四態容器（VocabSceneShell）。catalog scene
  // 為 .fill，vocabCanvasBackground = pageBackground（不透明全幀）→ 全 phone-frame
  // 不透明捕捉（無 transparent/crop）。loading/empty/error/content 垂直置中、
  // loadingSkeleton 頂部對齊 6 骨架列。
  {
    case: 'vocab-scene-shell-loading-spinner-light',
    params: { surface: 'vocab-scene-shell', scenario: 'loading-spinner', appearance: 'light' },
    ref: { surface: 'Vocab Scene Shell', scenario: 'Loading · centered spinner', appearance: 'light' },
    note: 'Vocab scene shell · loading（arrow.clockwise + ProgressView spinner，置中 message card）',
  },
  {
    case: 'vocab-scene-shell-loading-skeleton-light',
    params: { surface: 'vocab-scene-shell', scenario: 'loading-skeleton', appearance: 'light' },
    ref: { surface: 'Vocab Scene Shell', scenario: 'Loading skeleton · 6 rows', appearance: 'light' },
    note: 'Vocab scene shell · loadingSkeleton 6 列（AppSkeletonCard，頂部對齊）',
  },
  {
    case: 'vocab-scene-shell-empty-cta-light',
    params: { surface: 'vocab-scene-shell', scenario: 'empty-cta', appearance: 'light' },
    ref: { surface: 'Vocab Scene Shell', scenario: 'Empty · with CTA', appearance: 'light' },
    note: 'Vocab scene shell · empty（sparkles + outline「前往閱讀」CTA，置中 empty card）',
  },
  {
    case: 'vocab-scene-shell-empty-no-action-light',
    params: { surface: 'vocab-scene-shell', scenario: 'empty-no-action', appearance: 'light' },
    ref: { surface: 'Vocab Scene Shell', scenario: 'Empty · no action', appearance: 'light' },
    note: 'Vocab scene shell · empty（magnifyingglass，無 CTA，置中 empty card）',
  },
  {
    case: 'vocab-scene-shell-error-retry-light',
    params: { surface: 'vocab-scene-shell', scenario: 'error-retry', appearance: 'light' },
    ref: { surface: 'Vocab Scene Shell', scenario: 'Error · retry', appearance: 'light' },
    note: 'Vocab scene shell · error（exclamationmark.triangle + 「重試」按鈕，置中 message card）',
  },
  {
    case: 'vocab-scene-shell-content-light',
    params: { surface: 'vocab-scene-shell', scenario: 'content', appearance: 'light' },
    transparent: true, // content pass-through 不套 canvas → ref 透明（alpha-mean 0.008）
    ref: { surface: 'Vocab Scene Shell', scenario: 'Content · pass-through', appearance: 'light' },
    note: 'Vocab scene shell · content pass-through（範例字卡 serendipity，確認殼不污染 content）',
  },
  // Vocab Highlight Picker — Reader 螢光標記顏色選擇器（VocabHighlightColorPresetPicker）。
  //   catalog .fill 透明 component scene（alpha-mean 0.049）→ 全 phone-frame 透明捕捉。
  //   4 preset selected 態；Dark mode scene deferred（.preferredColorScheme 語意未定）。
  { case: 'vocab-highlight-picker-paper-selected-light', params: { surface: 'vocab-highlight-picker', scenario: 'paper-selected', appearance: 'light' }, transparent: true, ref: { surface: 'Vocab Highlight Picker', scenario: 'Paper selected', appearance: 'light' }, note: 'Vocab highlight picker · 紙色 selected' },
  { case: 'vocab-highlight-picker-blue-selected-light', params: { surface: 'vocab-highlight-picker', scenario: 'blue-selected', appearance: 'light' }, transparent: true, ref: { surface: 'Vocab Highlight Picker', scenario: 'Blue selected', appearance: 'light' }, note: 'Vocab highlight picker · 藍色 selected' },
  { case: 'vocab-highlight-picker-sage-selected-light', params: { surface: 'vocab-highlight-picker', scenario: 'sage-selected', appearance: 'light' }, transparent: true, ref: { surface: 'Vocab Highlight Picker', scenario: 'Sage selected', appearance: 'light' }, note: 'Vocab highlight picker · 鼠尾草 selected' },
  { case: 'vocab-highlight-picker-rose-selected-light', params: { surface: 'vocab-highlight-picker', scenario: 'rose-selected', appearance: 'light' }, transparent: true, ref: { surface: 'Vocab Highlight Picker', scenario: 'Rose selected', appearance: 'light' }, note: 'Vocab highlight picker · 玫瑰 selected' },
  // --- Composite layer batch-2 — 8 cases (wf-composite-batch): collocation-explain
  //     (.fill transparent full-frame) + kg-empty-state (.fill opaque page-bg full-frame).
  //     banner-review deferred (task #8: opaque-card-on-transparent edge-scale sensitivity).
  {
    case: 'collocation-explain-loaded-short-light',
    params: { surface: 'collocation-explain', scenario: 'loaded-short', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Collocation Explain', scenario: 'Loaded · short', appearance: 'light' },
    note: 'Collocation explain · loaded 短解釋（mono 標題 take into account + 單行片語動詞解釋 + trash/xmark footer）(light)',
  },
  {
    case: 'collocation-explain-loaded-long-light',
    params: { surface: 'collocation-explain', scenario: 'loaded-long', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Collocation Explain', scenario: 'Loaded · long', appearance: 'light' },
    note: 'Collocation explain · loaded 長解釋（come to terms with，多行 wrap 解釋 + trash/xmark footer）(light)',
  },
  {
    case: 'collocation-explain-loaded-with-delete-light',
    params: { surface: 'collocation-explain', scenario: 'loaded-with-delete', appearance: 'light' },
    transparent: true,
    ref: { surface: 'Collocation Explain', scenario: 'Loaded · with delete', appearance: 'light' },
    note: 'Collocation explain · loaded（on the verge of，existingExplanation!=nil → trash 鈕現身 + xmark）(light)',
  },
  {
    case: 'kg-empty-state-multi-filter-light',
    params: { surface: 'kg-empty-state', scenario: 'multi-filter', appearance: 'light' },
    ref: { surface: 'KG Empty State', scenario: 'Multi filter', appearance: 'light' },
    note: 'KG 空狀態 — 多選篩選（通用篩選圖示 line.3.horizontal.decrease.circle）',
  },

  // --- LinkReasonSheet — 5 cases: card-link 解釋 sheet（.fill opaque page-bg full-frame）。
  //     paperclip header + mono word + divider + reason body + 2× ghost button footer。
  {
    case: 'link-reason-sheet-medium-reason-light',
    params: { surface: 'link-reason-sheet', scenario: 'medium-reason', appearance: 'light' },
    ref: { surface: 'Link Reason Sheet', scenario: 'Loaded · medium reason', appearance: 'light' },
    note: 'Link reason · 一般長度（forestall / 相似用法 / 三行 reason + 查看詳情 + 隱藏此連結）(light)',
  },
  {
    case: 'link-reason-sheet-short-reason-light',
    params: { surface: 'link-reason-sheet', scenario: 'short-reason', appearance: 'light' },
    ref: { surface: 'Link Reason Sheet', scenario: 'Short reason', appearance: 'light' },
    note: 'Link reason · 極短（deft / 同義詞 / 單行 reason）(light)',
  },
  {
    case: 'link-reason-sheet-long-reason-light',
    params: { surface: 'link-reason-sheet', scenario: 'long-reason', appearance: 'light' },
    ref: { surface: 'Link Reason Sheet', scenario: 'Long reason (stress)', appearance: 'light' },
    note: 'Link reason · 超長 stress（schadenfreude / 相關概念 / 多行 wrap reason）(light)',
  },
  {
    case: 'link-reason-sheet-no-hide-light',
    params: { surface: 'link-reason-sheet', scenario: 'no-hide', appearance: 'light' },
    ref: { surface: 'Link Reason Sheet', scenario: 'No hide action', appearance: 'light' },
    note: 'Link reason · onHide=nil → 僅查看詳情、無隱藏鈕（forestall）(light)',
  },
  {
    case: 'link-reason-sheet-empty-reason-light',
    params: { surface: 'link-reason-sheet', scenario: 'empty-reason', appearance: 'light' },
    ref: { surface: 'Link Reason Sheet', scenario: 'Empty reason', appearance: 'light' },
    note: 'Link reason · 空 reason 邊界（laconic / divider 緊鄰標題 / footer 不變）(light)',
  },

  // --- NotebookEditSheet — 5 cases: 新建/編輯單字本 grouped Form（.fill opaque #F2F2F7）。
  //     cover preview + name field + 12 色圈 + 6 pattern tile（橫向 scroll，噪點被裁）+ 自訂圖片。
  {
    case: 'notebook-edit-create-blank-light',
    params: { surface: 'notebook-edit', scenario: 'create-blank', appearance: 'light' },
    ref: { surface: 'Notebook Edit', scenario: 'Create · blank', appearance: 'light' },
    note: 'Notebook edit · 新建空白（預覽 cover #AFC2D3 default / 空 name / 無色無 pattern）(light)',
  },
  {
    case: 'notebook-edit-color-pattern-light',
    params: { surface: 'notebook-edit', scenario: 'color-pattern', appearance: 'light' },
    ref: { surface: 'Notebook Edit', scenario: 'Edit · color + pattern', appearance: 'light' },
    note: 'Notebook edit · 海洋色 + 圓點 pattern（GRE 高頻字 / 色圈+tile 雙選定白勾）(light)',
  },
  {
    case: 'notebook-edit-color-only-light',
    params: { surface: 'notebook-edit', scenario: 'color-only', appearance: 'light' },
    ref: { surface: 'Notebook Edit', scenario: 'Edit · color only', appearance: 'light' },
    note: 'Notebook edit · 珊瑚色無 pattern（雅思核心詞彙 / 無 tile selected）(light)',
  },
  {
    case: 'notebook-edit-long-name-light',
    params: { surface: 'notebook-edit', scenario: 'long-name', appearance: 'light' },
    ref: { surface: 'Notebook Edit', scenario: 'Edit · long name', appearance: 'light' },
    note: 'Notebook edit · 長名稱壓力（紫藤色 / cover lineLimit 2 截斷）(light)',
  },
  {
    case: 'notebook-edit-empty-name-light',
    params: { surface: 'notebook-edit', scenario: 'empty-name', appearance: 'light' },
    ref: { surface: 'Notebook Edit', scenario: 'Edit · empty name (save disabled)', appearance: 'light' },
    note: 'Notebook edit · 空名稱（森林色 / field placeholder / cover 顯預覽）(light)',
  },

  // ── word-edit ──
  { case: 'word-edit-populated-light', params: { surface: 'word-edit', scenario: 'populated', appearance: 'light' }, ref: { surface: 'Word Edit', scenario: 'Populated', appearance: 'light' }, note: '已填翻譯+教學筆記的詞條編輯（兩張白卡） (light)' },
    { case: 'word-edit-empty-explanation-light', params: { surface: 'word-edit', scenario: 'empty-explanation', appearance: 'light' }, ref: { surface: 'Word Edit', scenario: 'Empty explanation', appearance: 'light' }, note: '教學筆記為空（第二張卡空白、minHeight 80 保留） (light)' },
    { case: 'word-edit-long-content-stress-light', params: { surface: 'word-edit', scenario: 'long-content-stress', appearance: 'light' }, ref: { surface: 'Word Edit', scenario: 'Long content stress', appearance: 'light' }, note: '長翻譯+6 段重複教學筆記（第二張卡撐高） (light)' },
    { case: 'word-edit-long-word-title-light', params: { surface: 'word-edit', scenario: 'long-word-title', appearance: 'light' }, ref: { surface: 'Word Edit', scenario: 'Long word title', appearance: 'light' }, note: '超長單字 navigationTitle（near-white serif、截斷） (light)' },
  // ── vocab-calendar ──
  {
    case: 'vocab-calendar-active-month-light',
    params: { surface: 'vocab-calendar', scenario: 'active-month', appearance: 'light', crop: 'component' },
    crop: '.vocab-calendar-surface',
    transparent: true,
    ref: { surface: 'Vocab Calendar', scenario: 'Active month', appearance: 'light' },
    note: '2024-03 gradient 全 intensity 色階（cellFill 0.12/0.16/0.20/0.26 + dot 0.5/0.75/1.0）；Monday-first 7欄 grid，.fillH 全寬透明畫布 (light)',
  },
  {
    case: 'vocab-calendar-day-selected-light',
    params: { surface: 'vocab-calendar', scenario: 'day-selected', appearance: 'light', crop: 'component' },
    crop: '.vocab-calendar-surface',
    transparent: true,
    ref: { surface: 'Vocab Calendar', scenario: 'Day selected', appearance: 'light' },
    note: '2024-03 gradient + 選中 day15（mutedFill 底 + primaryText 數字）；其餘同 active-month (light)',
  },
  {
    case: 'vocab-calendar-heavy-intensity-light',
    params: { surface: 'vocab-calendar', scenario: 'heavy-intensity', appearance: 'light', crop: 'component' },
    crop: '.vocab-calendar-surface',
    transparent: true,
    ref: { surface: 'Vocab Calendar', scenario: 'Heavy intensity', appearance: 'light' },
    note: '2024-03 全 count=20 → 最深 cellFill 0.26 + 滿 dot（chart-highlight 1.0）逼出色階上限 (light)',
  },
  {
    case: 'vocab-calendar-no-activity-light',
    params: { surface: 'vocab-calendar', scenario: 'no-activity', appearance: 'light', crop: 'component' },
    crop: '.vocab-calendar-surface',
    transparent: true,
    ref: { surface: 'Vocab Calendar', scenario: 'No activity', appearance: 'light' },
    note: '2024-03 空 map（empty state）：僅 secondaryText 數字 + cardBorder 0.5 格線，無 fill/dot (light)',
  },
  {
    case: 'vocab-calendar-current-month-light',
    params: { surface: 'vocab-calendar', scenario: 'current-month', appearance: 'light', crop: 'component' },
    crop: '.vocab-calendar-surface',
    transparent: true,
    ref: { surface: 'Vocab Calendar', scenario: 'Current month with today', appearance: 'light' },
    note: '2026-06（catalog 擷取月）gradient + today=11 chartHighlight 數字色；月份較窄、ref 高度小於其他 scene (light)',
  },
  // ── vocab-forecast ──
  {
    case: 'vocab-forecast-7-day-light',
    params: { surface: 'vocab-forecast', scenario: '7-day', appearance: 'light', crop: 'component' },
    transparent: true,
    crop: '.vocab-forecast-surface',
    ref: { surface: 'Vocab Forecast', scenario: '7-day forecast', appearance: 'light' },
    note: 'Vocab forecast 長條圖 · 7 天 counts [12,5,8,3,6,9,4]，index0 高亮、count label (light)',
  },
  {
    case: 'vocab-forecast-14-day-light',
    params: { surface: 'vocab-forecast', scenario: '14-day', appearance: 'light', crop: 'component' },
    transparent: true,
    crop: '.vocab-forecast-surface',
    ref: { surface: 'Vocab Forecast', scenario: '14-day forecast', appearance: 'light' },
    note: 'Vocab forecast 長條圖 · 14 天，index6 顯示「1週」label (light)',
  },
  {
    case: 'vocab-forecast-compact-light',
    params: { surface: 'vocab-forecast', scenario: 'compact', appearance: 'light', crop: 'component' },
    transparent: true,
    crop: '.vocab-forecast-surface',
    ref: { surface: 'Vocab Forecast', scenario: 'Compact (30 days)', appearance: 'light' },
    note: 'Vocab forecast 長條圖 · 30 天 isCompact，無 count label、date label 窄欄截斷 (light)',
  },
  {
    case: 'vocab-forecast-sparse-light',
    params: { surface: 'vocab-forecast', scenario: 'sparse', appearance: 'light', crop: 'component' },
    transparent: true,
    crop: '.vocab-forecast-surface',
    ref: { surface: 'Vocab Forecast', scenario: 'Sparse — single spike', appearance: 'light' },
    note: 'Vocab forecast 長條圖 · 單峰 [18,0,...]，僅 index0 有 bar/count (light)',
  },
  // ── vocab-heatmap ──
  { case: 'vocab-heatmap-dense-graded-light', params: { surface: 'vocab-heatmap', scenario: 'dense-graded', appearance: 'light', crop: 'component' }, transparent: true, crop: '.vocab-heatmap-surface', ref: { surface: 'Vocab Heatmap', scenario: 'Dense · graded', appearance: 'light' }, note: '密集 graded 20 週活動熱圖 — 四級著色全覆蓋 (light)' },
{ case: 'vocab-heatmap-sparse-light', params: { surface: 'vocab-heatmap', scenario: 'sparse', appearance: 'light', crop: 'component' }, transparent: true, crop: '.vocab-heatmap-surface', ref: { surface: 'Vocab Heatmap', scenario: 'Sparse', appearance: 'light' }, note: '稀疏低活躍熱圖 — 每 11 天一個 level 1 點 (light)' },
{ case: 'vocab-heatmap-no-thresholds-light', params: { surface: 'vocab-heatmap', scenario: 'no-thresholds', appearance: 'light', crop: 'component' }, transparent: true, crop: '.vocab-heatmap-surface', ref: { surface: 'Vocab Heatmap', scenario: 'No thresholds (flat level)', appearance: 'light' }, note: '無 thresholds — 所有非零日扁平 level 1 (light)' },
{ case: 'vocab-heatmap-empty-light', params: { surface: 'vocab-heatmap', scenario: 'empty', appearance: 'light', crop: 'component' }, transparent: true, crop: '.vocab-heatmap-surface', ref: { surface: 'Vocab Heatmap', scenario: 'Empty', appearance: 'light' }, note: '空活動 — 全格透明僅留 grid 結構與圖例 (light)' },
{ case: 'vocab-heatmap-short-range-light', params: { surface: 'vocab-heatmap', scenario: 'short-range', appearance: 'light', crop: 'component' }, transparent: true, crop: '.vocab-heatmap-surface', ref: { surface: 'Vocab Heatmap', scenario: 'Short range (8 weeks)', appearance: 'light' }, note: '8 週短區間 graded 熱圖 (light)' },
  // ── review-banner ──
{ case: 'review-banner-demo-default-light', params: { surface: 'review-banner', scenario: 'demo-default', appearance: 'light' }, ref: { surface: 'Banners · Demo', scenario: 'Default', appearance: 'light' }, note: 'DemoBanner 全幀 strip：Demo 模式 + 結束 (light)' },
  // ── vocab-add-link ──
  { case: 'vocab-add-link-with-candidates-light', params: { surface: 'vocab-add-link', scenario: 'with-candidates', appearance: 'light' }, ref: { surface: 'Vocabulary · Add Link', scenario: 'With candidates', appearance: 'light' }, note: 'Add Link sheet 候選態：初始 searchText 為空，固定渲染空查詢空態（與 No candidates byte-identical）(light)' },
{ case: 'vocab-add-link-no-candidates-light', params: { surface: 'vocab-add-link', scenario: 'no-candidates', appearance: 'light' }, ref: { surface: 'Vocabulary · Add Link', scenario: 'No candidates', appearance: 'light' }, note: 'Add Link sheet 無候選態：空查詢空態，視覺等同 With candidates (light)' },
  // ── vocab-linked-card ──
  { case: 'vocab-linked-card-single-card-light', params: { surface: 'vocab-linked-card', scenario: 'single-card', appearance: 'light' }, transparent: true, ref: { surface: 'Vocabulary · Linked Card', scenario: 'Single card', appearance: 'light' }, note: '單張連結卡 overlay（載入態 placeholder），scrim black 0.20 over 透明畫布 (light)' },
{ case: 'vocab-linked-card-stacked-3-deep-light', params: { surface: 'vocab-linked-card', scenario: 'stacked-3-deep', appearance: 'light' }, transparent: true, ref: { surface: 'Vocabulary · Linked Card', scenario: 'Stacked 3-deep', appearance: 'light' }, note: '三層疊卡 overlay（前卡 Nested Link +2），各層 offset/scale 遞增 (light)' },

  {
    case: 'kg-empty-state-no-entries-logged-out-light',
    params: { surface: 'kg-empty-state', scenario: 'no-entries-logged-out', appearance: 'light' },
    ref: { surface: 'KG Empty State', scenario: 'No entries (logged out)', appearance: 'light' },
    note: 'KG 空狀態 — 整本無卡、未登入（無 CTA）',
  },
  {
    case: 'kg-empty-state-no-entries-cta-light',
    params: { surface: 'kg-empty-state', scenario: 'no-entries-cta', appearance: 'light' },
    ref: { surface: 'KG Empty State', scenario: 'No entries (with CTA)', appearance: 'light' },
    note: 'KG 空狀態 — 整本無卡、含「重新整理」outline CTA',
  },
  {
    case: 'kg-empty-state-search-no-match-light',
    params: { surface: 'kg-empty-state', scenario: 'search-no-match', appearance: 'light' },
    ref: { surface: 'KG Empty State', scenario: 'Search no match', appearance: 'light' },
    note: 'KG 空狀態 — 搜尋無結果（magnifyingglass）',
  },
  {
    case: 'kg-empty-state-single-filter-due-light',
    params: { surface: 'kg-empty-state', scenario: 'single-filter-due', appearance: 'light' },
    ref: { surface: 'KG Empty State', scenario: 'Single filter (due)', appearance: 'light' },
    note: 'KG 空狀態 — 單一篩選（due）→ checkmark.seal',
  },
  // ── Composite layer batch-3 ──
  // Sync (.fill opaque page-bg full-frame, NO crop, bookshelf pattern)
  { case: 'sync-completed-light', params: { surface: 'sync', scenario: 'completed', appearance: 'light' }, ref: { surface: 'Sync', scenario: 'Completed', appearance: 'light' }, note: 'completed — green checkmark hero「同步完成」, 5 done steps, content-width「完成」pill' },
  { case: 'sync-full-light', params: { surface: 'sync', scenario: 'full', appearance: 'light' }, ref: { surface: 'Sync', scenario: 'Failed · full error', appearance: 'light' }, note: 'failed/full — red triangle hero「同步失敗」, summary（accent icon）, full-width「重試」' },
  { case: 'sync-partial-light', params: { surface: 'sync', scenario: 'partial', appearance: 'light' }, ref: { surface: 'Sync', scenario: 'Failed · partial', appearance: 'light' }, note: 'failed/partial — amber hero「部分同步完成」, 4 done + 1 error, full-width「重試失敗項目」' },
  { case: 'sync-ready-light', params: { surface: 'sync', scenario: 'ready', appearance: 'light' }, ref: { surface: 'Sync', scenario: 'Ready · pending rows', appearance: 'light' }, note: 'ready — blue hero「3 個待處理動作」+ tone chips, pending list（3 WordRows）, full-width「開始同步」' },
  { case: 'sync-running-light', params: { surface: 'sync', scenario: 'running', appearance: 'light' }, ref: { surface: 'Sync', scenario: 'Running · steps in flight', appearance: 'light' }, note: 'running — blue hero「同步中…」+ spinner, 1 done / 1 running（1/2）/ 3 waiting, full-width「取消」' },
  // Notebooks·Card (opaque component crop, editorial book-row)
  { case: 'notebooks-card-grid-two-light', params: { surface: 'notebooks-card', scenario: 'grid-two', appearance: 'light', crop: 'component' }, crop: '.notebooks-card', ref: { surface: 'Notebooks · Card', scenario: 'Grid · two notebooks', appearance: 'light' }, note: 'Notebooks Card — 2-col LazyVGrid, heavy(active,blue) + light(GRE,green)' },
  { case: 'notebooks-card-hero-fresh-light', params: { surface: 'notebooks-card', scenario: 'hero-fresh', appearance: 'light', crop: 'component' }, crop: '.notebooks-card', ref: { surface: 'Notebooks · Card', scenario: 'Hero · fresh notebook (no progress)', appearance: 'light' }, note: 'Notebooks Card — hero single, empty notebook（0 詞 placeholder, no progress）' },
  { case: 'notebooks-card-hero-long-name-light', params: { surface: 'notebooks-card', scenario: 'hero-long-name', appearance: 'light', crop: 'component' }, crop: '.notebooks-card', ref: { surface: 'Notebooks · Card', scenario: 'Hero · long name truncate', appearance: 'light' }, note: 'Notebooks Card — hero single, long CJK name 2-line tail truncate, 1,801 grouped' },
  { case: 'notebooks-card-hero-heavy-light', params: { surface: 'notebooks-card', scenario: 'hero-heavy', appearance: 'light', crop: 'component' }, crop: '.notebooks-card', ref: { surface: 'Notebooks · Card', scenario: 'Hero · single notebook (heavy usage)', appearance: 'light' }, note: 'Notebooks Card — hero single, 我的單字本 active, 626 詞 + 538 actionable + progress' },
  // KG Vocab Row (WordRow molecule, transparent component crop, varying width)
  { case: 'kg-vocab-row-default-light', params: { surface: 'kg-vocab-row', scenario: 'default', appearance: 'light', crop: 'component' }, crop: '.kg-vocab-row-surface', transparent: true, ref: { surface: 'KG Vocab Row', scenario: 'Default', appearance: 'light' }, note: 'WordRow 非 selecting：mono18 word + caption pos + sans15 translation；trailing 進度 detailLabel「首輪 12h」' },
  { case: 'kg-vocab-row-highlighted-light', params: { surface: 'kg-vocab-row', scenario: 'highlighted', appearance: 'light', crop: 'component' }, crop: '.kg-vocab-row-surface', transparent: true, ref: { surface: 'KG Vocab Row', scenario: 'Highlighted', appearance: 'light' }, note: 'isHighlighted → RoundedRectangle(sm=6).fill(accent.opacity(0.08)) 包住 inset row' },

  // ── Composite layer batch-4 ──
  // Book Card（R: bookshelf cell atom）— BookCardScenarios.swift 6 態，皆 light、
  // layout .compressed = 元件級 crop。catalog component scene 透明畫布
  // （corner srgba 0,0,0,0）→ transparent crop，同 vocab-sort-pill。
  // crop 目標 = .book-card-component-surface（card width 180 + scene .padding(24)）。
  // 註：A11y3.png 與 Progress·Mid.png byte-identical（component scene 內 a11y3
  // 字級未顯著放大）→ a11y3 fixture 沿用 midProgress 內容。
  {
    case: 'book-card-placeholder-epub-light',
    params: { surface: 'book-card', scenario: 'placeholder-epub', appearance: 'light', crop: 'component' },
    crop: '.book-card-component-surface',
    transparent: true,
    ref: { surface: 'Book Card', scenario: 'Placeholder · EPUB', appearance: 'light' },
    note: 'Book card · placeholder EPUB（0% track-only、無格式 pill）(light)',
  },
  {
    case: 'book-card-pdf-badge-light',
    params: { surface: 'book-card', scenario: 'pdf-badge', appearance: 'light', crop: 'component' },
    crop: '.book-card-component-surface',
    transparent: true,
    ref: { surface: 'Book Card', scenario: 'Placeholder · PDF badge', appearance: 'light' },
    note: 'Book card · placeholder PDF（封面格式 pill PDF、0% track-only）(light)',
  },
  {
    case: 'book-card-progress-mid-light',
    params: { surface: 'book-card', scenario: 'progress-mid', appearance: 'light', crop: 'component' },
    crop: '.book-card-component-surface',
    transparent: true,
    ref: { surface: 'Book Card', scenario: 'Progress · Mid', appearance: 'light' },
    note: 'Book card · 42% accent fill + 相對日期 (light)',
  },
  {
    case: 'book-card-progress-complete-light',
    params: { surface: 'book-card', scenario: 'progress-complete', appearance: 'light', crop: 'component' },
    crop: '.book-card-component-surface',
    transparent: true,
    ref: { surface: 'Book Card', scenario: 'Progress · Complete', appearance: 'light' },
    note: 'Book card · 100% full accent fill (light)',
  },
  {
    case: 'book-card-long-title-light',
    params: { surface: 'book-card', scenario: 'long-title', appearance: 'light', crop: 'component' },
    crop: '.book-card-component-surface',
    transparent: true,
    ref: { surface: 'Book Card', scenario: 'Long title + author', appearance: 'light' },
    note: 'Book card · 兩行標題 clamp + 作者 ellipsis + TXT pill + 8% (light)',
  },
  {
    case: 'book-card-a11y3-light',
    params: { surface: 'book-card', scenario: 'a11y3', appearance: 'light', crop: 'component' },
    crop: '.book-card-component-surface',
    transparent: true,
    ref: { surface: 'Book Card', scenario: 'A11y3', appearance: 'light' },
    note: 'Book card · A11y3（catalog 與 Progress·Mid byte-identical）(light)',
  },
  // Subscription Views · Gate Card — ProAccessGateCard（SubscriptionViews.swift）。
  // layout .fillH → opaque component crop（corner = page-bg srgba(247,246,243,1)，
  // 無 transparent）；crop 目標 = surface .padding(16) intrinsic box（撐滿 frame 寬）。
  {
    case: 'subscription-gate-card-happy-path-light',
    params: { surface: 'subscription-gate-card', scenario: 'happy-path', appearance: 'light', crop: 'component' },
    crop: '.subscription-gate-card-surface',
    ref: { surface: 'Subscription Views · Gate Card', scenario: 'Happy path', appearance: 'light' },
    note: 'Gate card happy path — sparkles + 升級 Pro (light)',
  },
  {
    case: 'subscription-gate-card-long-copy-stress-light',
    params: { surface: 'subscription-gate-card', scenario: 'long-copy-stress', appearance: 'light', crop: 'component' },
    crop: '.subscription-gate-card-surface',
    ref: { surface: 'Subscription Views · Gate Card', scenario: 'Long copy stress', appearance: 'light' },
    note: 'Gate card long copy — graduationcap.fill + multiline (light)',
  },
  {
    case: 'subscription-gate-card-narrow-width-320pt-light',
    params: { surface: 'subscription-gate-card', scenario: 'narrow-width-320pt', appearance: 'light', crop: 'component' },
    crop: '.subscription-gate-card-surface',
    ref: { surface: 'Subscription Views · Gate Card', scenario: 'Narrow width 320pt', appearance: 'light' },
    note: 'Gate card narrow 320pt — clock.badge.checkmark, card max-width 320 (light)',
  },
  {
    case: 'subscription-gate-card-dynamic-type-accessibility3-light',
    params: { surface: 'subscription-gate-card', scenario: 'dynamic-type-accessibility3', appearance: 'light', crop: 'component' },
    crop: '.subscription-gate-card-surface',
    ref: { surface: 'Subscription Views · Gate Card', scenario: 'Dynamic Type · accessibility3', appearance: 'light' },
    note: 'Gate card a11y3 — headphones; AppFonts 固定字級不隨 Dynamic Type 縮放 (light)',
  },
  // ── account-section ── transparent .fill full-frame；surface 頂部 inset 75 CSS px（=225
  //    capture px，header glyph 對齊 ref；單位混淆修正：勿用 capture px 當 CSS px）。
  { case: 'account-section-logged-out-light', params: { surface: 'account-section', scenario: 'logged-out', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Section', scenario: 'Logged Out', appearance: 'light' }, note: 'Account section · 未登入（登入卡 hero）' },
  { case: 'account-section-logged-out-auth-error-light', params: { surface: 'account-section', scenario: 'logged-out-auth-error', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Section', scenario: 'Logged Out · Auth Error', appearance: 'light' }, note: 'Account section · 未登入 + auth error' },
  { case: 'account-section-subscribed-active-light', params: { surface: 'account-section', scenario: 'subscribed-active', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Section', scenario: 'Subscribed · Pro Active', appearance: 'light' }, note: 'Account section · Pro 訂閱中' },
  { case: 'account-section-subscription-loading-light', params: { surface: 'account-section', scenario: 'subscription-loading', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Section', scenario: 'Subscription Loading', appearance: 'light' }, note: 'Account section · 訂閱載入中' },
  { case: 'account-section-pricing-unavailable-light', params: { surface: 'account-section', scenario: 'pricing-unavailable', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Section', scenario: 'Pricing Unavailable · Upgrade CTA', appearance: 'light' }, note: 'Account section · 價格不可用 + 升級 CTA' },
  // ── Composite layer batch-5 ── Review Fold trio（.fill transparent full-frame，
  //    sampleCard/segment over transparent，shots transparent:true，無 component crop）
  { case: 'review-fold-chevron-collapse-handle-light', params: { surface: 'review-fold-chevron', scenario: 'collapse-handle', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Chevron Pill', scenario: 'Collapse handle', appearance: 'light' }, note: 'ReviewFoldChevronPill 裸 capsule（chevron.compact.down，muted-fill + hairline border），置中 padding 40' },
  { case: 'review-fold-chevron-on-card-backdrop-light', params: { surface: 'review-fold-chevron', scenario: 'on-card-backdrop', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Chevron Pill', scenario: 'On card backdrop', appearance: 'light' }, note: 'sampleCard（title3 + subhead + footnote）+ bottom-overlay chevron pill（offset y 10）' },
  { case: 'review-fold-paper-expanded-light', params: { surface: 'review-fold-paper', scenario: 'expanded', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Paper Fold', scenario: 'Expanded (1.0)', appearance: 'light' }, note: 'PaperFoldModifier progress 1.0 — sampleCard 全展開' },
  // NOTE: paper three-quarter (0.75) + half (0.5) deferred — iOS .fill scene 對置中卡片
  //   套 scaleEffect(anchor:.top)+rotation3DEffect(anchor:.top)，SwiftUI 的「layout 不變、
  //   render-transform」在中段使視覺卡片上移至幀頂；web 以 flex center 置中 → 中段垂直錯位
  //   （0.75 RMSE 0.39 / 0.5 RMSE 0.30 > ceiling，兩極端 1.0/0.25/0.05 對齊故過）。與
  //   account-section 同類 .fill 對齊根因，待 top-anchor layout 模型重導。fixtures 仍保留 5 態。
  { case: 'review-fold-paper-quarter-light', params: { surface: 'review-fold-paper', scenario: 'quarter', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Paper Fold', scenario: 'Quarter (0.25)', appearance: 'light' }, note: 'PaperFoldModifier progress 0.25 — sampleCard 摺至 25% 高' },
  { case: 'review-fold-paper-nearly-folded-light', params: { surface: 'review-fold-paper', scenario: 'nearly-folded', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Paper Fold', scenario: 'Nearly folded (0.05)', appearance: 'light' }, note: 'PaperFoldModifier progress 0.05 — sampleCard 近全摺' },
  { case: 'review-fold-segment-single-light', params: { surface: 'review-fold-segment', scenario: 'single', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Segment', scenario: 'Single', appearance: 'light' }, note: 'ReviewFoldSurface position single — 單段（四角 radii），padding 40' },
  { case: 'review-fold-segment-stacked-group-light', params: { surface: 'review-fold-segment', scenario: 'stacked-group', appearance: 'light' }, transparent: true, ref: { surface: 'Review Fold · Segment', scenario: 'Stacked group', appearance: 'light' }, note: 'ReviewFoldSurface top/middle/bottom 三段堆疊（join radii），padding 24' },
  // ── Composite layer batch-6 ── Podcast Continue Card（component crop .pcc-surface）+
  //    Episode Row（full-frame transparent）+ Series Card（component crop）
  { case: 'podcast-continue-card-in-progress-light', params: { surface: 'podcast-continue-card', scenario: 'in-progress', appearance: 'light', crop: 'component' }, crop: '.pcc-surface', transparent: true, ref: { surface: 'Podcast Continue Card', scenario: 'In Progress (Resume)', appearance: 'light' }, note: 'Podcast continue card · in-progress resume（disc + progress + 剩餘時間）' },
  { case: 'podcast-continue-card-fresh-light', params: { surface: 'podcast-continue-card', scenario: 'fresh', appearance: 'light', crop: 'component' }, crop: '.pcc-surface', transparent: true, ref: { surface: 'Podcast Continue Card', scenario: 'Fresh (Play)', appearance: 'light' }, note: 'Podcast continue card · fresh play（無進度，play action）' },
  { case: 'podcast-continue-card-completed-light', params: { surface: 'podcast-continue-card', scenario: 'completed', appearance: 'light', crop: 'component' }, crop: '.pcc-surface', transparent: true, ref: { surface: 'Podcast Continue Card', scenario: 'Completed (Replay)', appearance: 'light' }, note: 'Podcast continue card · completed replay（100% + replay）' },
  { case: 'podcast-continue-card-free-preview-light', params: { surface: 'podcast-continue-card', scenario: 'free-preview', appearance: 'light', crop: 'component' }, crop: '.pcc-surface', transparent: true, ref: { surface: 'Podcast Continue Card', scenario: 'Free Preview', appearance: 'light' }, note: 'Podcast continue card · free preview' },
  { case: 'podcast-continue-card-gated-light', params: { surface: 'podcast-continue-card', scenario: 'gated', appearance: 'light', crop: 'component' }, crop: '.pcc-surface', transparent: true, ref: { surface: 'Podcast Continue Card', scenario: 'Gated (Sign In / Upgrade / Unavailable)', appearance: 'light' }, note: 'Podcast continue card · gated（登入/升級/不可用堆疊）' },
  { case: 'podcast-episode-row-variants-light', params: { surface: 'podcast-episode-row', scenario: 'variants', appearance: 'light' }, transparent: true, ref: { surface: 'Podcast · Episode Row', scenario: 'Variants', appearance: 'light' }, note: 'Podcast episode row · variants（多列 episode：番號/日期/時長/字幕+音檔狀態）' },
  { case: 'podcast-series-card-normal-light', params: { surface: 'podcast-series-card', scenario: 'normal', appearance: 'light', crop: 'component' }, crop: '.podcast-series-card-surface', transparent: true, ref: { surface: 'Podcast Series Card', scenario: 'Normal', appearance: 'light' }, note: 'Podcast series card · normal（封面 + 標題 + host + 集數）' },
  { case: 'podcast-series-card-long-host-light', params: { surface: 'podcast-series-card', scenario: 'long-host', appearance: 'light', crop: 'component' }, crop: '.podcast-series-card-surface', transparent: true, ref: { surface: 'Podcast Series Card', scenario: 'Long host', appearance: 'light' }, note: 'Podcast series card · long host（多 host 截斷）' },
  // NOTE: series-card narrow (120px) deferred — 封面波紋 SVG 頻率與 iOS NotebookCoverPattern.waves
  //   在窄寬下放大失配（RMSE 0.251 > ceiling 0.25，僅超 0.4%；normal/long-host/a11y3 皆 <0.09）。
  //   徽章 material 已收斂（0.35→0.18），殘餘為波長比例，待 wave wavelength 隨寬縮放重導。fixtures 保留 narrow 態。
  { case: 'podcast-series-card-a11y3-light', params: { surface: 'podcast-series-card', scenario: 'a11y3', appearance: 'light', crop: 'component' }, crop: '.podcast-series-card-surface', transparent: true, ref: { surface: 'Podcast Series Card', scenario: 'A11y3', appearance: 'light' }, note: 'Podcast series card · a11y3（固定字級不縮放）' },
  // ── Composite layer batch-7 ── Notebook Cover（component crop .nbc-component-surface）+
  //    Notebooks Stack（full-frame：single 透明 / grid 不透明）+ Word Detail Card（component crop 不透明 page-bg）
  { case: 'notebook-cover-all-patterns-blue-light', params: { surface: 'notebook-cover', scenario: 'all-patterns-blue', appearance: 'light', crop: 'component' }, crop: '.nbc-component-surface', transparent: true, ref: { surface: 'Notebook Cover', scenario: 'All patterns · blue', appearance: 'light' }, note: 'Notebook cover · 全 pattern 藍底（dots 白點）' },
  // NOTE: notebook-cover color-swatches deferred — 多色樣本 scene 渲染多張不同色封面網格，
  //   web 色序/排列與 iOS NotebookPalette swatch 列舉失配（RMSE 0.411）；其餘 5 態 <0.21 皆過。
  //   待 swatch 色序對齊重導。fixtures 保留該態。
  { case: 'notebook-cover-solid-no-pattern-light', params: { surface: 'notebook-cover', scenario: 'solid-no-pattern', appearance: 'light', crop: 'component' }, crop: '.nbc-component-surface', transparent: true, ref: { surface: 'Notebook Cover', scenario: 'Solid color · no pattern', appearance: 'light' }, note: 'Notebook cover · 純色無 pattern' },
  { case: 'notebook-cover-long-name-truncate-light', params: { surface: 'notebook-cover', scenario: 'long-name-truncate', appearance: 'light', crop: 'component' }, crop: '.nbc-component-surface', transparent: true, ref: { surface: 'Notebook Cover', scenario: 'Long name truncate', appearance: 'light' }, note: 'Notebook cover · 長名截斷' },
  { case: 'notebook-cover-shows-name-false-light', params: { surface: 'notebook-cover', scenario: 'shows-name-false', appearance: 'light', crop: 'component' }, crop: '.nbc-component-surface', transparent: true, ref: { surface: 'Notebook Cover', scenario: 'showsName = false (overlay use)', appearance: 'light' }, note: 'Notebook cover · showsName=false（overlay 用）' },
  { case: 'notebook-cover-image-fallback-light', params: { surface: 'notebook-cover', scenario: 'image-fallback', appearance: 'light', crop: 'component' }, crop: '.nbc-component-surface', transparent: true, ref: { surface: 'Notebook Cover', scenario: 'Image path fallback (missing → pattern)', appearance: 'light' }, note: 'Notebook cover · 圖路徑 fallback（缺→pattern）' },
  { case: 'notebooks-stack-state-active-light', params: { surface: 'notebooks-stack', scenario: 'state-active', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'State · active light', appearance: 'light' }, note: 'Notebooks stack · single active（我的單字本，dots，100 詞）' },
  { case: 'notebooks-stack-state-inactive-light', params: { surface: 'notebooks-stack', scenario: 'state-inactive', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'State · inactive light', appearance: 'light' }, note: 'Notebooks stack · single inactive（TOEIC）' },
  // NOTE: dark 變體 deferred — catalog 的「State · … dark」scene 內容其實是淺色（snapshot
  //   系統未 honor scene 的 .preferredColorScheme(.dark)，兩個 device dir 皆渲染淺色），與
  //   web data-theme=dark 真暗底失配（RMSE 0.66）。dark parity 需先釐清 catalog dark 語意，非 cheap seam。
  { case: 'notebooks-stack-d1-cover-basic-light', params: { surface: 'notebooks-stack', scenario: 'd1-cover-basic', appearance: 'light' }, ref: { surface: 'Notebooks · Stack', scenario: 'D1 · cover composition basic', appearance: 'light' }, note: 'Notebooks stack · grid 2-up（page-bg 全幅不透明）' },
  { case: 'notebooks-stack-depth-100-light', params: { surface: 'notebooks-stack', scenario: 'depth-100', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'Depth · 100 字 (3 層)', appearance: 'light' }, note: 'Notebooks stack · single depth 100 字（3 層 cover）' },
  { case: 'notebooks-stack-d1-empty-light', params: { surface: 'notebooks-stack', scenario: 'd1-empty', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'D1 · empty notebook (0 詞 hides count)', appearance: 'light' }, note: 'Notebooks stack · single empty（0 詞 placeholder）' },
  // notebooks-stack batch expansion（dots/null pattern only，light，全幀；複用既有元件）。
  //   single → page-bg band 僅內容寬、周圍透明（transparent:true）；grid → page-bg 全幅不透明。
  { case: 'notebooks-stack-depth-0-light', params: { surface: 'notebooks-stack', scenario: 'depth-0', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'Depth · 0 字 (1 層)', appearance: 'light' }, note: 'Notebooks stack · single depth 0 字（1 層，fresh）' },
  { case: 'notebooks-stack-d1-large-card-count-light', params: { surface: 'notebooks-stack', scenario: 'd1-large-card-count', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'D1 · very large cardCount (99999)', appearance: 'light' }, note: 'Notebooks stack · single 99999 詞（monoLabel 字寬邊界）' },
  { case: 'notebooks-stack-d1-large-due-count-light', params: { surface: 'notebooks-stack', scenario: 'd1-large-due-count', appearance: 'light' }, ref: { surface: 'Notebooks · Stack', scenario: 'D1 · very large dueCount (9999)', appearance: 'light' }, note: 'Notebooks stack · grid 9999 到期（chip 不擠破）' },
  { case: 'notebooks-stack-d2-grid-height-light', params: { surface: 'notebooks-stack', scenario: 'd2-grid-height', appearance: 'light' }, ref: { surface: 'Notebooks · Stack', scenario: 'D2 · grid height stability (mixed due)', appearance: 'light' }, note: 'Notebooks stack · grid 高度穩定（due 0/>0 同高）' },
  { case: 'notebooks-stack-editorial-different-seeds-light', params: { surface: 'notebooks-stack', scenario: 'editorial-different-seeds', appearance: 'light' }, ref: { surface: 'Notebooks · Stack', scenario: 'Editorial · different seeds 2-up', appearance: 'light' }, note: 'Notebooks stack · grid 不同 seed 2-up' },
  { case: 'notebooks-stack-editorial-spine-rotation-light', params: { surface: 'notebooks-stack', scenario: 'editorial-spine-rotation', appearance: 'light' }, transparent: true, ref: { surface: 'Notebooks · Stack', scenario: 'Editorial · spine 隨 rotation (active)', appearance: 'light' }, note: 'Notebooks stack · single spine rotation（active）' },
  { case: 'notebooks-stack-stress-happy-2up-light', params: { surface: 'notebooks-stack', scenario: 'stress-happy-2up', appearance: 'light' }, ref: { surface: 'Notebooks · Stack', scenario: 'Stress · happy 2-up', appearance: 'light' }, note: 'Notebooks stack · grid happy 2-up（mediumActive + fresh）' },
  { case: 'word-detail-card-full-light', params: { surface: 'word-detail-card', scenario: 'full', appearance: 'light', crop: 'component' }, crop: '.word-detail-card', ref: { surface: 'Word Detail · Card Document', scenario: 'Full', appearance: 'light' }, note: 'Word detail card · full（詞 + 翻譯 + 例句 + collocations）' },
  { case: 'word-detail-card-compact-light', params: { surface: 'word-detail-card', scenario: 'compact', appearance: 'light', crop: 'component' }, crop: '.word-detail-card', ref: { surface: 'Word Detail · Card Document', scenario: 'Compact', appearance: 'light' }, note: 'Word detail card · compact' },
  { case: 'word-detail-card-no-example-light', params: { surface: 'word-detail-card', scenario: 'no-example', appearance: 'light', crop: 'component' }, crop: '.word-detail-card', ref: { surface: 'Word Detail · Card Document', scenario: 'No example / collocations', appearance: 'light' }, note: 'Word detail card · 無例句/collocations' },
  // ── Composite layer batch-8 ── Settings Preferences/Review（full-frame transparent）+ Subscription（component crop .settings-subscription-surface）
  // settings-preferences：transparent .fill scene 的 ScrollView 內容落在 in-app chrome 之下。
  //   逐列掃 ios-normalized.png 得 content 頂緣 ≈225 capture px → ÷dpr3 = 75 CSS px（commit
  //   3cea3e84）。切勿把 capture px 當 CSS 值（231 CSS = 693 capture px 會把內容打到 ~900px）。
  { case: 'settings-preferences-with-auto-sync-light', params: { surface: 'settings-preferences', scenario: 'with-auto-sync', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Preferences', scenario: '含自動同步', appearance: 'light' }, note: 'Settings preferences · 含自動同步列' },
  { case: 'settings-preferences-auto-sync-off-light', params: { surface: 'settings-preferences', scenario: 'auto-sync-off', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Preferences', scenario: '自動同步關閉', appearance: 'light' }, note: 'Settings preferences · 自動同步關閉' },
  { case: 'settings-preferences-logged-out-light', params: { surface: 'settings-preferences', scenario: 'logged-out', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Preferences', scenario: '未登入 / 無同步列', appearance: 'light' }, note: 'Settings preferences · 未登入（無同步列）' },
  { case: 'settings-review-intensive-light', params: { surface: 'settings-review', scenario: 'intensive', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Review', scenario: '密集模式', appearance: 'light' }, note: 'Settings review · 密集模式' },
  { case: 'settings-review-relaxed-light', params: { surface: 'settings-review', scenario: 'relaxed', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Review', scenario: '寬鬆模式', appearance: 'light' }, note: 'Settings review · 寬鬆模式' },
  { case: 'settings-review-frozen-light', params: { surface: 'settings-review', scenario: 'frozen', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Review', scenario: '已凍結進度', appearance: 'light' }, note: 'Settings review · 已凍結進度' },
  { case: 'settings-review-custom-light', params: { surface: 'settings-review', scenario: 'custom', appearance: 'light' }, transparent: true, ref: { surface: 'Settings Sections · Review', scenario: '自訂模式 / 展開參數', appearance: 'light' }, note: 'Settings review · 自訂模式（展開參數）' },
  { case: 'settings-subscription-pro-active-light', params: { surface: 'settings-subscription', scenario: 'pro-active', appearance: 'light', crop: 'component' }, crop: '.settings-subscription-surface', transparent: true, ref: { surface: 'Settings Subscription Section', scenario: 'Pro Active', appearance: 'light' }, note: 'Settings subscription · Pro active' },
  { case: 'settings-subscription-loading-light', params: { surface: 'settings-subscription', scenario: 'loading', appearance: 'light', crop: 'component' }, crop: '.settings-subscription-surface', transparent: true, ref: { surface: 'Settings Subscription Section', scenario: 'Loading', appearance: 'light' }, note: 'Settings subscription · loading' },
  { case: 'settings-subscription-pricing-unavailable-light', params: { surface: 'settings-subscription', scenario: 'pricing-unavailable', appearance: 'light', crop: 'component' }, crop: '.settings-subscription-surface', transparent: true, ref: { surface: 'Settings Subscription Section', scenario: 'Pricing Unavailable', appearance: 'light' }, note: 'Settings subscription · pricing unavailable' },
  { case: 'settings-subscription-inactive-free-light', params: { surface: 'settings-subscription', scenario: 'inactive-free', appearance: 'light', crop: 'component' }, crop: '.settings-subscription-surface', transparent: true, ref: { surface: 'Settings Subscription Section', scenario: 'Inactive · Free', appearance: 'light' }, note: 'Settings subscription · inactive free' },
  // ── Composite layer batch-9 ── Podcast Bubble Cell（component .podcast-bubble-cell-surface）+ Hero（full-frame transparent）+ Rail Card（component .prc-surface）
  { case: 'podcast-bubble-cell-highlighted-active-light', params: { surface: 'podcast-bubble-cell', scenario: 'highlighted-active', appearance: 'light', crop: 'component' }, crop: '.podcast-bubble-cell-surface', transparent: true, ref: { surface: 'Podcast · Bubble Cell', scenario: 'Highlighted (active)', appearance: 'light' }, note: 'Podcast bubble cell · highlighted active' },
  { case: 'podcast-bubble-cell-idle-non-current-light', params: { surface: 'podcast-bubble-cell', scenario: 'idle-non-current', appearance: 'light', crop: 'component' }, crop: '.podcast-bubble-cell-surface', transparent: true, ref: { surface: 'Podcast · Bubble Cell', scenario: 'Idle (non-current)', appearance: 'light' }, note: 'Podcast bubble cell · idle' },
  { case: 'podcast-bubble-cell-right-aligned-speaker-light', params: { surface: 'podcast-bubble-cell', scenario: 'right-aligned-speaker', appearance: 'light', crop: 'component' }, crop: '.podcast-bubble-cell-surface', transparent: true, ref: { surface: 'Podcast · Bubble Cell', scenario: 'Right-aligned speaker', appearance: 'light' }, note: 'Podcast bubble cell · right-aligned' },
  { case: 'podcast-bubble-cell-vocab-highlighted-light', params: { surface: 'podcast-bubble-cell', scenario: 'vocab-highlighted', appearance: 'light', crop: 'component' }, crop: '.podcast-bubble-cell-surface', transparent: true, ref: { surface: 'Podcast · Bubble Cell', scenario: 'Vocab highlighted', appearance: 'light' }, note: 'Podcast bubble cell · vocab highlight' },
  { case: 'podcast-hero-full-meta-light', params: { surface: 'podcast-hero', scenario: 'full-meta', appearance: 'light' }, transparent: true, ref: { surface: 'Podcast Hero', scenario: 'Full meta', appearance: 'light' }, note: 'Podcast hero · full meta' },
  { case: 'podcast-hero-long-title-multi-host-light', params: { surface: 'podcast-hero', scenario: 'long-title-multi-host', appearance: 'light' }, transparent: true, ref: { surface: 'Podcast Hero', scenario: 'Long title · multi host', appearance: 'light' }, note: 'Podcast hero · long title multi-host' },
  { case: 'podcast-hero-fresh-no-meta-light', params: { surface: 'podcast-hero', scenario: 'fresh-no-meta', appearance: 'light' }, transparent: true, ref: { surface: 'Podcast Hero', scenario: 'Fresh · no meta', appearance: 'light' }, note: 'Podcast hero · fresh no-meta' },
  { case: 'podcast-hero-episodes-only-light', params: { surface: 'podcast-hero', scenario: 'episodes-only', appearance: 'light' }, transparent: true, ref: { surface: 'Podcast Hero', scenario: 'Episodes only', appearance: 'light' }, note: 'Podcast hero · episodes only' },
  { case: 'podcast-hero-a11y3-light', params: { surface: 'podcast-hero', scenario: 'a11y3', appearance: 'light' }, transparent: true, ref: { surface: 'Podcast Hero', scenario: 'A11y3', appearance: 'light' }, note: 'Podcast hero · a11y3' },
  { case: 'podcast-rail-card-resume-light', params: { surface: 'podcast-rail-card', scenario: 'resume', appearance: 'light', crop: 'component' }, crop: '.prc-surface', transparent: true, ref: { surface: 'Podcast Continue Rail Card', scenario: 'Resume', appearance: 'light' }, note: 'Podcast rail card · resume' },
  { case: 'podcast-rail-card-no-progress-light', params: { surface: 'podcast-rail-card', scenario: 'no-progress', appearance: 'light', crop: 'component' }, crop: '.prc-surface', transparent: true, ref: { surface: 'Podcast Continue Rail Card', scenario: 'No progress', appearance: 'light' }, note: 'Podcast rail card · no progress' },
  { case: 'podcast-rail-card-long-title-light', params: { surface: 'podcast-rail-card', scenario: 'long-title', appearance: 'light', crop: 'component' }, crop: '.prc-surface', transparent: true, ref: { surface: 'Podcast Continue Rail Card', scenario: 'Long title', appearance: 'light' }, note: 'Podcast rail card · long title' },
  { case: 'podcast-rail-card-large-numbers-light', params: { surface: 'podcast-rail-card', scenario: 'large-numbers', appearance: 'light', crop: 'component' }, crop: '.prc-surface', transparent: true, ref: { surface: 'Podcast Continue Rail Card', scenario: 'Large numbers', appearance: 'light' }, note: 'Podcast rail card · large numbers' },
  { case: 'podcast-rail-card-a11y3-light', params: { surface: 'podcast-rail-card', scenario: 'a11y3', appearance: 'light', crop: 'component' }, crop: '.prc-surface', transparent: true, ref: { surface: 'Podcast Continue Rail Card', scenario: 'A11y3', appearance: 'light' }, note: 'Podcast rail card · a11y3' },
  // ── Composite layer batch-10 ── Account Auth Summary（full-frame transparent 垂直置中）+ Login Sheet（full-frame opaque）+ Welcome（full-frame opaque）
  { case: 'account-auth-summary-initials-free-light', params: { surface: 'account-auth-summary', scenario: 'initials-free', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Auth Summary', scenario: 'Initials · Free', appearance: 'light' }, note: 'Account auth summary · initials free' },
  { case: 'account-auth-summary-initials-pro-light', params: { surface: 'account-auth-summary', scenario: 'initials-pro', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Auth Summary', scenario: 'Initials · Pro', appearance: 'light' }, note: 'Account auth summary · initials pro' },
  { case: 'account-auth-summary-long-name-email-overflow-light', params: { surface: 'account-auth-summary', scenario: 'long-name-email-overflow', appearance: 'light' }, transparent: true, ref: { surface: 'Account Section · Auth Summary', scenario: 'Long Name + Email Overflow', appearance: 'light' }, note: 'Account auth summary · long name/email overflow' },
  { case: 'login-sheet-default-light', params: { surface: 'login-sheet', scenario: 'default', appearance: 'light' }, ref: { surface: 'Login Sheet', scenario: 'Default', appearance: 'light' }, note: 'Login sheet · default' },
  { case: 'login-sheet-authenticating-light', params: { surface: 'login-sheet', scenario: 'authenticating', appearance: 'light' }, ref: { surface: 'Login Sheet', scenario: 'Authenticating', appearance: 'light' }, note: 'Login sheet · authenticating' },
  { case: 'login-sheet-error-light', params: { surface: 'login-sheet', scenario: 'error', appearance: 'light' }, ref: { surface: 'Login Sheet', scenario: 'Error', appearance: 'light' }, note: 'Login sheet · error' },
  { case: 'welcome-step-1-capture-light', params: { surface: 'welcome', scenario: 'step-1-capture', appearance: 'light' }, ref: { surface: 'Welcome', scenario: 'Step 1 / Capture', appearance: 'light' }, note: 'Welcome · step 1 capture' },
  { case: 'welcome-step-2-link-light', params: { surface: 'welcome', scenario: 'step-2-link', appearance: 'light' }, ref: { surface: 'Welcome', scenario: 'Step 2 / Link', appearance: 'light' }, note: 'Welcome · step 2 link' },
  { case: 'welcome-step-3-review-light', params: { surface: 'welcome', scenario: 'step-3-review', appearance: 'light' }, ref: { surface: 'Welcome', scenario: 'Step 3 / Review', appearance: 'light' }, note: 'Welcome · step 3 review' },
  { case: 'welcome-step-3-dark-light', params: { surface: 'welcome', scenario: 'step-3-dark', appearance: 'light' }, ref: { surface: 'Welcome', scenario: 'Step 3 / Dark', appearance: 'light' }, note: 'Welcome · step 3 dark（catalog 離線 preferredColorScheme no-op → 渲染 light）' },
];
