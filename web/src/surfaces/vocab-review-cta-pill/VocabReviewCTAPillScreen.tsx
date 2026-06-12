import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_REVIEW_CTA_PILL_FIXTURES } from './fixtures'
import './vocab-review-cta-pill.css'

/**
 * VocabReviewCTAPill surface — iOS `VocabReviewCTAPill` 的 web 鏡像（Vocab Shell
 * 原語層 CTA atom）。pillLabel：HStack(spacing microGap=6)[systemImage + caption
 * monospacedDigit count]，內距 = compact-chip token（6h/3v），填 brandHero capsule、
 * 前景 onBrandHero。due/unlearned 數量決定前導圖示（play.fill / clock.badge /
 * sparkles）。
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0,0,0,0）：
 * `?crop=component` 令 surface + phone-frame 透明、shots `transparent:true` 以
 * omitBackground 截圖，使 web 與 ref 同為 pill-over-transparent（見 css）。
 */
export function VocabReviewCTAPillScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-review-cta-pill'>
}) {
  const { count, Icon, iconSize, ariaLabel } = VOCAB_REVIEW_CTA_PILL_FIXTURES[scenario]
  return (
    <div className="vocab-review-cta-pill-surface">
      <span className="vocab-review-cta-pill" role="button" aria-label={ariaLabel}>
        <Icon className="vocab-review-cta-pill-icon" size={iconSize} />
        <span className="vocab-review-cta-pill-count">{count}</span>
      </span>
    </div>
  )
}
