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
  // These pinned values ARE the CODEGEN'd demo SoT (ops/demo/demo_dataset.json)
  // shaped through the transformer. If a seed/SoT edit changes derived output,
  // this catches it even when (a) still passes (because data.ts faithfully
  // re-derives the now-wrong seed). Regenerate via:
  //   (cd backend && uv run python ../ops/demo/build_demo.py emit-web --commit)
  // then repoint the values below if the change is intentional.

  it('vocab cards: 14 canonical cards with verbatim word/meaning/pos/notebook', () => {
    expect(derived.vocabCards).toHaveLength(14)
    expect(
      derived.vocabCards.map((c) => ({ id: c.id, content: c.content, meaning: c.meaning, pos: c.pos, notebookId: c.notebookId })),
    ).toEqual([
      { id: 'card-1', content: 'meticulous', meaning: '一絲不苟的；極為仔細的', pos: 'adj', notebookId: 'editorial-picks' },
      { id: 'card-2', content: 'discerning', meaning: '有洞察力的；能辨別細微差異的', pos: 'adj', notebookId: 'editorial-picks' },
      { id: 'card-3', content: 'evoke', meaning: '喚起；引發（情感或記憶）', pos: 'v', notebookId: 'editorial-picks' },
      { id: 'card-4', content: 'luminous', meaning: '明亮的；清晰動人的（文筆）', pos: 'adj', notebookId: 'editorial-picks' },
      { id: 'card-5', content: 'nuance', meaning: '細微差別；微妙之處', pos: 'n', notebookId: 'editorial-picks' },
      { id: 'card-6', content: 'entropy', meaning: '熵；系統的混亂程度', pos: 'n', notebookId: 'systems-thinking' },
      { id: 'card-7', content: 'cascade', meaning: '一連串；連鎖反應', pos: 'n', notebookId: 'systems-thinking' },
      { id: 'card-8', content: 'coherent', meaning: '連貫的；條理一致的', pos: 'adj', notebookId: 'systems-thinking' },
      { id: 'card-9', content: 'leverage', meaning: '善用；以槓桿放大效果', pos: 'v', notebookId: 'systems-thinking' },
      { id: 'card-10', content: 'feedback', meaning: '回饋；系統輸出反向影響輸入', pos: 'n', notebookId: 'systems-thinking' },
      { id: 'card-11', content: 'cadence', meaning: '節奏；穩定推進的步調', pos: 'n', notebookId: 'creative-practice' },
      { id: 'card-12', content: 'iterate', meaning: '反覆打磨；迭代改進', pos: 'v', notebookId: 'creative-practice' },
      { id: 'card-13', content: 'tactile', meaning: '有觸感的；能喚起手感的', pos: 'adj', notebookId: 'creative-practice' },
      { id: 'card-14', content: 'prototype', meaning: '原型；先做出可驗證的版本', pos: 'n', notebookId: 'creative-practice' },
    ])
    // Card-metadata defaults the transformer applies uniformly to every card.
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

  it('graph links: eight seeded edges joined by content within notebook', () => {
    expect(derived.graphLinks).toEqual([
      { id: 'link-1', fromId: 'card-1', toId: 'card-2', kind: 'shares_usage', confidence: 0.74, reason: 'Both describe the careful attention an editor brings to a text.', hidden: false, notebookId: 'editorial-picks' },
      { id: 'link-2', fromId: 'card-3', toId: 'card-4', kind: 'shares_usage', confidence: 0.71, reason: 'Luminous prose is precisely the kind that evokes feeling in a reader.', hidden: false, notebookId: 'editorial-picks' },
      { id: 'link-3', fromId: 'card-2', toId: 'card-5', kind: 'shares_usage', confidence: 0.79, reason: 'A discerning reader is one who can register nuance.', hidden: false, notebookId: 'editorial-picks' },
      { id: 'link-4', fromId: 'card-6', toId: 'card-7', kind: 'shares_usage', confidence: 0.81, reason: 'Both describe how disorder propagates through a system over time.', hidden: false, notebookId: 'systems-thinking' },
      { id: 'link-5', fromId: 'card-7', toId: 'card-8', kind: 'contrasts_with', confidence: 0.64, reason: 'Cascade emphasizes runaway propagation; coherent emphasizes orderly structure.', hidden: false, notebookId: 'systems-thinking' },
      { id: 'link-6', fromId: 'card-10', toId: 'card-9', kind: 'shares_usage', confidence: 0.77, reason: 'Feedback loops are a primary place to leverage a system.', hidden: false, notebookId: 'systems-thinking' },
      { id: 'link-7', fromId: 'card-12', toId: 'card-14', kind: 'shares_usage', confidence: 0.84, reason: 'Both belong to the fast feedback loops of product and design work.', hidden: false, notebookId: 'creative-practice' },
      { id: 'link-8', fromId: 'card-11', toId: 'card-13', kind: 'shares_usage', confidence: 0.68, reason: 'Both point to the felt rhythm and texture of a sustained practice.', hidden: false, notebookId: 'creative-practice' },
    ])
  })

  it('notebooks: implicit default + three dataset notebooks with pinned cardCounts', () => {
    expect(derived.notebooks).toEqual([
      { id: 'default', name: '我的單字本', color: '#AFC2D3', coverPattern: null, sortOrder: 0, isDefault: true, isDeleted: false, cardCount: 0, updatedAt: '2026-06-11T00:00:00Z' },
      { id: 'editorial-picks', name: 'Editorial Picks', color: '#8C6A5D', coverPattern: 'waves', sortOrder: 1, isDefault: false, isDeleted: false, cardCount: 5, updatedAt: '2026-06-11T00:00:00Z' },
      { id: 'systems-thinking', name: 'Systems Thinking', color: '#4F7C73', coverPattern: 'grid', sortOrder: 2, isDefault: false, isDeleted: false, cardCount: 5, updatedAt: '2026-06-11T00:00:00Z' },
      { id: 'creative-practice', name: 'Creative Practice', color: '#B96F5B', coverPattern: 'dots', sortOrder: 3, isDefault: false, isDeleted: false, cardCount: 4, updatedAt: '2026-06-11T00:00:00Z' },
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

  it('notebook cardCount equals the seeded card→notebook assignment per notebook', () => {
    // The SoT puts every card in a named notebook; the implicit default holds
    // none. Each notebook's authored cardCount must equal the number of cards
    // the seed assigns to it, so a future edit to either side is a conscious,
    // reviewed change rather than silent drift.
    for (const nb of derived.notebooks) {
      const cards = derived.vocabCards.filter((c) => c.notebookId === nb.id)
      expect(nb.cardCount).toBe(cards.length)
    }
    const defaultNb = derived.notebooks.find((n) => n.id === 'default')!
    expect(defaultNb.cardCount).toBe(0)
    expect(derived.vocabCards.filter((c) => c.notebookId === 'default')).toHaveLength(0)
  })
})
