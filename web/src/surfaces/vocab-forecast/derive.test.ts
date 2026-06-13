import { describe, expect, it } from 'vitest'
import { deriveForecastBuckets } from './derive'
import type { CardResponse } from '../../api/types'

const NOW = new Date(2026, 5, 11, 12, 0, 0) // 2026-06-11 local noon

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

// build a local-time nextReviewAt for "offset" days from NOW
function nextIn(days: number): string {
  const d = new Date(NOW)
  d.setDate(d.getDate() + days)
  d.setHours(9, 0, 0, 0)
  return d.toISOString()
}

describe('deriveForecastBuckets', () => {
  it('produces forecastDays buckets labelled +{i}d', () => {
    const buckets = deriveForecastBuckets([], 14, NOW)
    expect(buckets).toHaveLength(14)
    expect(buckets[0]!.label).toBe('+0d')
    expect(buckets[13]!.label).toBe('+13d')
    expect(buckets.every((b) => b.count === 0)).toBe(true)
  })

  it('buckets cards by nextReviewAt day offset', () => {
    const buckets = deriveForecastBuckets(
      [
        card({ id: '1', content: 'a', reviewCount: 1, nextReviewAt: nextIn(2) }),
        card({ id: '2', content: 'b', reviewCount: 1, nextReviewAt: nextIn(2) }),
        card({ id: '3', content: 'c', reviewCount: 1, nextReviewAt: nextIn(5) }),
      ],
      14,
      NOW,
    )
    expect(buckets[2]!.count).toBe(2)
    expect(buckets[5]!.count).toBe(1)
  })

  it('folds overdue (nextReviewAt <= today) into the today bucket', () => {
    const buckets = deriveForecastBuckets(
      [
        card({ id: '1', content: 'a', reviewCount: 3, nextReviewAt: nextIn(-3) }),
        card({ id: '2', content: 'b', reviewCount: 1, nextReviewAt: nextIn(0) }),
      ],
      14,
      NOW,
    )
    expect(buckets[0]!.count).toBe(2)
  })

  it('treats unlearned cards (null nextReviewAt) as due today', () => {
    const buckets = deriveForecastBuckets([card({ id: '1', content: 'a' })], 14, NOW)
    expect(buckets[0]!.count).toBe(1)
  })

  it('excludes archived and deleted cards', () => {
    const buckets = deriveForecastBuckets(
      [
        card({ id: '1', content: 'a', isArchived: true }),
        card({ id: '2', content: 'b', isDeleted: true }),
      ],
      14,
      NOW,
    )
    expect(buckets.every((b) => b.count === 0)).toBe(true)
  })

  it('drops cards whose nextReviewAt is past the forecast window', () => {
    const buckets = deriveForecastBuckets(
      [card({ id: '1', content: 'a', reviewCount: 1, nextReviewAt: nextIn(30) })],
      14,
      NOW,
    )
    expect(buckets.every((b) => b.count === 0)).toBe(true)
  })
})
