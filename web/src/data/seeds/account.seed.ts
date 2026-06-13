// Account + notebook domain seed — the canonical Source-of-Truth for the web
// app's demo identity and notebook taxonomy.
//
// Values are lifted verbatim from the legacy api/mock/data.ts (MOCK_NOTEBOOKS /
// MOCK_USER_PROFILE / MOCK_DELETE_ACCOUNT) so the transformer output stays
// byte-equivalent to today's mock responses. This file holds DOMAIN values
// only — no API-response shaping (that lives in ../transformers).

/** Shared synthetic "now" — every seed anchors timestamps here. */
export const SEED_NOW_ISO = '2026-06-11T00:00:00Z'

/** Default notebook color for seeded notebooks. */
export const NOTEBOOK_DEFAULT_COLOR = '#AFC2D3'

export interface NotebookSeed {
  id: string
  name: string
  color: string | null
  coverPattern: string | null
  sortOrder: number
  isDefault: boolean
  /** Authored card count for this notebook (drives NotebookResponse.cardCount). */
  cardCount: number
}

/**
 * Demo notebooks. `cardCount` is authored here (the legacy mock hard-coded it);
 * the vocabulary seed's card→notebook assignment must stay consistent with the
 * default notebook's count (4 seeded cards all live in `default`).
 */
export const NOTEBOOK_SEEDS: NotebookSeed[] = [
  { id: 'default', name: '我的單字本', color: NOTEBOOK_DEFAULT_COLOR, coverPattern: null, sortOrder: 0, isDefault: true, cardCount: 3 },
  { id: 'classics', name: '經典文學', color: NOTEBOOK_DEFAULT_COLOR, coverPattern: null, sortOrder: 1, isDefault: false, cardCount: 2 },
  { id: 'science', name: '科普閱讀', color: NOTEBOOK_DEFAULT_COLOR, coverPattern: null, sortOrder: 2, isDefault: false, cardCount: 1 },
]

export interface AccountSeed {
  userId: string
  email: string | null
  displayName: string | null
  /** Linked auth identities — used by the delete-account summary. */
  linkedIds: string[]
  /** Data dirs purged on account deletion (delete-account summary). */
  deletedDirs: string[]
  /** Deterministic access token the mock /auth/verify mints. */
  accessToken: string
}

export const ACCOUNT_SEED: AccountSeed = {
  userId: 'mock-user',
  email: 'reader@example.com',
  displayName: '示範使用者',
  linkedIds: ['apple:mock-user'],
  deletedDirs: ['/data/users/mock-user'],
  accessToken: 'mock-access-token',
}
