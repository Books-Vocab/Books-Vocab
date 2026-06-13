import { describe, expect, it } from 'vitest'
import type { CardResponse, GraphLinkResponse } from '../../api/types'
import { cardReviewRatio, hasLinks, toGraphFromApi } from './graphData'

function makeCard(
  partial: Partial<CardResponse> & { id: string; content: string },
): CardResponse {
  return {
    meaning: '',
    pos: null,
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
    updatedAt: null,
    reviewIntervalHours: 12,
    nextReviewAt: null,
    lastReviewedAt: null,
    reviewCount: 0,
    lapseCount: 0,
    reviewStreak: 0,
    lastReviewFeedback: -1,
    ...partial,
  }
}

function link(fromId: string, toId: string, id = `${fromId}-${toId}`): GraphLinkResponse {
  return { id, fromId, toId, kind: 'related', confidence: 0.7, reason: '' }
}

describe('cardReviewRatio', () => {
  const start = Date.parse('2026-01-01T00:00:00Z')
  const interval = 12 * 3_600_000 // 12h in ms
  const next = start + interval

  it('returns 0 at the review start (safe band)', () => {
    const c = makeCard({ id: 'a', content: 'a', lastReviewedAt: new Date(start).toISOString(), nextReviewAt: new Date(next).toISOString(), reviewCount: 1 })
    expect(cardReviewRatio(c, start)).toBe(0)
  })

  it('returns ~1 exactly at the next-review time (due band)', () => {
    const c = makeCard({ id: 'a', content: 'a', lastReviewedAt: new Date(start).toISOString(), nextReviewAt: new Date(next).toISOString(), reviewCount: 1 })
    expect(cardReviewRatio(c, next)).toBeCloseTo(1)
  })

  it('returns > 1 past the next-review time (overdue band)', () => {
    const c = makeCard({ id: 'a', content: 'a', lastReviewedAt: new Date(start).toISOString(), nextReviewAt: new Date(next).toISOString(), reviewCount: 1 })
    expect(cardReviewRatio(c, next + interval)).toBeCloseTo(2)
  })

  it('falls back to updatedAt when lastReviewedAt is null', () => {
    const c = makeCard({ id: 'a', content: 'a', updatedAt: new Date(start).toISOString(), nextReviewAt: new Date(next).toISOString(), reviewCount: 1 })
    expect(cardReviewRatio(c, next)).toBeCloseTo(1)
  })

  it('returns 0 when timestamps are missing', () => {
    expect(cardReviewRatio(makeCard({ id: 'a', content: 'a' }), start)).toBe(0)
  })

  it('never returns negative for a future start', () => {
    const c = makeCard({ id: 'a', content: 'a', lastReviewedAt: new Date(start).toISOString(), nextReviewAt: new Date(next).toISOString(), reviewCount: 1 })
    expect(cardReviewRatio(c, start - interval)).toBe(0)
  })
})

describe('toGraphFromApi', () => {
  it('maps reviewCount===0 cards to unlearned (null ratio) and >0 to learned', () => {
    const g = toGraphFromApi(
      [
        makeCard({ id: 'a', content: 'alpha', reviewCount: 0 }),
        makeCard({ id: 'b', content: 'bravo', reviewCount: 3, lastReviewedAt: '2026-01-01T00:00:00Z', nextReviewAt: '2026-01-01T12:00:00Z' }),
      ],
      [],
    )
    const a = g.nodes.find((n) => n.id === 'a')!
    const b = g.nodes.find((n) => n.id === 'b')!
    expect(a.learned).toBe(false)
    expect(a.reviewRatio).toBeNull()
    expect(b.learned).toBe(true)
    expect(b.reviewRatio).not.toBeNull()
  })

  it('excludes archived and deleted cards (iOS node rule)', () => {
    const g = toGraphFromApi(
      [
        makeCard({ id: 'a', content: 'alpha' }),
        makeCard({ id: 'b', content: 'bravo', isArchived: true }),
        makeCard({ id: 'c', content: 'charlie', isDeleted: true }),
      ],
      [],
    )
    expect(g.nodes.map((n) => n.id)).toEqual(['a'])
  })

  it('keeps an edge only when both endpoints survive as nodes', () => {
    const g = toGraphFromApi(
      [makeCard({ id: 'a', content: 'a' }), makeCard({ id: 'b', content: 'b' })],
      [link('a', 'b'), link('a', 'ghost'), link('archived', 'b')],
    )
    expect(g.links).toEqual([{ source: 'a', target: 'b' }])
  })

  it('drops an edge whose endpoint was archived out', () => {
    const g = toGraphFromApi(
      [makeCard({ id: 'a', content: 'a' }), makeCard({ id: 'b', content: 'b', isArchived: true })],
      [link('a', 'b')],
    )
    expect(g.links).toEqual([])
    expect(hasLinks(g)).toBe(false)
  })

  it('undirected-dedupes a pair linked twice', () => {
    const g = toGraphFromApi(
      [makeCard({ id: 'a', content: 'a' }), makeCard({ id: 'b', content: 'b' })],
      [link('a', 'b', 'l1'), link('b', 'a', 'l2')],
    )
    expect(g.links).toHaveLength(1)
  })

  it('uses card.content as the node word', () => {
    const g = toGraphFromApi([makeCard({ id: 'a', content: 'ephemeral' })], [])
    expect(g.nodes[0].word).toBe('ephemeral')
  })
})
