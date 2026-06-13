import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_INLINE_ACTION_BUTTON_FIXTURES } from './fixtures'
import './vocab-inline-action-button.css'

/**
 * VocabInlineActionButton surface — iOS `VocabInlineActionButton` 的 web 鏡像
 * （Vocab Shell chrome 層 inline 文字按鈕）。
 *
 * iOS view tree：`Button(title)` + `.buttonStyle(.plain)` → 純文字、無背景、
 * 無內距；.font(appSkin.typography.body) = sans 15（= --text-subhead，注意
 * 非 --text-body=17）；.foregroundStyle(tone ?? accent)。
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0）：scene 為
 * 文字 + wrapCompact 的 .padding(24)。`?crop=component` 令 surface 與 phone-frame
 * 透明、shots `transparent:true`，使 web 與 ref 同為 text-over-transparent。
 */
export function VocabInlineActionButtonScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-inline-action-button'>
}) {
  const { title, tone } = VOCAB_INLINE_ACTION_BUTTON_FIXTURES[scenario]
  return (
    <div className="vocab-inline-action-button-surface">
      <button type="button" className="vocab-inline-action-button" data-tone={tone}>
        {title}
      </button>
    </div>
  )
}
