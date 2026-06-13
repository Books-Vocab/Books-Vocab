import { describe, expect, it } from 'vitest'
import { deriveReviewBannerCounts } from './derive'
import type { CardResponse } from '../../api/types'

const NOW = new Date('2026-06-11T12:00:00Z')

function card(partial: Partial<CardResponse> & Pick<CardResponse, 'id' | 'content'>): CardResponse {
  return {
    meaning: 'x',
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

describe('deriveReviewBannerCounts', () => {
  it('counts reviewCount==0 as unlearned', () => {
    const cards = [card({ id: '1', content: 'a' }), card({ id: '2', content: 'b' })]
    expect(deriveReviewBannerCounts(cards, NOW)).toEqual({ dueCount: 0, unlearnedCount: 2 })
  })

  it('counts learned-and-expired (reviewCount>0 && nextReviewAt<=now) as due', () => {
    const cards = [
      card({ id: '1', content: 'a', reviewCount: 3, nextReviewAt: '2026-06-10T00:00:00Z' }),
      card({ id: '2', content: 'b', reviewCount: 1, nextReviewAt: '2026-06-11T12:00:00Z' }), // exactly now → due
    ]
    expect(deriveReviewBannerCounts(cards, NOW)).toEqual({ dueCount: 2, unlearnedCount: 0 })
  })

  it('excludes learned-but-not-yet-due cards from both buckets', () => {
    const cards = [
      card({ id: '1', content: 'a', reviewCount: 2, nextReviewAt: '2026-06-20T00:00:00Z' }),
    ]
    expect(deriveReviewBannerCounts(cards, NOW)).toEqual({ dueCount: 0, unlearnedCount: 0 })
  })

  it('treats learned card with null nextReviewAt as due (now fallback)', () => {
    const cards = [card({ id: '1', content: 'a', reviewCount: 5, nextReviewAt: null })]
    expect(deriveReviewBannerCounts(cards, NOW)).toEqual({ dueCount: 1, unlearnedCount: 0 })
  })

  it('excludes archived and deleted cards', () => {
    const cards = [
      card({ id: '1', content: 'a', isArchived: true }),
      card({ id: '2', content: 'b', isDeleted: true, reviewCount: 3, nextReviewAt: '2026-06-01T00:00:00Z' }),
      card({ id: '3', content: 'c' }),
    ]
    expect(deriveReviewBannerCounts(cards, NOW)).toEqual({ dueCount: 0, unlearnedCount: 1 })
  })

  it('mixes due + unlearned', () => {
    const cards = [
      card({ id: '1', content: 'a' }),
      card({ id: '2', content: 'b' }),
      card({ id: '3', content: 'c', reviewCount: 1, nextReviewAt: '2026-06-01T00:00:00Z' }),
    ]
    expect(deriveReviewBannerCounts(cards, NOW)).toEqual({ dueCount: 1, unlearnedCount: 2 })
  })
})
