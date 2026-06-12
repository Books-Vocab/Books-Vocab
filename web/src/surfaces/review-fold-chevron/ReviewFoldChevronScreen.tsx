import type { ScenarioId } from '../../harness/scenarios'
import { REVIEW_FOLD_CHEVRON_FIXTURES } from './fixtures'
import { ChevronUpIcon } from './icons'
import './review-fold-chevron.css'

/**
 * Review Fold · Chevron Pill surface — iOS `ReviewFoldChevronPill`
 * （`ReviewFoldSurface.swift`）的 web 鏡像。
 *
 * Pill：Button[ Image(chevron.up, iconTiny 10pt semibold / tertiaryText@0.78)
 *   .frame(34×18) .background(Capsule fill cardBackground@0.94)
 *   .overlay(Capsule stroke divider@0.58, lineWidth hairline=1)
 *   .frame(48 × chevronButtonSize=30) ]。buttonStyle .plain、contentShape Capsule。
 *
 * 兩 scenario 皆 layout .fill（全裝置幀 1179×2556、畫布透明 corner srgba 0,0,0,0）：
 *  - collapse-handle：pill .padding(40) 於整 frame 內**垂直置中**。
 *  - on-card-backdrop：sampleCard（.padding(24)、radii.card=md=8、bg cardBackground、
 *    border cardBorder 1px）以 .overlay(.bottom) 疊 pill、pill .offset(y:10)；card
 *    .padding(40) 後整體垂直置中。sampleCard 內文用 SwiftUI 系統 .title3.semibold /
 *    .subheadline+.secondary / .footnote+.tertiary（非 appSkin token）。
 *
 * 走**全 phone-frame 透明捕捉**（.fill scene 透明畫布，非 crop=component）：
 * phone-frame 本體透明，shots transparent:true（omitBackground）→ 內容-over-transparent。
 */
export function ReviewFoldChevronScreen({
  scenario,
}: {
  scenario: ScenarioId<'review-fold-chevron'>
}) {
  const fixture = REVIEW_FOLD_CHEVRON_FIXTURES[scenario]

  if (fixture.kind === 'card' && fixture.card) {
    return (
      <div className="review-fold-chevron-surface">
        <div className="review-fold-chevron-card">
          <div className="review-fold-chevron-card-title">{fixture.card.title}</div>
          <div className="review-fold-chevron-card-subtitle">{fixture.card.subtitle}</div>
          <div className="review-fold-chevron-card-body">{fixture.card.body}</div>
          {/* .overlay(alignment: .bottom){ pill.offset(y: 10) } */}
          <div className="review-fold-chevron-card-overlay">
            <ChevronPill />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="review-fold-chevron-surface">
      <ChevronPill />
    </div>
  )
}

/** ReviewFoldChevronPill — 置中收合手柄膠囊。 */
function ChevronPill() {
  return (
    <button type="button" className="review-fold-chevron-pill" aria-label="收合">
      <span className="review-fold-chevron-pill-inner">
        <ChevronUpIcon className="review-fold-chevron-pill-icon" size={13} strokeWidth={1.8} />
      </span>
    </button>
  )
}
