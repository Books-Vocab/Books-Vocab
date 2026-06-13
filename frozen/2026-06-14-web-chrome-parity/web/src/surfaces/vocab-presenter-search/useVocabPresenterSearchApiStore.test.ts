import { describe, expect, it } from 'vitest'
import {
  classify,
  classifyCounts,
  searchAndSort,
  toSearchRow,
} from './useVocabPresenterSearchApiStore'
import type { SearchRow } from './useVocabPresenterSearchApiStore'
import type { CardResponse } from '../../api/types'

function makeCard(
  partial: Partial<CardResponse> & { content: string; meaning: string },
): CardResponse {
  return {
    id: `c-${partial.content}`,
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
    reviewIntervalHours: partial.reviewIntervalHours ?? 12,
    nextReviewAt: partial.nextReviewAt ?? null,
    lastReviewedAt: null,
    reviewCount: partial.reviewCount ?? 0,
    lapseCount: 0,
    reviewStreak: 0,
    lastReviewFeedback: -1,
  }
}

const NOW = new Date('2026-06-13T12:00:00Z')

describe('classify', () => {
  it('returns unlearned when never reviewed', () => {
    expect(classify(makeCard({ content: 'a', meaning: 'x', reviewCount: 0 }), NOW)).toBe('unlearned')
  })

  it('returns due when reviewed and next review is past (or null)', () => {
    expect(
      classify(
        makeCard({ content: 'a', meaning: 'x', reviewCount: 2, nextReviewAt: '2026-06-13T11:00:00Z' }),
        NOW,
      ),
    ).toBe('due')
    expect(
      classify(makeCard({ content: 'a', meaning: 'x', reviewCount: 2, nextReviewAt: null }), NOW),
    ).toBe('due')
  })

  it('returns reviewed when next review is in the future', () => {
    expect(
      classify(
        makeCard({ content: 'a', meaning: 'x', reviewCount: 2, nextReviewAt: '2026-06-14T11:00:00Z' }),
        NOW,
      ),
    ).toBe('reviewed')
  })
})

describe('toSearchRow', () => {
  it('formats detailLabel per review state', () => {
    const unlearned = toSearchRow(
      makeCard({ content: 'serendipity', meaning: '機緣巧合', pos: 'n', reviewIntervalHours: 12 }),
      NOW,
    )
    expect(unlearned).toMatchObject({
      word: 'serendipity',
      partOfSpeech: 'n.',
      translation: '機緣巧合',
      detailLabel: '首輪 12h',
      reviewState: 'unlearned',
    })
    const due = toSearchRow(
      makeCard({ content: 'a', meaning: 'x', reviewCount: 1, nextReviewAt: '2026-06-13T11:00:00Z' }),
      NOW,
    )
    expect(due.detailLabel).toBe('待複習')
  })

  it('omits pos suffix when absent', () => {
    expect(toSearchRow(makeCard({ content: 'a', meaning: 'x' }), NOW).partOfSpeech).toBe('')
  })
})

const ROWS: SearchRow[] = [
  { word: 'meticulous', partOfSpeech: 'adj.', translation: '一絲不苟的', detailLabel: '首輪 12h', reviewState: 'unlearned' },
  { word: 'ingenious', partOfSpeech: 'adj.', translation: '巧妙的', detailLabel: '待複習', reviewState: 'due' },
  { word: 'tenacious', partOfSpeech: 'adj.', translation: '堅韌不拔的', detailLabel: '6月14日', reviewState: 'reviewed' },
  { word: 'serendipity', partOfSpeech: 'n.', translation: '機緣巧合', detailLabel: '首輪 12h', reviewState: 'unlearned' },
]

describe('searchAndSort', () => {
  it('filters by query (word or translation, case-insensitive)', () => {
    expect(searchAndSort(ROWS, 'OUS', null, 'reviewPriority').map((r) => r.word)).toEqual([
      'ingenious',
      'meticulous',
      'tenacious',
    ])
    expect(searchAndSort(ROWS, '機緣', null, 'reviewPriority').map((r) => r.word)).toEqual([
      'serendipity',
    ])
  })

  it('filters by review-state chip', () => {
    expect(searchAndSort(ROWS, '', 'unlearned', 'alphabetical').map((r) => r.word)).toEqual([
      'meticulous',
      'serendipity',
    ])
  })

  it('review-priority sort orders due < unlearned < reviewed then alphabetical', () => {
    expect(searchAndSort(ROWS, '', null, 'reviewPriority').map((r) => r.word)).toEqual([
      'ingenious', // due
      'meticulous', // unlearned
      'serendipity', // unlearned
      'tenacious', // reviewed
    ])
  })

  it('alphabetical sort orders strictly by word', () => {
    expect(searchAndSort(ROWS, '', null, 'alphabetical').map((r) => r.word)).toEqual([
      'ingenious',
      'meticulous',
      'serendipity',
      'tenacious',
    ])
  })

  it('returns [] when query matches nothing', () => {
    expect(searchAndSort(ROWS, 'zzzznotaword', null, 'reviewPriority')).toEqual([])
  })
})

describe('classifyCounts', () => {
  it('counts each review state over the full set (ignores query/filter)', () => {
    expect(classifyCounts(ROWS)).toEqual({ unlearned: 2, due: 1, reviewed: 1 })
  })
})
