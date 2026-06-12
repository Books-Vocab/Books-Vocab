import type { ScenarioId } from '../../harness/scenarios'

/**
 * Vocab Presenter (search) fixtures — 對齊 iOS `KGVocabSearchScenarios.swift`
 * 的三個 scene（query "ous" / "serendipity" / "zzzznotaword"）。
 *
 * scene 注入 7 個 synced + unlearned 的 `VocabularyEntry`（見
 * KGVocabSearchFixtures.library），交給 `KGVocabView(searchText:)`。KGVocabView
 * 計算：
 *   - tabOptions count = classify → 全部 unlearned ⇒ 未學習 7 / 待複習 0 / 已複習 0
 *   - rows = sortAndFilter(library, searchText) → query 子集（containsCaseInsensitive）
 *   - emptyState = KGVocabEmptyState（hasNoEntries=false, searchText 非空 ⇒
 *     title「沒有符合的單字」/ desc「試試其他關鍵字，或取消部分篩選條件。」/
 *     icon magnifyingglass）；presenter guidanceText =「嘗試切換篩選條件或新增單字」
 *     （emptyState.action == nil）。
 *
 * 每個 row 以 wordRowViewData(showsReviewProgress:true, 其餘 false) 取資料：
 * unlearned ratio:nil 分支 → trailing detailLabel「首輪 12h」
 * （reviewIntervalHours.compactHourLabel，全為新卡 → 同字串）。
 */
export interface VocabRowFixture {
  word: string
  partOfSpeech: string
  translation: string
  detailLabel: string
}

export interface VocabPresenterSearchFixture {
  /** 未學習 / 待複習 / 已複習 chip counts（classify 後）。皆 unlearned ⇒ 7/0/0。 */
  counts: { unlearned: number; due: number; reviewed: number }
  /** query-filtered 後在 list card 內呈現的列；空 ⇒ 渲染 in-card 空狀態。 */
  rows: VocabRowFixture[]
}

const POS_ADJ = 'adj.'

export const VOCAB_PRESENTER_SEARCH_FIXTURES: Record<
  ScenarioId<'vocab-presenter-search'>,
  VocabPresenterSearchFixture
> = {
  // query "ous" → meticulous / ingenious / tenacious（library 順序保留）
  matches: {
    counts: { unlearned: 7, due: 0, reviewed: 0 },
    rows: [
      { word: 'meticulous', partOfSpeech: POS_ADJ, translation: '一絲不苟的', detailLabel: '首輪 12h' },
      { word: 'ingenious', partOfSpeech: POS_ADJ, translation: '巧妙的；獨創的', detailLabel: '首輪 12h' },
      { word: 'tenacious', partOfSpeech: POS_ADJ, translation: '堅韌不拔的', detailLabel: '首輪 12h' },
    ],
  },
  // query "serendipity" → 唯一精確命中
  'single-match': {
    counts: { unlearned: 7, due: 0, reviewed: 0 },
    rows: [
      { word: 'serendipity', partOfSpeech: 'n.', translation: '機緣巧合', detailLabel: '首輪 12h' },
    ],
  },
  // query "zzzznotaword" → 無命中 → in-card 空狀態
  'no-match': {
    counts: { unlearned: 7, due: 0, reviewed: 0 },
    rows: [],
  },
}

/** 篩選 chip 三態（VocabularyReviewState.allCases 順序）— 全未選（selection 空 Set）。 */
export const FILTER_CHIPS = [
  { id: 'unlearned', title: '未學習' },
  { id: 'due', title: '待複習' },
  { id: 'reviewed', title: '已複習' },
] as const

/** 空狀態文案（KGVocabEmptyState，searchText 非空分支）。 */
export const EMPTY_STATE = {
  title: '沒有符合的單字',
  description: '試試其他關鍵字，或取消部分篩選條件。',
  /** presenter：action == nil ⇒ 顯示 guidanceText（secondaryText@0.7）。 */
  guidanceText: '嘗試切換篩選條件或新增單字',
} as const

/** sort pill — KGVocabSortOption.default.label，icon 固定 arrow.up.arrow.down。 */
export const SORT_LABEL = '複習優先'
