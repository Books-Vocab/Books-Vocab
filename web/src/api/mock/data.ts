// Mock API payloads, shaped to the backend pydantic schemas (./../types) and
// derived from the existing surface fixtures so mock mode renders the same
// content the parity captures already assert. Surface fixtures are
// presentation-shaped; here we lift their domain values into API-shaped rows.

import { VOCABULARY_FIXTURES } from '../../surfaces/vocabulary/fixtures'
import type {
  BookMetadataResponse,
  CardResponse,
  EntitlementsResponse,
  NotebookResponse,
  PodcastProgressListResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
  QuotaResponse,
  ReviewEventsResponse,
  UserConfigResponse,
  VocabAddResponse,
} from '../types'

const NOW_ISO = '2026-06-11T00:00:00Z'

export const MOCK_LIBRARY_BOOKS: BookMetadataResponse[] = [
  {
    id: 'book-1',
    client_book_id: 'atomic-habits-epub',
    title: 'Atomic Habits',
    author: 'James Clear',
    language: 'en',
    format: 'epub',
    notebook_id: null,
    is_deleted: false,
    updated_at: NOW_ISO,
    locator: null,
    progression: 0.15,
    position_updated_at: null,
  },
  {
    id: 'book-2',
    client_book_id: 'deep-work-pdf',
    title: 'Deep Work',
    author: 'Cal Newport',
    language: 'en',
    format: 'pdf',
    notebook_id: null,
    is_deleted: false,
    updated_at: NOW_ISO,
    locator: null,
    progression: 0.0,
    position_updated_at: null,
  },
  {
    id: 'book-3',
    client_book_id: 'flow-epub',
    title: 'Flow',
    author: 'Mihaly Csikszentmihalyi',
    language: 'en',
    format: 'epub',
    notebook_id: null,
    is_deleted: false,
    updated_at: NOW_ISO,
    locator: null,
    progression: 0.0,
    position_updated_at: null,
  },
  {
    id: 'book-4',
    client_book_id: 'meditations-txt',
    title: 'Meditations',
    author: 'Marcus Aurelius',
    language: 'en',
    format: 'txt',
    notebook_id: null,
    is_deleted: false,
    updated_at: NOW_ISO,
    locator: null,
    progression: 0.0,
    position_updated_at: null,
  },
  {
    id: 'book-5',
    client_book_id: 'on-writing-well-md',
    title: 'On Writing Well',
    author: 'William Zinsser',
    language: 'en',
    format: 'md',
    notebook_id: null,
    is_deleted: false,
    updated_at: NOW_ISO,
    locator: null,
    progression: 0.0,
    position_updated_at: null,
  },
]

let nextBookId = 100

export function mockLibraryCreate(req: {
  client_book_id: string
  title: string
  author?: string | null
  language?: string | null
  format?: string | null
}): BookMetadataResponse {
  // Idempotency: check existing by client_book_id
  const existing = MOCK_LIBRARY_BOOKS.find((b) => b.client_book_id === req.client_book_id)
  if (existing) {
    return existing
  }
  const id = `book-${nextBookId++}`
  const created: BookMetadataResponse = {
    id,
    client_book_id: req.client_book_id,
    title: req.title,
    author: req.author ?? null,
    language: req.language ?? null,
    format: req.format ?? null,
    notebook_id: null,
    is_deleted: false,
    updated_at: NOW_ISO,
    locator: null,
    progression: null,
    position_updated_at: null,
  }
  MOCK_LIBRARY_BOOKS.push(created)
  return created
}

export function mockLibraryUpdate(
  id: string,
  req: Partial<{
    title: string | null
    author: string | null
    language: string | null
    format: string | null
    notebook_id: string | null
  }>,
): BookMetadataResponse | undefined {
  const base = MOCK_LIBRARY_BOOKS.find((b) => b.id === id)
  if (!base) return undefined
  return {
    ...base,
    title: req.title !== undefined ? (req.title ?? base.title) : base.title,
    author: req.author !== undefined ? req.author : base.author,
    language: req.language !== undefined ? req.language : base.language,
    format: req.format !== undefined ? req.format : base.format,
    notebook_id: req.notebook_id !== undefined ? req.notebook_id : base.notebook_id,
  }
}

export function mockLibraryPosition(
  id: string,
  req: {
    locator?: string | null
    progression?: number | null
    position_updated_at?: string | null
  },
): BookMetadataResponse | undefined {
  const base = MOCK_LIBRARY_BOOKS.find((b) => b.id === id)
  if (!base) return undefined
  return {
    ...base,
    locator: req.locator !== undefined ? req.locator : base.locator,
    progression: req.progression !== undefined ? req.progression : base.progression,
    position_updated_at: req.position_updated_at !== undefined ? req.position_updated_at : base.position_updated_at,
  }
}

export const MOCK_NOTEBOOKS: NotebookResponse[] = [
  {
    id: 'default',
    name: '我的單字本',
    color: '#AFC2D3',
    coverPattern: null,
    sortOrder: 0,
    isDefault: true,
    isDeleted: false,
    cardCount: 3,
    updatedAt: NOW_ISO,
  },
  {
    id: 'classics',
    name: '經典文學',
    color: '#AFC2D3',
    coverPattern: null,
    sortOrder: 1,
    isDefault: false,
    isDeleted: false,
    cardCount: 2,
    updatedAt: NOW_ISO,
  },
  {
    id: 'science',
    name: '科普閱讀',
    color: '#AFC2D3',
    coverPattern: null,
    sortOrder: 2,
    isDefault: false,
    isDeleted: false,
    cardCount: 1,
    updatedAt: NOW_ISO,
  },
]

let nextNotebookId = 100

export function mockNotebookCreate(req: { name: string; color?: string | null; cover_pattern?: string | null }): NotebookResponse {
  const id = `nb-${nextNotebookId++}`
  return {
    id,
    name: req.name,
    color: req.color ?? '#AFC2D3',
    coverPattern: req.cover_pattern ?? null,
    sortOrder: 10,
    isDefault: false,
    isDeleted: false,
    cardCount: 0,
    updatedAt: NOW_ISO,
  }
}

export function mockNotebookUpdate(id: string, req: Partial<{ name: string; color: string | null; sort_order: number; cover_pattern: string | null }>): NotebookResponse | undefined {
  const base = MOCK_NOTEBOOKS.find((n) => n.id === id)
  if (!base) return undefined
  return {
    ...base,
    name: req.name ?? base.name,
    color: req.color !== undefined ? req.color : base.color,
    coverPattern: req.cover_pattern !== undefined ? req.cover_pattern : base.coverPattern,
    sortOrder: req.sort_order ?? base.sortOrder,
  }
}

function card(
  partial: Pick<CardResponse, 'id' | 'content' | 'meaning' | 'pos'> &
    Partial<CardResponse>,
): CardResponse {
  return {
    difficulty: null,
    difficultyTier: null,
    note: null,
    collocations: [],
    examples: [],
    mode: 'recognition',
    isDeleted: false,
    isArchived: false,
    inflections: [],
    linksByKind: {},
    notebookId: 'default',
    source: null,
    updatedAt: NOW_ISO,
    reviewIntervalHours: 12.0,
    nextReviewAt: NOW_ISO,
    lastReviewedAt: null,
    reviewCount: 0,
    lapseCount: 0,
    reviewStreak: 0,
    lastReviewFeedback: -1,
    ...partial,
  }
}

// Lift the populated vocabulary fixture (4 synced unlearned rows) into
// API-shaped CardResponse rows. Word/translation/pos mirror the fixture verbatim.
export const MOCK_VOCAB_CARDS: CardResponse[] = VOCABULARY_FIXTURES.populated.rows.map(
  (row, i) =>
    card({
      id: `card-${i + 1}`,
      content: row.word,
      meaning: row.translation,
      pos: row.partOfSpeech.replace(/\.$/, '') || null,
    }),
)

export function mockVocabByWord(word: string): CardResponse | undefined {
  return MOCK_VOCAB_CARDS.find((c) => c.content === word)
}

export function mockVocabAdd(count: number): VocabAddResponse {
  return {
    created: count,
    skipped: 0,
    duplicates: [],
    cardIds: Object.fromEntries(
      Array.from({ length: count }, (_, i) => [`pending-${i}`, `new-card-${i}`]),
    ),
  }
}

export const MOCK_REVIEW_EVENTS: ReviewEventsResponse = {
  entries: [],
  cursor: null,
}

// Editorial podcast catalog — opaque dicts; shape mirrors the producer JSON
// (id / title / episodes) the iOS bookshelf + player consume.
export const MOCK_PODCAST_SERIES: PodcastSeriesSummary[] = [
  {
    id: 'pride-and-prejudice',
    title: 'Pride and Prejudice',
    author: 'Jane Austen',
    episode_count: 6,
  },
]

export const MOCK_PODCAST_DETAIL: PodcastSeriesDetail = {
  id: 'pride-and-prejudice',
  title: 'Pride and Prejudice',
  author: 'Jane Austen',
  episodes: [
    { ep_num: 1, title: 'Chapter 1', duration_sec: 1832 },
    { ep_num: 2, title: 'Chapter 2', duration_sec: 1740 },
  ],
}

export const MOCK_PODCAST_PROGRESS: PodcastProgressListResponse = {
  items: [
    {
      series_id: 'pride-and-prejudice',
      ep_num: 1,
      position_sec: 6.09,
      duration_sec: 1832,
      updated_at: NOW_ISO,
    },
  ],
}

export const MOCK_USER_CONFIG: UserConfigResponse = {
  translation: null,
  review_clock: { is_paused: false, paused_at: null, updated_at: null },
  review_mode: {
    mode: 'relaxed',
    custom_initial_interval_hours: 12,
    custom_remembered_multiplier: 1.9,
    custom_forgot_multiplier: 0.45,
    custom_minimum_interval_hours: 6,
    custom_maximum_interval_hours: 1440,
    updated_at: null,
  },
  vocab_ui: null,
  auto_link: null,
}

export const MOCK_ENTITLEMENTS: EntitlementsResponse = {
  pro: {
    is_active: false,
    product_id: null,
    plan_name: null,
    price_display: null,
    status: 'none',
    is_trial: false,
    trial_days: null,
    will_renew: false,
    expires_at: null,
    source: 'app_store',
    last_synced_at: null,
  },
}

export const MOCK_QUOTA: QuotaResponse = {
  fraction: 0.12,
  reset_seconds: 43200,
}

/** A deterministic access token the mock /auth/verify mints. */
export const MOCK_ACCESS_TOKEN = 'mock-access-token'
