import { describe, expect, it } from 'vitest'
import { buildContentPatch, draftFromCard } from './useWordEditApiStore'
import type { CardResponse } from '../../api/types'

function makeCard(partial: Partial<CardResponse> & { content: string; meaning: string }): CardResponse {
  return {
    id: 'c-1',
    content: partial.content,
    meaning: partial.meaning,
    pos: null,
    difficulty: null,
    difficultyTier: null,
    note: partial.note ?? null,
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
  }
}

describe('draftFromCard', () => {
  it('lifts meaning + note into the two-field draft', () => {
    const d = draftFromCard(makeCard({ content: 'serendipity', meaning: '機緣巧合', note: '無心插柳' }))
    expect(d).toEqual({ meaning: '機緣巧合', explanation: '無心插柳' })
  })

  it('maps null note to empty explanation', () => {
    const d = draftFromCard(makeCard({ content: 'terse', meaning: '簡潔的', note: null }))
    expect(d.explanation).toBe('')
  })
})

describe('buildContentPatch', () => {
  const orig = { meaning: '機緣巧合', explanation: '無心插柳' }

  it('sends only the changed meaning', () => {
    expect(buildContentPatch(orig, { meaning: '巧合', explanation: '無心插柳' })).toEqual({ meaning: '巧合' })
  })

  it('routes explanation changes to patch.note', () => {
    expect(buildContentPatch(orig, { meaning: '機緣巧合', explanation: '新筆記' })).toEqual({ note: '新筆記' })
  })

  it('sends both when both changed', () => {
    expect(buildContentPatch(orig, { meaning: 'X', explanation: 'Y' })).toEqual({ meaning: 'X', note: 'Y' })
  })

  it('produces an empty patch when nothing changed', () => {
    expect(buildContentPatch(orig, { ...orig })).toEqual({})
  })
})
