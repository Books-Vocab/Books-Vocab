import { describe, expect, it } from 'vitest'
import type { PodcastProgressListResponse, PodcastSeriesSummary } from '../../api/types'
import { buildContinueShelf, indexCatalog, isCompleted } from './continueShelf'

const CATALOG: PodcastSeriesSummary[] = [
  {
    id: 'atomic',
    title: 'Atomic Habits Unpacked',
    episodes: [
      { ep_num: 1, title: 'The Aggregation of Marginal Gains' },
      { ep_num: 2, title: 'Identity-Based Habits' },
    ],
  },
  {
    id: 'flow',
    title: 'Finding Flow',
    episodes: [{ ep_num: 1, title: 'What Is Flow' }],
  },
]

const PROGRESS: PodcastProgressListResponse = {
  items: [
    // earlier updated
    { series_id: 'atomic', ep_num: 2, position_sec: 612, duration_sec: 1832, updated_at: '2026-06-10T00:00:00Z' },
    // later updated → should sort first
    { series_id: 'flow', ep_num: 1, position_sec: 300, duration_sec: 1500, updated_at: '2026-06-11T00:00:00Z' },
    // completed → filtered out
    { series_id: 'atomic', ep_num: 1, position_sec: 1832, duration_sec: 1832, updated_at: '2026-06-09T00:00:00Z' },
  ],
}

describe('isCompleted', () => {
  it('true at/over duration, false otherwise', () => {
    expect(isCompleted({ series_id: 'x', ep_num: 1, position_sec: 1832, duration_sec: 1832, updated_at: '' })).toBe(true)
    expect(isCompleted({ series_id: 'x', ep_num: 1, position_sec: 600, duration_sec: 1832, updated_at: '' })).toBe(false)
    expect(isCompleted({ series_id: 'x', ep_num: 1, position_sec: 0, duration_sec: 0, updated_at: '' })).toBe(false)
  })
})

describe('buildContinueShelf', () => {
  const shelf = buildContinueShelf(PROGRESS, indexCatalog(CATALOG))

  it('drops completed rows', () => {
    expect(shelf).toHaveLength(2)
    expect(shelf.find((i) => i.seriesId === 'atomic' && i.epNum === 1)).toBeUndefined()
  })

  it('sorts by updated_at desc (most recent first)', () => {
    expect(shelf[0].seriesId).toBe('flow')
    expect(shelf[1].seriesId).toBe('atomic')
  })

  it('joins series + episode titles into the display string', () => {
    expect(shelf[0].seriesTitle).toBe('Finding Flow')
    expect(shelf[0].episodeDisplay).toBe('Ep 1 · What Is Flow')
    expect(shelf[1].episodeDisplay).toBe('Ep 2 · Identity-Based Habits')
  })

  it('computes fraction and remaining clock', () => {
    expect(shelf[1].fraction).toBeCloseTo(612 / 1832, 6)
    expect(shelf[1].remaining).toBe('還剩 20:20') // (1832-612)=1220s → 20:20
    expect(shelf[0].remaining).toBe('還剩 20:00') // (1500-300)=1200s → 20:00
  })

  it('degrades to the series id and bare Ep label when catalog lacks the entry', () => {
    const shelfNoCat = buildContinueShelf(
      { items: [{ series_id: 'ghost', ep_num: 3, position_sec: 10, duration_sec: 100, updated_at: '2026-01-01T00:00:00Z' }] },
      new Map(),
    )
    expect(shelfNoCat[0].seriesTitle).toBe('ghost')
    expect(shelfNoCat[0].episodeDisplay).toBe('Ep 3')
  })

  it('handles unknown duration without dividing by zero', () => {
    const shelfNoDur = buildContinueShelf(
      { items: [{ series_id: 'flow', ep_num: 1, position_sec: 10, duration_sec: 0, updated_at: '2026-01-01T00:00:00Z' }] },
      indexCatalog(CATALOG),
    )
    expect(shelfNoDur[0].fraction).toBe(0)
    expect(shelfNoDur[0].remaining).toBeNull()
  })
})

describe('indexCatalog', () => {
  it('keys by id and skips entries without one', () => {
    const map = indexCatalog([...CATALOG, { title: 'no id' }])
    expect(map.size).toBe(2)
    expect(map.get('atomic')?.title).toBe('Atomic Habits Unpacked')
  })
})
