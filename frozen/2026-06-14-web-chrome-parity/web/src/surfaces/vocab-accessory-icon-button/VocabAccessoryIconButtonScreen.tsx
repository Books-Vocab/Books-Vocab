import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_ACCESSORY_ICON_BUTTON_FIXTURES } from './fixtures'
import { TrashIcon } from './icons'
import './vocab-accessory-icon-button.css'

/**
 * VocabAccessoryIconButton surface — iOS `VocabAccessoryIconButton` 的 web 鏡像
 * （Vocab Shell chrome 層 atom）。SF symbol（iconToolbar = symbol 15/medium）+
 * tone（系統紅）前景，置於 chromeButtonSize(32) 方形、RoundedRectangle(tiny=6,
 * continuous) muted-fill 背景內。
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0,0,0,0）：
 * `?crop=component` 令 surface 透明、shots `transparent:true` 以 omitBackground
 * 截圖，使 web 與 ref 同為 button-over-transparent（見 vocab-accessory-icon-button.css）。
 */
export function VocabAccessoryIconButtonScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-accessory-icon-button'>
}) {
  const { accessibilityLabel } = VOCAB_ACCESSORY_ICON_BUTTON_FIXTURES[scenario]
  return (
    <div className="vocab-accessory-icon-button-surface">
      <button type="button" className="vocab-accessory-icon-button" aria-label={accessibilityLabel}>
        <TrashIcon className="vocab-accessory-icon-button-icon" />
      </button>
    </div>
  )
}
