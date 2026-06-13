import { describe, expect, it } from 'vitest'
import { findLinkSummary } from './useLinkReasonApiStore'
import type { CardLinkSummaryResponse, CardResponse } from '../../api/types'

function link(id: string, kind: string, word: string): CardLinkSummaryResponse {
  return { id, cardId: 'c1', word, kind, label: '相似用法', confidence: 0.8, reason: `${word} 的理由`, hidden: false }
}

function makeCard(linksByKind: Record<string, CardLinkSummaryResponse[]>): CardResponse {
  return {
    id: 'c1',
    content: 'forestall',
    meaning: '預先阻止',
    pos: null,
    difficulty: null,
    difficultyTier: null,
    note: null,
    collocations: [],
    examples: [],
    mode: 'recognition',
    isDeleted: false,
    isArchived: false,
    inflections: [],
    linksByKind,
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

describe('findLinkSummary', () => {
  const card = makeCard({
    synonym: [link('l1', 'synonym', 'preempt')],
    antonym: [link('l2', 'antonym', 'allow')],
  })

  it('finds a link across kind groups', () => {
    expect(findLinkSummary(card, 'l2')?.word).toBe('allow')
  })

  it('returns null when no link matches', () => {
    expect(findLinkSummary(card, 'nope')).toBeNull()
  })
})
