import { describe, expect, it } from 'vitest'
import { toVocabRow } from './useVocabApiStore'
import type { CardResponse } from '../../api/types'

function makeCard(partial: Partial<CardResponse> & { content: string; meaning: string }): CardResponse {
  const pos = partial.hasOwnProperty('pos') ? partial.pos : 'n'
  return {
    id: 'c-1',
    content: partial.content,
    meaning: partial.meaning,
    pos: pos ?? null,
    difficulty: null,
    difficultyTier: null,
    note: partial.note ?? null,
    collocations: [],
    examples: partial.examples ?? [],
    mode: 'recognition',
    isDeleted: false,
    isArchived: false,
    inflections: [],
    linksByKind: {},
    notebookId: 'nb-1',
    source: null,
    updatedAt: null,
    reviewIntervalHours: 12,
    nextReviewAt: partial.nextReviewAt ?? null,
    lastReviewedAt: null,
    reviewCount: partial.reviewCount ?? 0,
    lapseCount: 0,
    reviewStreak: 0,
    lastReviewFeedback: -1,
  }
}

describe('toVocabRow', () => {
  it('maps unlearned card (reviewCount=0) with first-round detail', () => {
    const card = makeCard({ content: 'ephemeral', meaning: '短暫的', pos: 'adj', reviewCount: 0 })
    const row = toVocabRow(card)
    expect(row.word).toBe('ephemeral')
    expect(row.translation).toBe('短暫的')
    expect(row.partOfSpeech).toBe('adj.')
    expect(row.reviewState).toBe('unlearned')
    expect(row.detail).toBe('首輪 12h')
  })

  it('maps due card when nextReviewAt is in the past', () => {
    const yesterday = new Date(Date.now() - 86400_000).toISOString()
    const card = makeCard({ content: 'serendipity', meaning: '機緣巧合', reviewCount: 1, nextReviewAt: yesterday })
    const row = toVocabRow(card)
    expect(row.reviewState).toBe('due')
    expect(row.detail).toBe('待複習')
  })

  it('maps reviewed card when nextReviewAt is in the future', () => {
    const tomorrow = new Date(Date.now() + 86400_000).toISOString()
    const card = makeCard({ content: 'meticulous', meaning: '一絲不苟的', reviewCount: 3, nextReviewAt: tomorrow })
    const row = toVocabRow(card)
    expect(row.reviewState).toBe('reviewed')
  })

  it('handles empty pos by returning empty string', () => {
    const card = makeCard({ content: 'word', meaning: '詞', pos: null })
    const row = toVocabRow(card)
    expect(row.partOfSpeech).toBe('')
  })

  it('uses note for explanation and first example', () => {
    const card = makeCard({
      content: 'ubiquitous',
      meaning: '無所不在的',
      note: '形容某事物到處都有',
      examples: ['In coastal towns the smell of salt is ubiquitous.'],
    })
    const row = toVocabRow(card)
    expect(row.expansion.explanation).toBe('形容某事物到處都有')
    expect(row.expansion.example).toBe('In coastal towns the smell of salt is ubiquitous.')
  })
})
