import { describe, expect, it } from 'vitest'
import { deriveCalendarFixture } from './derive'
import type { ReviewEventEntry } from '../../api/types'

const NOW = new Date(2026, 5, 11, 12, 0, 0) // 2026-06-11 local noon

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

describe('deriveCalendarFixture', () => {
  it('reports the current month + today, no selected day', () => {
    const fx = deriveCalendarFixture([], NOW)
    expect(fx.year).toBe(2026)
    expect(fx.month).toBe(5) // June, 0-indexed
    expect(fx.today).toBe(11)
    expect(fx.selectedDay).toBeNull()
    expect(fx.activity).toEqual({})
  })

  it('aggregates events by day-of-month within the current month', () => {
    const fx = deriveCalendarFixture(
      [
        event(new Date(2026, 5, 3, 9)),
        event(new Date(2026, 5, 3, 18)),
        event(new Date(2026, 5, 11, 8)),
      ],
      NOW,
    )
    expect(fx.activity).toEqual({ 3: 2, 11: 1 })
  })

  it('excludes events outside the current month', () => {
    const fx = deriveCalendarFixture(
      [
        event(new Date(2026, 4, 30, 9)), // May
        event(new Date(2026, 6, 1, 9)), // July
        event(new Date(2025, 5, 11, 9)), // prior year June
        event(new Date(2026, 5, 7, 9)), // June — counted
      ],
      NOW,
    )
    expect(fx.activity).toEqual({ 7: 1 })
  })

  it('ignores unparseable reviewed_at', () => {
    const bad: ReviewEventEntry = { ...event(new Date(2026, 5, 5)), reviewed_at: 'not-a-date' }
    const fx = deriveCalendarFixture([bad, event(new Date(2026, 5, 5))], NOW)
    expect(fx.activity).toEqual({ 5: 1 })
  })
})
