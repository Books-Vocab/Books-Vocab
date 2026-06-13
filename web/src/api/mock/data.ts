// Mock API payloads, shaped to the backend pydantic schemas (./../types).
//
// SINGLE SOURCE OF TRUTH: every MOCK_* constant below is DERIVED from the
// unified seed (src/data/seeds) via the pure transformers (src/data/transformers)
// — zero hand-duplicated literals. The seed lifts the canonical demo values once;
// `toMockBackend(SEED)` shapes them into the API responses this mock serves, so
// the running app + tests see byte-equivalent output. A drift guard
// (src/data/validation/driftGuard.test.ts) fails if any MOCK_* diverges from
// transformer(SEED).
//
// Mutation handlers (create/update/delete/archive/…) still live here: they own
// the in-memory store semantics (idempotency, soft-delete tombstones, id minting)
// that are request-time behavior, not seed data.

import { SEED } from '../../data/seeds'
import { toMockBackend, type MockGraphLink } from '../../data/transformers'
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
  ReviewEventsResponse,
  UserConfigResponse,
  UserProfileResponse,
  VocabAddResponse,
  VocabContentPatch,
  VocabEntry,
} from '../types'

// All derived payloads come from a single transform of the unified seed.
const MOCK = toMockBackend(SEED)

const NOW_ISO = MOCK.nowIso

export const MOCK_LIBRARY_BOOKS: BookMetadataResponse[] = MOCK.libraryBooks

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

export const MOCK_NOTEBOOKS: NotebookResponse[] = MOCK.notebooks

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

// The seeded vocabulary cards (4 synced unlearned rows), derived from SEED.
export const MOCK_VOCAB_CARDS: CardResponse[] = MOCK.vocabCards

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
// non-empty history offline. The generator + params live in the seed +
// transformer (src/data); derived here from SEED.
export const MOCK_REVIEW_EVENTS: ReviewEventsResponse = MOCK.reviewEvents

// Editorial podcast catalog — opaque dicts; shape mirrors the producer JSON
// (id / title / episodes) the iOS bookshelf + player consume.
export const MOCK_PODCAST_SERIES: PodcastSeriesSummary[] = MOCK.podcastSeries

export const MOCK_PODCAST_DETAIL: PodcastSeriesDetail = MOCK.podcastDetail

export const MOCK_PODCAST_PROGRESS: PodcastProgressListResponse = MOCK.podcastProgress

export const MOCK_USER_CONFIG: UserConfigResponse = MOCK.userConfig

export const MOCK_ENTITLEMENTS: EntitlementsResponse = MOCK.entitlements

export const MOCK_QUOTA: QuotaResponse = MOCK.quota

// ── graph links ──────────────────────────────────────────────────────────────
// Edges between the seeded vocab cards. hidden links stay in the store (the
// real backend filters them server-side); the hide/unhide handlers mutate in
// place so a list() after an unhide observes the round-trip.
export const MOCK_GRAPH_LINKS: MockGraphLink[] = MOCK.graphLinks

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
export const MOCK_USER_PROFILE: UserProfileResponse = MOCK.userProfile

// DELETE /api/user/account — mirrors api_models/auth.py::DeleteAccountResponse.
export const MOCK_DELETE_ACCOUNT: DeleteAccountResponse = MOCK.deleteAccount

// GET /api/podcasts/{series}/{ep}/subtitle — raw SRT text (text/plain).
export const MOCK_SUBTITLE_SRT = MOCK.subtitleSrt

/** A deterministic access token the mock /auth/verify mints. */
export const MOCK_ACCESS_TOKEN = MOCK.accessToken
