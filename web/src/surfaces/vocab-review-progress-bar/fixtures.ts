import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabReviewProgressBar scenario fixtures — 對齊 VocabComponentScenarios.swift
 * 「Vocab Components · Review Progress Bar」3 態（VocabReviewProgress：
 * statusLabel / detailLabel / ratio）。
 *
 * statusLabel 在此元件 view tree 中**不渲染**（VocabReviewProgressBar.body 只用
 * detailLabel + ratio；statusLabel 供其他 caller），故 fixtures 不帶它。
 *
 * fill 顏色 = ReviewGradient.color(for: ratio)（runtime 依 ratio 在 HSL 色階上
 * 插值的衍生資料值，非靜態 design token），以 hsl() 寫死於 fixture：
 *   0.00 → hsl(160 48% 38%)  翠綠
 *   0.33 → hsl(134.8 41.2% 42.4%)
 *   0.75 → hsl(79.2 41.8% 46%)
 *   1.00 → hsl(45 55% 48%)   到期黃
 *   1.50 → hsl(21.1 63% 42.9%) 深橘（ratio 仍 1.5，fill 寬度 clamp 至 100%）
 * 與 ReviewGradient.swift stops 同插值法算出。
 */

export type ProgressBarItem = {
  detailLabel: string | null
  /** nil → 不畫 bar，只顯示 detailLabel 文字 */
  ratio: number | null
  /** ReviewGradient.color(for: ratio) 衍生 hsl；ratio=null 時不用 */
  fill: string | null
}

export type ProgressBarScenario = {
  /** 多條 bar（Ratios）或單條（其餘）；VStack(alignment: .trailing, spacing 24) */
  items: ProgressBarItem[]
}

export const VOCAB_REVIEW_PROGRESS_BAR_FIXTURES: Record<
  ScenarioId<'vocab-review-progress-bar'>,
  ProgressBarScenario
> = {
  ratios: {
    items: [
      { detailLabel: '0 / 12', ratio: 0.0, fill: 'hsl(160 48% 38%)' },
      { detailLabel: '4 / 12', ratio: 0.33, fill: 'hsl(134.8 41.2% 42.4%)' },
      { detailLabel: '9 / 12', ratio: 0.75, fill: 'hsl(79.2 41.8% 46%)' },
      { detailLabel: '12 / 12', ratio: 1.0, fill: 'hsl(45 55% 48%)' },
    ],
  },
  'detail-only': {
    items: [{ detailLabel: '尚未開始複習', ratio: null, fill: null }],
  },
  'over-100': {
    items: [{ detailLabel: '15 / 12', ratio: 1.5, fill: 'hsl(21.1 63% 42.9%)' }],
  },
}
