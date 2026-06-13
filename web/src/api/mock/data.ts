// Mock API payloads, shaped to the backend pydantic schemas (./../types) and
// derived from the existing surface fixtures so mock mode renders the same
// content the parity captures already assert. Surface fixtures are
// presentation-shaped; here we lift their domain values into API-shaped rows.

import { VOCABULARY_FIXTURES } from '../../surfaces/vocabulary/fixtures'
import type {
  BookMetadataResponse,
  CardResponse,
  DeleteAccountResponse,
  DeleteBookResponse,
  EntitlementsResponse,
  ExplainResponse,
  GraphLinkResponse,
  NotebookResponse,
  PhraseTranslateResponse,
  PodcastProgressListResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
  QuickTranslateResponse,
  QuotaResponse,
  ReviewEventEntry,
  ReviewEventsResponse,
  UserConfigResponse,
  UserProfileResponse,
  VocabAddResponse,
  VocabContentPatch,
  VocabEntry,
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

// DELETE /api/library/books/{id} — mirrors backend soft-delete. Flips is_deleted
// in the in-memory store so list() (which filters deleted) hides it, then returns
// { deleted: id } to match api_models/library.py::DeleteBookResponse.
export function mockLibraryDelete(id: string): DeleteBookResponse | undefined {
  const base = MOCK_LIBRARY_BOOKS.find((b) => b.id === id)
  if (!base) return undefined
  base.is_deleted = true
  return { deleted: id }
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

// POST /api/vocab — mints a card id per submitted entry. The sync SoT
// (docs/reference/sync_lifecycle.md §"cardIds 不變式") requires `cardIds` to be
// keyed by the client-submitted word as a BYTE-EXACT echo — no NFC / case / trim
// normalization — because iOS reconcile does `cardIds[entry.word]` per-word.
// Keying by index (`pending-${i}`) silently breaks that reconcile, so we key by
// `entries[i].word` verbatim.
export function mockVocabAdd(entries: VocabEntry[]): VocabAddResponse {
  return {
    created: entries.length,
    skipped: 0,
    duplicates: [],
    cardIds: Object.fromEntries(
      entries.map((e, i) => [e.word, `new-card-${i}`]),
    ),
  }
}

// PATCH /api/vocab/{word}/archive — flip a card's archived flag in place.
export function mockVocabArchive(word: string, archived: boolean): CardResponse | undefined {
  const c = MOCK_VOCAB_CARDS.find((x) => x.content === word)
  if (!c) return undefined
  c.isArchived = archived
  return c
}

// DELETE /api/vocab/{word} — remove a card from the store.
export function mockVocabDelete(word: string): CardResponse | undefined {
  const idx = MOCK_VOCAB_CARDS.findIndex((x) => x.content === word)
  if (idx < 0) return undefined
  const [removed] = MOCK_VOCAB_CARDS.splice(idx, 1)
  return removed
}

// PATCH /api/vocab/{word} — NEW backend (mock-only). Partial content edit:
// only meaning / note / explanation are mutable. Returns the updated card.
// Note: there is no `explanation` field on CardResponse; the backend contract
// folds it into `note` for now, so we apply it there (last-write-wins).
export function mockVocabUpdateContent(
  word: string,
  patch: VocabContentPatch,
): CardResponse | undefined {
  const c = MOCK_VOCAB_CARDS.find((x) => x.content === word)
  if (!c) return undefined
  if (patch.meaning !== undefined) c.meaning = patch.meaning
  if (patch.note !== undefined) c.note = patch.note
  if (patch.explanation !== undefined) c.note = patch.explanation
  c.updatedAt = NOW_ISO
  return c
}

// Synthetic review-event log so shell-mode stats surfaces (vocab-calendar /
// vocab-heatmap, which derive activity from todayReview.events()) render a
// non-empty history offline. Anchored to NOW_ISO's day (2026-06-11); a few
// events per recent day across the last ~6 weeks. Only the calendar/heatmap
// derivations read this — no other surface consumes the event log.
function syntheticReviewEvents(): ReviewEventEntry[] {
  const anchor = new Date(NOW_ISO) // 2026-06-11T00:00:00Z
  const words = ['serendipity', 'ephemeral', 'quintessential', 'ubiquitous', 'eloquent']
  const entries: ReviewEventEntry[] = []
  // Past 42 days: skip every 4th day (gaps → streak/heatmap variety); count
  // ramps with a deterministic pattern to exercise intensity thresholds.
  for (let offset = 0; offset < 42; offset++) {
    if (offset % 4 === 0) continue
    const day = new Date(anchor)
    day.setUTCDate(day.getUTCDate() - offset)
    const count = ((offset * 3) % 11) + 1
    for (let i = 0; i < count; i++) {
      const at = new Date(day)
      at.setUTCHours(9, i * 7, 0, 0)
      const iso = at.toISOString()
      entries.push({
        event_id: `mock-evt-${offset}-${i}`,
        card_id: null,
        word_snapshot: words[i % words.length]!,
        notebook_id: 'default',
        feedback: i % 3 === 0 ? 0 : 1,
        reviewed_at: iso,
        created_at: iso,
        is_synthetic: true,
      })
    }
  }
  return entries
}

export const MOCK_REVIEW_EVENTS: ReviewEventsResponse = {
  entries: syntheticReviewEvents(),
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

// ── graph links ──────────────────────────────────────────────────────────────
// Edges between the seeded vocab cards. hidden links stay in the store (the
// real backend filters them server-side); the hide/unhide handlers mutate in
// place so a list() after an unhide observes the round-trip.
interface MockGraphLink extends GraphLinkResponse {
  hidden: boolean
  notebookId: string
}

export const MOCK_GRAPH_LINKS: MockGraphLink[] = [
  {
    id: 'link-1',
    fromId: 'card-1',
    toId: 'card-2',
    kind: 'synonym',
    confidence: 0.82,
    reason: '兩字在語意上高度重疊',
    hidden: false,
    notebookId: 'default',
  },
  {
    id: 'link-2',
    fromId: 'card-2',
    toId: 'card-3',
    kind: 'related',
    confidence: 0.64,
    reason: '常於同一語境共現',
    hidden: false,
    notebookId: 'default',
  },
]

function toGraphLink(l: MockGraphLink): GraphLinkResponse {
  return { id: l.id, fromId: l.fromId, toId: l.toId, kind: l.kind, confidence: l.confidence, reason: l.reason }
}

/** GET /api/graph/links — visible links for a notebook (default if omitted). */
export function mockGraphList(notebookId = 'default'): GraphLinkResponse[] {
  return MOCK_GRAPH_LINKS.filter((l) => l.notebookId === notebookId && !l.hidden).map(toGraphLink)
}

let nextLinkId = 100

/** POST /api/graph/links — create a manual link (judge synthesised here). */
export function mockGraphCreate(req: { from_id: string; to_id: string }, notebookId = 'default'): GraphLinkResponse {
  const link: MockGraphLink = {
    id: `link-${nextLinkId++}`,
    fromId: req.from_id,
    toId: req.to_id,
    kind: 'related',
    confidence: 0.7,
    reason: '使用者手動建立的連結',
    hidden: false,
    notebookId,
  }
  MOCK_GRAPH_LINKS.push(link)
  return toGraphLink(link)
}

/** PATCH /api/graph/links/{id}/hide|unhide — toggle hidden; true if found. */
export function mockGraphSetHidden(linkId: string, hidden: boolean): boolean {
  const l = MOCK_GRAPH_LINKS.find((x) => x.id === linkId)
  if (!l) return false
  l.hidden = hidden
  return true
}

/** DELETE /api/graph/links/{id} — remove a link; true if found. */
export function mockGraphDelete(linkId: string): boolean {
  const idx = MOCK_GRAPH_LINKS.findIndex((x) => x.id === linkId)
  if (idx < 0) return false
  MOCK_GRAPH_LINKS.splice(idx, 1)
  return true
}

// ── translate ────────────────────────────────────────────────────────────────
// Deterministic terse responses (t/p/r, t, e) — single-letter fields mirror the
// backend pydantic models verbatim. Echoes the requested word so tests assert
// the round-trip without coupling to a fixed dictionary.
export function mockTranslateQuick(word: string): QuickTranslateResponse {
  return { t: `${word} 的翻譯`, p: `/ˈmɒk/`, r: word }
}

export function mockTranslatePhrase(word: string): PhraseTranslateResponse {
  return { t: `${word} 的片語翻譯` }
}

export function mockTranslateExplain(word: string): ExplainResponse {
  return { e: `${word} 在此語境中的說明。` }
}

// ── user profile + account deletion ──────────────────────────────────────────
// GET /api/user/profile — NEW backend (mock-only) identity contract.
export const MOCK_USER_PROFILE: UserProfileResponse = {
  user_id: 'mock-user',
  email: 'reader@example.com',
  display_name: '示範使用者',
}

// DELETE /api/user/account — mirrors api_models/auth.py::DeleteAccountResponse.
export const MOCK_DELETE_ACCOUNT: DeleteAccountResponse = {
  deleted_user_id: 'mock-user',
  linked_ids: ['apple:mock-user'],
  deleted_dirs: ['/data/users/mock-user'],
}

// GET /api/podcasts/{series}/{ep}/subtitle — raw SRT text (text/plain).
export const MOCK_SUBTITLE_SRT = `1
00:00:00,000 --> 00:00:02,500
It is a truth universally acknowledged,

2
00:00:02,500 --> 00:00:05,000
that a single man in possession of a good fortune,
`

/** A deterministic access token the mock /auth/verify mints. */
export const MOCK_ACCESS_TOKEN = 'mock-access-token'
