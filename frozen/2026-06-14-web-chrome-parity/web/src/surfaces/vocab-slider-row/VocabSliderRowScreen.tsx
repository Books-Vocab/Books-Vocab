import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_SLIDER_ROW_FIXTURES } from './fixtures'
import './vocab-slider-row.css'

/**
 * VocabSliderRow surface — iOS `VocabSliderRow` 的 web 鏡像（Vocab Shell
 * chrome 層的滿寬互動列）。view tree：
 *   HStack(spacing: inlineGap=8)[
 *     Text(label) caption(12,bold) primaryText, width 64 leading,
 *     Slider(value, in: range),
 *     Text(format value) monoLabel(mono 10 bold) monospacedDigit
 *       secondaryText, width 42 trailing
 *   ].frame(height: tabSelectorHeight=32)
 * scene wrapper：.frame(maxWidth:.infinity).padding(24) → 滿寬（.fillH）。
 *
 * Slider 在 Catalyst 渲染為「無凸起 thumb」的雙段膠囊軌：filled = tint
 * (#37352f)、empty = 黑 10%（量測 srgba(0,0,0,0.1)），軌高 ~6px。initial=0.6
 * → filled 約 58%。
 *
 * catalog scene 畫布透明（corner srgba 0,0,0,0）：`?crop=component` 令 surface
 * 透明、shots `transparent:true` 以 omitBackground 截圖，使 web 與 ref 同為
 * row-over-transparent（見 vocab-slider-row.css）。
 */
export function VocabSliderRowScreen({ scenario }: { scenario: ScenarioId<'vocab-slider-row'> }) {
  const { label, value, range, valueText } = VOCAB_SLIDER_ROW_FIXTURES[scenario]
  const fillPct = ((value - range[0]) / (range[1] - range[0])) * 100
  return (
    <div className="vocab-slider-row-surface">
      <div className="vocab-slider-row">
        <span className="vocab-slider-row-label">{label}</span>
        <span
          className="vocab-slider-row-track"
          role="slider"
          aria-valuemin={range[0]}
          aria-valuemax={range[1]}
          aria-valuenow={value}
          aria-label={label}
        >
          <span className="vocab-slider-row-fill" style={{ width: `${fillPct}%` }} />
        </span>
        <span className="vocab-slider-row-value">{valueText}</span>
      </div>
    </div>
  )
}
