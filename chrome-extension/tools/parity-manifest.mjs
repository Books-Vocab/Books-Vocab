/**
 * parity-manifest.mjs — single source of truth for the Chrome ⟷ iOS parity
 * case list, shared by compare.mjs and parity-audit.mjs (previously two
 * drifting copies).
 *
 * `ref` addresses the iOS counterpart by Catalog taxonomy (see ios-ref.mjs);
 * null = Chrome-only state with no iOS counterpart. The iOS app has no sepia
 * theme outside the reader, so sepia cases pair against the light reference.
 */
export const PARITY = [
  {
    case: 'sidepanel-content-light',
    ref: { surface: 'Vocabulary List View', scenario: 'Populated · mixed sync states', appearance: 'light' },
    note: '單字列表 (light)',
  },
  {
    case: 'content-popup-notebook-light',
    ref: null,
    note: '選詞 popup + 目標單字本 selector (Chrome content state)',
  },
  {
    case: 'sidepanel-outbox-failed-light',
    ref: null,
    note: '失敗暫存列 + 手動重試 (Chrome outbox state)',
  },
  {
    case: 'sidepanel-notebook-sheet-light',
    ref: { surface: 'Notebook Edit', scenario: 'Edit · color + pattern', appearance: 'light' },
    note: '單字本編輯 sheet',
  },
  {
    case: 'sidepanel-content-dark',
    ref: { surface: 'Vocabulary List View', scenario: 'Populated · mixed sync states', appearance: 'dark' },
    note: '單字列表 (dark ⟷ dark)',
  },
  {
    case: 'sidepanel-content-sepia',
    ref: { surface: 'Vocabulary List View', scenario: 'Populated · mixed sync states', appearance: 'light' },
    note: '單字列表 (sepia — iOS 無 sepia，對 light)',
  },
  {
    case: 'sidepanel-detail-light',
    ref: { surface: 'Word Detail Presenter', scenario: 'Chrome · links + review', appearance: 'light' },
    note: '單字詳情',
  },
  {
    case: 'options-settings-light',
    ref: { surface: 'Settings', scenario: 'Subscribed Active', appearance: 'light' },
    note: '設定頁（已登入/Pro）',
  },
  {
    case: 'sidepanel-empty-light',
    ref: { surface: 'Vocabulary List View', scenario: 'Empty · zero data', appearance: 'light' },
    note: '空狀態',
  },
  {
    case: 'sidepanel-error-light',
    ref: null,
    note: '錯誤狀態 (Chrome-only)',
  },
];
