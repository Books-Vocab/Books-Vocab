import type { ScenarioId } from '../../harness/scenarios'

/**
 * Word Detail · Card Document fixtures — iOS WordDetailScenarios.swift
 * richDocument()/minimalDocument()（經 CardDocumentBuilder.build）的 web 鏡像資料。
 *
 * block 順序由 builder 決定：
 *   Full / Compact (richDocument): hero → example → divider → meaning(title+explanation)
 *                                   → divider → collocations → divider → source
 *   No example / collocations (minimalDocument): hero → divider → source
 *     （example 空 → skip；explanation nil → meaning 空 → skip；collocations 空 → skip）
 */

export interface WordDetailCardFixture {
  /** compact=true → blockPadding 0、block 間距 24（foldSectionSpacing）、divider 無 h padding、meaning 3 行截斷 */
  compact: boolean
  hero: { word: string; partOfSpeech: string | null; difficultyTier: string | null }
  /** example block（CardDocumentExampleBlock，serif italic 22）。null = 無 example block */
  example: string | null
  /** meaning block。null = 無 meaning block */
  meaning: { title: string; paragraphs: string[] } | null
  /** collocations pills。空陣列 = 無 collocations block */
  collocations: string[]
  source: { bookTitle: string; chapterTitle: string | null }
}

export const WORD_DETAIL_CARD_FIXTURES: Record<
  ScenarioId<'word-detail-card'>,
  WordDetailCardFixture
> = {
  full: {
    compact: false,
    hero: { word: 'ephemeral', partOfSpeech: 'adj.', difficultyTier: 'advanced' },
    example: 'The ephemeral beauty of cherry blossoms draws crowds each spring.',
    meaning: {
      title: '短暫的；轉瞬即逝的',
      paragraphs: [
        'Lasting for a very short time; describes things that fade quickly, often with a wistful, literary tone.',
      ],
    },
    collocations: ['ephemeral nature', 'ephemeral pleasure'],
    source: { bookTitle: 'On Writing Well', chapterTitle: 'Chapter 3 · Simplicity' },
  },
  compact: {
    compact: true,
    hero: { word: 'ephemeral', partOfSpeech: 'adj.', difficultyTier: 'advanced' },
    example: 'The ephemeral beauty of cherry blossoms draws crowds each spring.',
    meaning: {
      title: '短暫的；轉瞬即逝的',
      paragraphs: [
        'Lasting for a very short time; describes things that fade quickly, often with a wistful, literary tone.',
      ],
    },
    collocations: ['ephemeral nature', 'ephemeral pleasure'],
    source: { bookTitle: 'On Writing Well', chapterTitle: 'Chapter 3 · Simplicity' },
  },
  'no-example': {
    compact: false,
    hero: { word: 'terse', partOfSpeech: 'adj.', difficultyTier: null },
    example: null,
    meaning: null,
    collocations: [],
    source: { bookTitle: 'Sample Book', chapterTitle: null },
  },
}
