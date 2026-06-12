import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabTabSelector scenario fixtures — 對齊 VocabShellComponentsScenarios.swift
 * 「Vocab Shell · Tab Selector」3 態。
 *
 * scene = VocabTabSelectorScene(initial:, counts:)；options =
 * VocabularyReviewState.allCases.map { VocabTabOption(id:, title: $0.title,
 * count: counts[$0]) }。allCases 順序 = unlearned / due / reviewed，title =
 * VocabularyReviewState.title（未學習 / 待複習 / 已複習）。
 *
 *   counts 空 dict → 每 option count == nil → 無 count badge。
 *   counts 含 0 → count == 0 → 仍顯示 badge（"0"）。
 *   selected = initial（單選，selected pill = mutedFill capsule）。
 */
export type VocabTabOption = { id: string; title: string; count: number | null }

export const VOCAB_TAB_SELECTOR_FIXTURES: Record<
  ScenarioId<'vocab-tab-selector'>,
  { options: VocabTabOption[]; selected: string }
> = {
  // No counts · unlearned selected — counts:[:] → 全部 count nil（無 badge）
  'no-counts': {
    options: [
      { id: 'unlearned', title: '未學習', count: null },
      { id: 'due', title: '待複習', count: null },
      { id: 'reviewed', title: '已複習', count: null },
    ],
    selected: 'unlearned',
  },
  // With counts · due selected — counts:[unlearned:12, due:5, reviewed:38]
  'with-counts': {
    options: [
      { id: 'unlearned', title: '未學習', count: 12 },
      { id: 'due', title: '待複習', count: 5 },
      { id: 'reviewed', title: '已複習', count: 38 },
    ],
    selected: 'due',
  },
  // Zero counts · reviewed selected — counts:[unlearned:0, due:0, reviewed:0]
  'zero-counts': {
    options: [
      { id: 'unlearned', title: '未學習', count: 0 },
      { id: 'due', title: '待複習', count: 0 },
      { id: 'reviewed', title: '已複習', count: 0 },
    ],
    selected: 'reviewed',
  },
}
