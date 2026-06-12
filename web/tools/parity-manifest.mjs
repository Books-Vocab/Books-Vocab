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
  // account-section deferred (see scenarios.ts note): top-aligned + safe-area top inset fix pending.
];
