import { describe, expect, it } from 'vitest'
import { toCardFixture } from './useWordDetailCardApiStore'
import type { CardResponse } from '../../api/types'

function makeCard(partial: Partial<CardResponse> & { content: string; meaning: string }): CardResponse {
  return {
    id: 'c-1',
    content: partial.content,
    meaning: partial.meaning,
    pos: partial.pos ?? null,
    difficulty: null,
    difficultyTier: partial.difficultyTier ?? null,
    note: partial.note ?? null,
    collocations: partial.collocations ?? [],
    examples: partial.examples ?? [],
    mode: 'recognition',
    isDeleted: false,
    isArchived: false,
    inflections: [],
    linksByKind: {},
    notebookId: 'default',
    source: partial.source ?? null,
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

describe('toCardFixture', () => {
  it('maps a rich card into hero/example/meaning/collocations blocks', () => {
    const fx = toCardFixture(
      makeCard({
        content: 'ephemeral',
        meaning: '短暫的',
        pos: 'adj',
        difficultyTier: 'advanced',
        note: '轉瞬即逝',
        collocations: ['ephemeral nature'],
        examples: ['The ephemeral beauty.'],
        source: 'reader',
      }),
    )
    expect(fx.hero).toEqual({ word: 'ephemeral', partOfSpeech: 'adj.', difficultyTier: 'advanced' })
    expect(fx.example).toBe('The ephemeral beauty.')
    expect(fx.meaning).toEqual({ title: '短暫的', paragraphs: ['轉瞬即逝'] })
    expect(fx.collocations).toEqual(['ephemeral nature'])
    expect(fx.source).toEqual({ bookTitle: 'reader', chapterTitle: null })
  })

  it('drops example/note paragraph when absent', () => {
    const fx = toCardFixture(makeCard({ content: 'terse', meaning: '簡潔的', pos: null }))
    expect(fx.hero.partOfSpeech).toBeNull()
    expect(fx.example).toBeNull()
    expect(fx.meaning).toEqual({ title: '簡潔的', paragraphs: [] })
    expect(fx.collocations).toEqual([])
    expect(fx.source.bookTitle).toBe('單字庫')
  })
})
