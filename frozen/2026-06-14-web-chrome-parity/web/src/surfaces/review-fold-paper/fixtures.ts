import type { ScenarioId } from '../../harness/scenarios'

/** Paper Fold 各 scenario 的 progress（iOS PaperFoldModifier.progress）。
 *  catalog title → progress：1.0 / 0.75 / 0.5 / 0.25 / 0.05。 */
export const REVIEW_FOLD_PAPER_FIXTURES: Record<
  ScenarioId<'review-fold-paper'>,
  { progress: number }
> = {
  expanded: { progress: 1.0 },
  'three-quarter': { progress: 0.75 },
  half: { progress: 0.5 },
  quarter: { progress: 0.25 },
  'nearly-folded': { progress: 0.05 },
}

/** 範例卡片內容（ReviewFoldScenarios.sampleCard，title=serendipity / subtitle=機緣巧合）。 */
export const SAMPLE_CARD = {
  title: 'serendipity',
  subtitle: '機緣巧合',
  body: '一張用於展示摺疊效果的範例卡片。',
}
