import { describe, expect, it } from 'vitest'
import { toVocabRow } from './useVocabApiStore'
import type { CardResponse } from '../../api/types'

describe('toVocabRow', () => {
  it('maps unlearned card (reviewCount=0) to fixture row', () => {
    const card: CardResponse = {
      id: 'c1',
      content: 'serendipity',
      meaning: '機緣巧合',
      pos: 'n',
      difficulty: null,
      difficultyTier: null,
      note: '意外發現美好事物的能力',
      collocations: [],
      examples: ['Finding that café was pure serendipity.'],
      mode: 'recognition',
      isDeleted: false,
      isArchived: false,
      inflections: [],
      linksByKind: {},
      notebookId: 'default',
      source: null,
      updatedAt: null,
      reviewIntervalHours: 12,
      nextReviewAt: '2026-06-12T00:00:00Z',
      lastReviewedAt: null,
      reviewCount: 0,
      lapseCount: 0,
      reviewStreak: 0,
      lastReviewFeedback: -1,
    }
    const row = toVocabRow(card)
    expect(row.word).toBe('serendipity')
    expect(row.translation).toBe('機緣巧合')
    expect(row.partOfSpeech).toBe('n.')
    expect(row.reviewState).toBe('unlearned')
    expect(row.detail).toBe('首輪 12h')
  })

  it('maps reviewed card with future nextReviewAt', () => {
    const future = new Date(Date.now() + 86400000).toISOString()
    const card: CardResponse = {
      id: 'c2',
      content: 'ephemeral',
      meaning: '短暫的',
      pos: 'adj',
      difficulty: null,
      difficultyTier: 'intermediate',
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
      reviewIntervalHours: 24,
      nextReviewAt: future,
      lastReviewedAt: new Date().toISOString(),
      reviewCount: 1,
      lapseCount: 0,
      reviewStreak: 1,
      lastReviewFeedback: 1,
    }
    const row = toVocabRow(card)
    expect(row.reviewState).toBe('reviewed')
  })

  it('maps due card with past nextReviewAt', () => {
    const past = new Date(Date.now() - 86400000).toISOString()
    const card: CardResponse = {
      id: 'c3',
      content: 'petrichor',
      meaning: '雨後泥土香',
      pos: 'n',
      difficulty: null,
      difficultyTier: null,
      note: null,
      collocations: [],
      examples: [],
      mode: 'production',
      isDeleted: false,
      isArchived: false,
      inflections: [],
      linksByKind: {},
      notebookId: 'default',
      source: null,
      updatedAt: null,
      reviewIntervalHours: 12,
      nextReviewAt: past,
      lastReviewedAt: '2026-06-10T00:00:00Z',
      reviewCount: 2,
      lapseCount: 0,
      reviewStreak: 2,
      lastReviewFeedback: 1,
    }
    const row = toVocabRow(card)
    expect(row.reviewState).toBe('due')
    expect(row.detail).toBe('待複習')
    expect(row.word).toBe('petrichor')
  })
})
