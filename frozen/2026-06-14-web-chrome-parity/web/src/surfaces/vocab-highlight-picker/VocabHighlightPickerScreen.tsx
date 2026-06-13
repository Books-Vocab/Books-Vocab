import type { ScenarioId } from '../../harness/scenarios'
import { HIGHLIGHT_PRESETS, VOCAB_HIGHLIGHT_PICKER_FIXTURES } from './fixtures'
import './vocab-highlight-picker.css'

/**
 * Vocab · Highlight Picker surface — iOS `VocabHighlightColorPresetPicker`（Reader
 * 螢光標記顏色選擇器）的 web 鏡像。
 *
 * VStack(align:leading, spacing s2)[caption 標題 · HStack(s2) 4×tile]。每個 tile =
 * ReaderSelectionTile(isSelected) 包 VStack(s2)[Circle swatch 18px + stroke cardBorder ·
 * caption label]，frame maxWidth:.infinity、padding .vertical vocabOptionVerticalPadding(10)。
 * selected：mutedFill + cardBorder + primaryText；unselected：pageBackground +
 * divider×0.6 + secondaryText（同 ReaderSelectionTile chrome）。
 *
 * catalog scene = .fill 透明（alpha-mean 0.049）、picker .padding(s4=16) 於整幀**垂直置中**。
 * 故全 phone-frame 透明捕捉（transparent:true）、surface justify-content center。
 */
export function VocabHighlightPickerScreen({ scenario }: { scenario: ScenarioId<'vocab-highlight-picker'> }) {
  const selected = VOCAB_HIGHLIGHT_PICKER_FIXTURES[scenario]
  return (
    <div className="vhp-surface">
      <div className="vhp-picker">
        <div className="vhp-title">螢光標記顏色</div>
        <div className="vhp-row">
          {HIGHLIGHT_PRESETS.map((preset) => (
            <div
              key={preset.key}
              className="vhp-tile"
              data-selected={preset.key === selected ? '1' : undefined}
            >
              <span className="vhp-swatch" style={{ background: preset.color }} />
              <span className="vhp-label">{preset.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
