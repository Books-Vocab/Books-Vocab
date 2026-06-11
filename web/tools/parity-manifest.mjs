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
  // Translation panel（R2）— ReaderScenarios.swift「Reader · Translation」6 態
  // （layout .fill = scrim + bottom-sheet panel，gorgeous / adj.）。皆 light。
  {
    case: 'reader-translation-expanded-light',
    params: { surface: 'reader', scenario: 'translation-expanded', appearance: 'light' },
    ref: { surface: 'Reader · Translation', scenario: 'Expanded', appearance: 'light' },
    note: 'Translation panel expanded (light)',
  },
  {
    case: 'reader-translation-collapsed-light',
    params: { surface: 'reader', scenario: 'translation-collapsed', appearance: 'light' },
    ref: { surface: 'Reader · Translation', scenario: 'Collapsed', appearance: 'light' },
    note: 'Translation panel collapsed (light)',
  },
  {
    case: 'reader-translation-loading-light',
    params: { surface: 'reader', scenario: 'translation-loading', appearance: 'light' },
    ref: { surface: 'Reader · Translation', scenario: 'Loading', appearance: 'light' },
    note: 'Translation panel loading (light)',
  },
  {
    case: 'reader-translation-error-light',
    params: { surface: 'reader', scenario: 'translation-error', appearance: 'light' },
    ref: { surface: 'Reader · Translation', scenario: 'Error', appearance: 'light' },
    note: 'Translation panel translation-error (light)',
  },
  {
    case: 'reader-translation-explain-only-light',
    params: { surface: 'reader', scenario: 'translation-explain-only', appearance: 'light' },
    ref: { surface: 'Reader · Translation', scenario: 'Explain Only', appearance: 'light' },
    note: 'Translation panel explain-only (light)',
  },
  {
    case: 'reader-translation-explanation-error-light',
    params: { surface: 'reader', scenario: 'translation-explanation-error', appearance: 'light' },
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
];
