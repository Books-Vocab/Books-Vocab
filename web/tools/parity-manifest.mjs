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
];
