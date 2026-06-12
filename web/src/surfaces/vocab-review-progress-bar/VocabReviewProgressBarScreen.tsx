import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_REVIEW_PROGRESS_BAR_FIXTURES, type ProgressBarItem } from './fixtures'
import './vocab-review-progress-bar.css'

/**
 * VocabReviewProgressBar surface — iOS `VocabReviewProgressBar`(VocabComponents.swift)
 * 的 web 鏡像。
 *
 * iOS view tree（每條 bar）：
 *   if ratio != nil:
 *     VStack(alignment: .trailing, spacing: TodayReviewMetrics.progressBarGap=5) {
 *       Text(detailLabel).font(monoLabel = mono 10 bold).monospacedDigit()
 *                        .foregroundStyle(secondaryText)
 *       GeometryReader { ZStack(.leading) {
 *         Capsule(progressBarBackground)
 *         Capsule(ReviewGradient.color(for: ratio)).frame(width: max(6, W*min(ratio,1)))
 *       }}.frame(width: progressBarWidth=104, height: 5)
 *     }
 *   else: Text(detailLabel).font(monoLabel).foregroundStyle(secondaryText)
 *
 * 「Ratios」scenario 為 VStack(alignment: .trailing, spacing 24) 包 4 條 bar；
 * 其餘為單條。整個 scene 外層 .padding(24)。
 *
 * catalog 元件 scene 畫布透明（corner srgba 0）：`?crop=component` 令 surface 透明、
 * shots `transparent:true` omitBackground 截圖（見 vocab-review-progress-bar.css）。
 */
export function VocabReviewProgressBarScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-review-progress-bar'>
}) {
  const { items } = VOCAB_REVIEW_PROGRESS_BAR_FIXTURES[scenario]
  return (
    <div className="vocab-review-progress-bar-surface">
      <div className="vocab-review-progress-bar-stack">
        {items.map((item, i) => (
          <ProgressBar key={i} item={item} />
        ))}
      </div>
    </div>
  )
}

function ProgressBar({ item }: { item: ProgressBarItem }) {
  // ratio === null → 只渲染 detailLabel 文字（無 bar）
  if (item.ratio === null) {
    return <span className="vocab-review-progress-bar-detail">{item.detailLabel}</span>
  }
  const clamped = Math.min(item.ratio, 1)
  return (
    <div className="vocab-review-progress-bar-group">
      {item.detailLabel !== null && (
        <span className="vocab-review-progress-bar-detail">{item.detailLabel}</span>
      )}
      <div
        className="vocab-review-progress-bar-track"
        role="progressbar"
        aria-label="複習進度"
        aria-valuenow={Math.round(clamped * 100)}
      >
        <div
          className="vocab-review-progress-bar-fill"
          style={{
            // width: max(6px, W * clamped) — clamp(min-nub, %, 100%)
            width: `max(var(--progress-bar-fill-min), ${clamped * 100}%)`,
            background: item.fill ?? undefined,
          }}
        />
      </div>
    </div>
  )
}
