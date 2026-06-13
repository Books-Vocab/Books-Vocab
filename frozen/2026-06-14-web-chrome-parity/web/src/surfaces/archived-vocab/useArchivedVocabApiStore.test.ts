import { describe, expect, it } from 'vitest'
import { toArchivedRows, toggleSelection } from './useArchivedVocabApiStore'
import type { CardResponse } from '../../api/types'

function makeCard(partial: Partial<CardResponse> & { content: string; meaning: string }): CardResponse {
  return {
    id: partial.content,
    content: partial.content,
    meaning: partial.meaning,
    pos: partial.pos ?? null,
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

describe('toArchivedRows', () => {
  it('keeps only archived, non-deleted cards, sorted by word', () => {
    const rows = toArchivedRows([
      makeCard({ content: 'serendipity', meaning: '機緣巧合', pos: 'n', isArchived: true }),
      makeCard({ content: 'active', meaning: '活躍的', isArchived: false }),
      makeCard({ content: 'ephemeral', meaning: '短暫的', pos: 'adj', isArchived: true }),
      makeCard({ content: 'gone', meaning: '已刪', isArchived: true, isDeleted: true }),
    ])
    expect(rows.map((r) => r.word)).toEqual(['ephemeral', 'serendipity'])
    expect(rows[0]).toEqual({ id: 'ephemeral', word: 'ephemeral', partOfSpeech: 'adj.', translation: '短暫的' })
  })

  it('maps null pos to null partOfSpeech', () => {
    const rows = toArchivedRows([makeCard({ content: 'x', meaning: '詞', pos: null, isArchived: true })])
    expect(rows[0].partOfSpeech).toBeNull()
  })
})

describe('toggleSelection', () => {
  it('adds an unselected word', () => {
    expect([...toggleSelection(new Set(), 'a')]).toEqual(['a'])
  })
  it('removes an already-selected word', () => {
    expect([...toggleSelection(new Set(['a', 'b']), 'a')]).toEqual(['b'])
  })
  it('does not mutate the input set', () => {
    const input = new Set(['a'])
    toggleSelection(input, 'b')
    expect([...input]).toEqual(['a'])
  })
})
