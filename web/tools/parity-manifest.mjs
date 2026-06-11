/**
 * parity-manifest.mjs — single source of truth for the web-app ⟷ iOS parity
 * case list, shared by shots.mjs (capture URLs), compare.mjs and
 * parity-audit.mjs.
 *
 * `ref` addresses the iOS counterpart by Catalog taxonomy (see
 * design-system/parity/ios-ref.mjs); `params` drives the harness URL
 * (?scenario/?appearance — web/src/harness/scenarios.ts) so capture and
 * reference stay addressed by one entry.
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
];
