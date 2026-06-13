import type { ScenarioId } from '../../harness/scenarios'

export type FoldPosition = 'single' | 'top' | 'middle' | 'bottom'

export interface FoldSegment {
  position: FoldPosition
  title: string
  subtitle: string
}

/** ReviewFoldScenarios.segmentBody fixtures (catalog SoT). */
export const REVIEW_FOLD_SEGMENT_FIXTURES: Record<ScenarioId<'review-fold-segment'>, FoldSegment[]> = {
  single: [{ position: 'single', title: 'serendipity', subtitle: '機緣巧合' }],
  'stacked-group': [
    { position: 'top', title: 'serendipity', subtitle: '機緣巧合' },
    { position: 'middle', title: 'epiphany', subtitle: '頓悟' },
    { position: 'bottom', title: 'revelation', subtitle: '揭示' },
  ],
}
