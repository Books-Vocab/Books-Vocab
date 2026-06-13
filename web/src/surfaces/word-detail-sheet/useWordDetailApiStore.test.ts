import { describe, expect, it } from 'vitest'
import { toWordDetail } from './useWordDetailApiStore'
import type { CardLinkSummaryResponse, CardResponse } from '../../api/types'

function link(partial: Partial<CardLinkSummaryResponse> & { id: string; word: string; kind: string }): CardLinkSummaryResponse {
  return {
    cardId: 'c-1',
    label: '相似用法',
    confidence: 0.8,
    reason: '語意重疊',
    hidden: false,
    ...partial,
  }
}

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
    inflections: partial.inflections ?? [],
    linksByKind: partial.linksByKind ?? {},
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

describe('toWordDetail', () => {
  it('carries full card content (collocations / inflections / difficultyTier)', () => {
    const d = toWordDetail(
      makeCard({
        content: 'ephemeral',
        meaning: '短暫的',
        pos: 'adj',
        difficultyTier: 'advanced',
        note: '轉瞬即逝',
        collocations: ['ephemeral nature', 'ephemeral pleasure'],
        examples: ['The ephemeral beauty of cherry blossoms.'],
        inflections: ['ephemerally'],
      }),
    )
    expect(d.word).toBe('ephemeral')
    expect(d.pos).toBe('adj')
    expect(d.difficultyTier).toBe('advanced')
    expect(d.note).toBe('轉瞬即逝')
    expect(d.collocations).toEqual(['ephemeral nature', 'ephemeral pleasure'])
    expect(d.examples).toEqual(['The ephemeral beauty of cherry blossoms.'])
    expect(d.inflections).toEqual(['ephemerally'])
  })

  it('groups linksByKind, sorts by kind, drops hidden links', () => {
    const d = toWordDetail(
      makeCard({
        content: 'forestall',
        meaning: '預先阻止',
        linksByKind: {
          synonym: [link({ id: 'l1', word: 'preempt', kind: 'synonym' })],
          antonym: [
            link({ id: 'l2', word: 'allow', kind: 'antonym' }),
            link({ id: 'l3', word: 'hiddenword', kind: 'antonym', hidden: true }),
          ],
        },
      }),
    )
    expect(d.linkGroups.map((g) => g.kind)).toEqual(['antonym', 'synonym'])
    // hidden link filtered out
    expect(d.linkGroups[0].links.map((l) => l.word)).toEqual(['allow'])
  })

  it('drops empty link groups (all hidden)', () => {
    const d = toWordDetail(
      makeCard({
        content: 'terse',
        meaning: '簡潔的',
        linksByKind: {
          synonym: [link({ id: 'l1', word: 'x', kind: 'synonym', hidden: true })],
        },
      }),
    )
    expect(d.linkGroups).toEqual([])
  })

  it('handles a minimal card (no links / collocations)', () => {
    const d = toWordDetail(makeCard({ content: 'word', meaning: '詞' }))
    expect(d.linkGroups).toEqual([])
    expect(d.collocations).toEqual([])
    expect(d.inflections).toEqual([])
  })
})
