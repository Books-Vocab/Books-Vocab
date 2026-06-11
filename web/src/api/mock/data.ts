// Mock API payloads, shaped to the backend pydantic schemas (./../types) and
// derived from the existing surface fixtures so mock mode renders the same
// content the parity captures already assert. Surface fixtures are
// presentation-shaped; here we lift their domain values into API-shaped rows.

import { VOCABULARY_FIXTURES } from '../../surfaces/vocabulary/fixtures'
import type {
  CardResponse,
  EntitlementsResponse,
  PodcastProgressListResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
  QuotaResponse,
  ReviewEventsResponse,
  UserConfigResponse,
  VocabAddResponse,
} from '../types'

const NOW_ISO = '2026-06-11T00:00:00Z'

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
