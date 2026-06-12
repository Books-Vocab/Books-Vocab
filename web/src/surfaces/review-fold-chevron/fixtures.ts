import type { ScenarioId } from '../../harness/scenarios'

/**
 * Review Fold · Chevron Pill 兩個 catalog scenario（皆 layout .fill）：
 *  - collapse-handle：裸 `ReviewFoldChevronPill`（.padding(40)）置中。
 *  - on-card-backdrop：`sampleCard`（title/subtitle/body）上以 `.overlay(.bottom)`
 *    疊 pill，`.offset(y: 10)`；card `.padding(40)`。
 */
export interface ReviewFoldChevronFixture {
  kind: 'handle' | 'card'
  card?: { title: string; subtitle: string; body: string }
}

export const REVIEW_FOLD_CHEVRON_FIXTURES: Record<
  ScenarioId<'review-fold-chevron'>,
  ReviewFoldChevronFixture
> = {
  'collapse-handle': { kind: 'handle' },
  'on-card-backdrop': {
    kind: 'card',
    card: {
      title: 'knowledge graph',
      subtitle: '知識圖譜',
      body: '一張用於展示摺疊效果的範例卡片。',
    },
  },
}
