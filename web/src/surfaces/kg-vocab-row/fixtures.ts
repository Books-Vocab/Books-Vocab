import type { ScenarioId } from '../../harness/scenarios'

/**
 * KGVocabRow fixtures — 對齊 iOS `KGVocabRowScenarios.swift` 的 Default / Highlighted。
 *
 * scene 注入全新 `VocabularyEntry`（unlearned），row 以
 *   wordRowViewData(showsReviewState:false, showsSourceContext:false,
 *                   showsDifficultyTier:false, showsReviewProgress:true)
 * 取資料 → 無 book/chapter、無 statusText、無 tier；trailing = unlearned 進度
 * （ratio:nil 分支）的 detailLabel「首輪 12h」（reviewIntervalHours.compactHourLabel）。
 */
export interface KGVocabRowFixture {
  word: string
  partOfSpeech: string
  translation: string
  /** unlearned ratio:nil → 只渲染 detailLabel 文字（「首輪 12h」） */
  detailLabel: string
  isHighlighted: boolean
}

export const KG_VOCAB_ROW_FIXTURES: Record<ScenarioId<'kg-vocab-row'>, KGVocabRowFixture> = {
  default: {
    word: 'meticulous',
    partOfSpeech: 'adj.',
    translation: '一絲不苟的；非常仔細的',
    detailLabel: '首輪 12h',
    isHighlighted: false,
  },
  highlighted: {
    word: 'nuance',
    partOfSpeech: 'n.',
    translation: '細微差異；語氣層次',
    detailLabel: '首輪 12h',
    isHighlighted: true,
  },
}
