import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_SECTION_HEADER_FIXTURES } from './fixtures'
import { ClockBadgeIcon } from './icons'
import './vocab-section-header.css'

/**
 * VocabSectionHeader surface — iOS `VocabSectionHeader` 的 web 鏡像（Vocab Shell
 * 原語層的滿寬列）。HStack(spacing: microGap=6)[optional iconTiny + caption(12,bold)
 * title w/ labelTracking 0.5 + optional monoLabel(mono 10,bold) trailingText + Spacer]，
 * 整列 foregroundStyle = tertiaryText；trailingText 覆寫為 quaternaryText。
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0）：surface =
 * wrapWide 的 `.frame(maxWidth:.infinity).padding(24)` 滿寬列盒（ref 1179×191
 * = 393×63.67pt@dpr3）。`?crop=component` 令 surface 與 phone-frame 透明、shots
 * `transparent:true` omitBackground 截圖（見 vocab-section-header.css）。
 */
export function VocabSectionHeaderScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-section-header'>
}) {
  const { title, icon, trailingText } = VOCAB_SECTION_HEADER_FIXTURES[scenario]
  return (
    <div className="vocab-section-header-surface">
      <div className="vocab-section-header">
        {icon && <ClockBadgeIcon className="vocab-section-header-icon" />}
        <span className="vocab-section-header-title">{title}</span>
        {trailingText != null && (
          <span className="vocab-section-header-count">{trailingText}</span>
        )}
        <span className="vocab-section-header-spacer" />
      </div>
    </div>
  )
}
