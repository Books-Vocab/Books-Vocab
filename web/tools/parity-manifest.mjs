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
  {
    case: 'selection-toolbar-multiple-light',
    params: { surface: 'selection-toolbar', scenario: 'selection-multiple', appearance: 'light' },
    ref: { surface: 'Selection Toolbar', scenario: 'Multiple selected', appearance: 'light' },
    note: 'Selection toolbar multiple selected (light)',
  },
  {
    case: 'selection-toolbar-single-light',
    params: { surface: 'selection-toolbar', scenario: 'selection-single', appearance: 'light' },
    ref: { surface: 'Selection Toolbar', scenario: 'Single selected', appearance: 'light' },
    note: 'Selection toolbar single selected (light)',
  },
  {
    case: 'selection-toolbar-none-light',
    params: { surface: 'selection-toolbar', scenario: 'selection-none', appearance: 'light' },
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
];
