import type { ScenarioId } from '../../harness/scenarios'
import { REVIEW_FOLD_SEGMENT_FIXTURES, type FoldSegment } from './fixtures'
import './review-fold-segment.css'

/**
 * Review Fold · Segment — iOS `ReviewFoldSurface` 的 web 鏡像。
 *
 * ReviewFoldSurface(position) 包 content：
 *   .background(cardBackground.opacity(0.985))
 *   .clipShape(UnevenRoundedRectangle)：single/top→top 角 radii.card(8)，single/bottom→bottom 角 8；
 *     join 邊（middle 上下、top 下、bottom 上）= foldJoinRadius(4=--radius-xs)
 *   .overlay(stroke cardBorder.opacity(0.72) 1px，同 shape)
 *   .overlay(.top) 若 position ∈ {middle,bottom}：divider.opacity(0.85) 高 0.5pt，
 *     padding(.horizontal cardPadding=18)
 *   .appElevation(.z1)
 *
 * segmentBody = VStack(spacing 6=--micro-gap, leading)[headline title · subheadline(.secondary) subtitle]
 *   .frame(maxWidth:.infinity, leading).padding(20=--sp-5)
 *
 * Single scene = ReviewFoldSurface.padding(40)；Stacked = VStack(spacing 0)[top·middle·bottom].padding(24)。
 * catalog layout = .fill（1179×2556，corner srgba 0,0,0,0 透明）→ 全 phone-frame 透明捕捉，
 * 內容垂直置中、水平內縮 scene padding(24)。phone-frame 透明，shots transparent:true。
 */
export function ReviewFoldSegmentScreen({ scenario }: { scenario: ScenarioId<'review-fold-segment'> }) {
  const segments = REVIEW_FOLD_SEGMENT_FIXTURES[scenario]
  return (
    <div className="review-fold-segment-surface">
      <div className="review-fold-segment-stack">
        {segments.map((seg, i) => (
          <FoldSurface key={i} segment={seg} />
        ))}
      </div>
    </div>
  )
}

function FoldSurface({ segment }: { segment: FoldSegment }) {
  const showDivider = segment.position === 'middle' || segment.position === 'bottom'
  return (
    <div className="review-fold-segment-cell" data-position={segment.position}>
      {showDivider ? <div className="review-fold-segment-divider" /> : null}
      <div className="review-fold-segment-body">
        <div className="review-fold-segment-title">{segment.title}</div>
        <div className="review-fold-segment-subtitle">{segment.subtitle}</div>
      </div>
    </div>
  )
}
