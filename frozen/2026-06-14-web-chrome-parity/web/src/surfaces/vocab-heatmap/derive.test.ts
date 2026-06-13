import { describe, expect, it } from 'vitest'
import { deriveActivity, deriveThresholds, deriveHeatmapFixture } from './derive'
import type { ReviewEventEntry } from '../../api/types'

function event(reviewedAt: Date): ReviewEventEntry {
  const iso = reviewedAt.toISOString()
  return {
    event_id: `evt-${iso}-${Math.random()}`,
    card_id: null,
    word_snapshot: 'w',
    notebook_id: 'default',
    feedback: 1,
    reviewed_at: iso,
    created_at: iso,
    is_synthetic: false,
  }
}

describe('deriveActivity', () => {
  it('aggregates events by local dayKey', () => {
    const a = deriveActivity([
      event(new Date(2026, 5, 3, 9)),
      event(new Date(2026, 5, 3, 18)),
      event(new Date(2026, 5, 4, 8)),
    ])
    expect(a['2026-06-03']).toBe(2)
    expect(a['2026-06-04']).toBe(1)
  })

  it('ignores unparseable reviewed_at', () => {
    const bad: ReviewEventEntry = { ...event(new Date(2026, 5, 5)), reviewed_at: 'bad' }
    expect(deriveActivity([bad])).toEqual({})
  })
})

describe('deriveThresholds', () => {
  it('falls back to [1,2,3] when fewer than 4 non-zero days', () => {
    expect(deriveThresholds({ a: 1, b: 5, c: 9 })).toEqual([1, 2, 3])
    expect(deriveThresholds({})).toEqual([1, 2, 3])
  })

  it('computes p25/p50/p75 with floor indices matching Swift integer division', () => {
    // sorted nonzero = [1,2,3,4,5,6,7,8]  (n=8) → idx 2,4,6 → [3,5,7]
    const activity = { a: 5, b: 2, c: 8, d: 1, e: 6, f: 3, g: 7, h: 4 }
    expect(deriveThresholds(activity)).toEqual([3, 5, 7])
  })

  it('excludes zero counts before computing thresholds', () => {
    // nonzero = [1,2,3,4] (n=4) → idx 1,2,3 → [2,3,4]
    const activity = { z1: 0, z2: 0, a: 4, b: 1, c: 3, d: 2 }
    expect(deriveThresholds(activity)).toEqual([2, 3, 4])
  })
})

describe('deriveHeatmapFixture', () => {
  it('returns activity + thresholds + 20 weeks', () => {
    const fx = deriveHeatmapFixture([event(new Date(2026, 5, 3))])
    expect(fx.weeks).toBe(20)
    expect(fx.thresholds).toEqual([1, 2, 3])
    expect(fx.activity['2026-06-03']).toBe(1)
  })
})
