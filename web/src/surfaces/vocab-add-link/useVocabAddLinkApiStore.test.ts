import { describe, expect, it } from 'vitest'
import { filterCandidates } from './useVocabAddLinkApiStore'
import type { CardResponse } from '../../api/types'

function makeCard(partial: Partial<CardResponse> & { id: string; content: string; meaning: string }): CardResponse {
  return {
    id: partial.id,
    content: partial.content,
    meaning: partial.meaning,
    pos: null,
    difficulty: null,
    difficultyTier: null,
    note: null,
    collocations: [],
    examples: [],
    mode: 'recognition',
    isDeleted: partial.isDeleted ?? false,
    isArchived: partial.isArchived ?? false,
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

const CARDS = [
  makeCard({ id: 'c1', content: 'serendipity', meaning: '機緣巧合' }),
  makeCard({ id: 'c2', content: 'ephemeral', meaning: '短暫的' }),
  makeCard({ id: 'c3', content: 'meticulous', meaning: '一絲不苟的' }),
  makeCard({ id: 'c4', content: 'archived-one', meaning: '已封存', isArchived: true }),
]

describe('filterCandidates', () => {
  it('returns [] for an empty query (mirrors iOS empty-state)', () => {
    expect(filterCandidates(CARDS, 'serendipity', '')).toEqual([])
    expect(filterCandidates(CARDS, 'serendipity', '   ')).toEqual([])
  })

  it('matches by word case-insensitively and excludes the source card', () => {
    const out = filterCandidates(CARDS, 'serendipity', 'E')
    expect(out.map((c) => c.word)).toEqual(['ephemeral', 'meticulous'])
  })

  it('matches by translation', () => {
    const out = filterCandidates(CARDS, 'meticulous', '機緣')
    expect(out.map((c) => c.word)).toEqual(['serendipity'])
  })

  it('excludes archived candidates', () => {
    const out = filterCandidates(CARDS, 'serendipity', 'archived')
    expect(out).toEqual([])
  })

  it('maps to id/word/translation rows', () => {
    const out = filterCandidates(CARDS, 'ephemeral', 'serendipity')
    expect(out).toEqual([{ id: 'c1', word: 'serendipity', translation: '機緣巧合' }])
  })
})
