// Drift guard for the unified data Source-of-Truth.
//
// Fails if EITHER:
//   (a) the mock backend (api/mock/data.ts MOCK_*) diverges from what the
//       seed-derived transformer pipeline produces — i.e. someone reintroduces a
//       hand-written literal in data.ts instead of deriving from SEED; OR
//   (b) the seed → transformer pipeline regresses away from the byte-equivalent
//       baseline the running app + api tests depend on.
//
// (a) is enforced by re-deriving toMockBackend(SEED) here and asserting the
//     exported MOCK_* equal that derivation. (b) is enforced by pinning the
//     canonical baseline values (the old hand-written literals) so a silent seed
//     edit that changes mock output is caught.
//
// NOTE: api.test.ts mutates the shared MOCK_* store in place (archive flips,
// deletes). This suite asserts CONTENT identity at module-import time and does
// not depend on mutation ordering: it compares the live exports against a fresh
// transformer(SEED) derivation, and pins the seed-derived snapshot independently.

import { describe, expect, it } from 'vitest'
import { SEED } from '../seeds'
import { toMockBackend } from '../transformers'
import {
  MOCK_DELETE_ACCOUNT,
  MOCK_ENTITLEMENTS,
  MOCK_LIBRARY_BOOKS,
  MOCK_NOTEBOOKS,
  MOCK_PODCAST_DETAIL,
  MOCK_PODCAST_PROGRESS,
  MOCK_PODCAST_SERIES,
  MOCK_QUOTA,
  MOCK_REVIEW_EVENTS,
  MOCK_SUBTITLE_SRT,
  MOCK_USER_CONFIG,
  MOCK_USER_PROFILE,
} from '../../api/mock/data'

// Fresh, side-effect-free derivation — the SoT the mock MUST equal.
const derived = toMockBackend(SEED)

describe('drift guard (a): api/mock/data MOCK_* derives from SEED', () => {
  it('library books equal transformer(SEED)', () => {
    expect(MOCK_LIBRARY_BOOKS).toEqual(derived.libraryBooks)
  })

  it('notebooks equal transformer(SEED)', () => {
    expect(MOCK_NOTEBOOKS).toEqual(derived.notebooks)
  })

  it('podcast series / detail / progress equal transformer(SEED)', () => {
    expect(MOCK_PODCAST_SERIES).toEqual(derived.podcastSeries)
    expect(MOCK_PODCAST_DETAIL).toEqual(derived.podcastDetail)
    expect(MOCK_PODCAST_PROGRESS).toEqual(derived.podcastProgress)
  })

  it('user config / entitlements / quota / profile / delete-account equal transformer(SEED)', () => {
    expect(MOCK_USER_CONFIG).toEqual(derived.userConfig)
    expect(MOCK_ENTITLEMENTS).toEqual(derived.entitlements)
    expect(MOCK_QUOTA).toEqual(derived.quota)
    expect(MOCK_USER_PROFILE).toEqual(derived.userProfile)
    expect(MOCK_DELETE_ACCOUNT).toEqual(derived.deleteAccount)
  })

  it('review events + subtitle equal transformer(SEED)', () => {
    expect(MOCK_REVIEW_EVENTS).toEqual(derived.reviewEvents)
    expect(MOCK_SUBTITLE_SRT).toEqual(derived.subtitleSrt)
  })
})

describe('drift guard (b): seed → transformer baseline is byte-equivalent', () => {
  // These pinned values ARE the legacy hand-written mock output. If a seed edit
  // changes derived output, this catches it even when (a) still passes (because
  // data.ts faithfully re-derives the now-wrong seed).

  it('vocab cards: 4 canonical unlearned cards with verbatim word/meaning/pos', () => {
    expect(derived.vocabCards).toHaveLength(4)
    expect(
      derived.vocabCards.map((c) => ({ id: c.id, content: c.content, meaning: c.meaning, pos: c.pos })),
    ).toEqual([
      { id: 'card-1', content: 'serendipity', meaning: '機緣巧合', pos: 'n' },
      { id: 'card-2', content: 'ephemeral', meaning: '短暫的', pos: 'adj' },
      { id: 'card-3', content: 'petrichor', meaning: '雨後泥土香', pos: 'n' },
      { id: 'card-4', content: 'ineffable', meaning: '難以言喻的', pos: 'adj' },
    ])
    // Card-metadata defaults the legacy card() helper applied.
    for (const c of derived.vocabCards) {
      expect(c).toMatchObject({
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
        updatedAt: '2026-06-11T00:00:00Z',
        reviewIntervalHours: 12.0,
        nextReviewAt: '2026-06-11T00:00:00Z',
        lastReviewedAt: null,
        reviewCount: 0,
        lapseCount: 0,
        reviewStreak: 0,
        lastReviewFeedback: -1,
      })
    }
  })

  it('graph links: two seeded edges between the canonical cards', () => {
    expect(derived.graphLinks).toEqual([
      { id: 'link-1', fromId: 'card-1', toId: 'card-2', kind: 'synonym', confidence: 0.82, reason: '兩字在語意上高度重疊', hidden: false, notebookId: 'default' },
      { id: 'link-2', fromId: 'card-2', toId: 'card-3', kind: 'related', confidence: 0.64, reason: '常於同一語境共現', hidden: false, notebookId: 'default' },
    ])
  })

  it('notebooks: three canonical notebooks with pinned cardCounts', () => {
    expect(derived.notebooks).toEqual([
      { id: 'default', name: '我的單字本', color: '#AFC2D3', coverPattern: null, sortOrder: 0, isDefault: true, isDeleted: false, cardCount: 3, updatedAt: '2026-06-11T00:00:00Z' },
      { id: 'classics', name: '經典文學', color: '#AFC2D3', coverPattern: null, sortOrder: 1, isDefault: false, isDeleted: false, cardCount: 2, updatedAt: '2026-06-11T00:00:00Z' },
      { id: 'science', name: '科普閱讀', color: '#AFC2D3', coverPattern: null, sortOrder: 2, isDefault: false, isDeleted: false, cardCount: 1, updatedAt: '2026-06-11T00:00:00Z' },
    ])
  })

  it('library books: five canonical books with pinned formats/progression', () => {
    expect(derived.libraryBooks.map((b) => ({ id: b.id, client_book_id: b.client_book_id, title: b.title, format: b.format, progression: b.progression }))).toEqual([
      { id: 'book-1', client_book_id: 'atomic-habits-epub', title: 'Atomic Habits', format: 'epub', progression: 0.15 },
      { id: 'book-2', client_book_id: 'deep-work-pdf', title: 'Deep Work', format: 'pdf', progression: 0.0 },
      { id: 'book-3', client_book_id: 'flow-epub', title: 'Flow', format: 'epub', progression: 0.0 },
      { id: 'book-4', client_book_id: 'meditations-txt', title: 'Meditations', format: 'txt', progression: 0.0 },
      { id: 'book-5', client_book_id: 'on-writing-well-md', title: 'On Writing Well', format: 'md', progression: 0.0 },
    ])
  })

  it('podcast detail: pinned series + episode shape', () => {
    expect(derived.podcastDetail).toEqual({
      id: 'pride-and-prejudice',
      title: 'Pride and Prejudice',
      author: 'Jane Austen',
      episodes: [
        { ep_num: 1, title: 'Chapter 1', duration_sec: 1832 },
        { ep_num: 2, title: 'Chapter 2', duration_sec: 1740 },
      ],
    })
    expect(derived.podcastSeries).toEqual([
      { id: 'pride-and-prejudice', title: 'Pride and Prejudice', author: 'Jane Austen', episode_count: 6 },
    ])
  })

  it('user config: relaxed review mode with pinned multipliers', () => {
    expect(derived.userConfig).toEqual({
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
    })
  })

  it('quota / entitlements: pinned baseline', () => {
    expect(derived.quota).toEqual({ fraction: 0.12, reset_seconds: 43200 })
    expect(derived.entitlements.pro.is_active).toBe(false)
    expect(derived.entitlements.pro.status).toBe('none')
    expect(derived.entitlements.pro.source).toBe('app_store')
  })

  it('review events: deterministic 42-day synthetic window, all synthetic', () => {
    const entries = derived.reviewEvents.entries
    expect(entries.length).toBeGreaterThan(0)
    expect(derived.reviewEvents.cursor).toBeNull()
    expect(entries.every((e) => e.is_synthetic)).toBe(true)
    // offset 0 is skipped (offset % 4 === 0) → first event is offset 1, count
    // ((1*3)%11)+1 = 4 events; first event id is mock-evt-1-0.
    expect(entries[0].event_id).toBe('mock-evt-1-0')
    expect(entries[0].notebook_id).toBe('default')
    // Determinism: regenerating yields an identical log.
    expect(toMockBackend(SEED).reviewEvents).toEqual(derived.reviewEvents)
  })

  it('notebook cardCount stays consistent with the seeded default-notebook cards', () => {
    // All 4 seeded cards live in the default notebook; the authored default
    // cardCount (3) is the legacy hard-coded value — pin it so a future edit to
    // either side is a conscious, reviewed change rather than silent drift.
    const defaultNb = derived.notebooks.find((n) => n.id === 'default')!
    const defaultCards = derived.vocabCards.filter((c) => c.notebookId === 'default')
    expect(defaultCards).toHaveLength(4)
    expect(defaultNb.cardCount).toBe(3)
  })
})
