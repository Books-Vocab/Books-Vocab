import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_TONE_CHIP_FIXTURES } from './fixtures'
import './vocab-tone-chip.css'

/**
 * VocabToneChip surface — iOS `VocabToneChip` 的 web 鏡像（VocabComponents 葉節點）。
 *
 * iOS view tree（VocabComponents.swift:55）：
 *   Text(text).font(caption=sans12 bold).foregroundStyle(tone)
 *     .padding(.h chipHorizontalPadding=10).padding(.v chipVerticalPadding=6)
 *     .background(tone.opacity(0.08)).clipShape(Capsule(.continuous))
 *
 * tone = SwiftUI 系統色，per-chip 以 inline `--tone` CSS 變數注入（值取自
 * --tone-{blue|green|red|purple|indigo} design token）；文字用全色、bg 用 8% alpha。
 *
 * catalog scene 畫布透明（component-isolated，corner srgba 0）：`?crop=component`
 * 令 surface + phone-frame 透明、shots `transparent:true` omitBackground 截圖。
 * surface = scene 的 .padding(24) intrinsic box；Variants 內含 VStack(spacing 16)。
 */
export function VocabToneChipScreen({ scenario }: { scenario: ScenarioId<'vocab-tone-chip'> }) {
  const { chips } = VOCAB_TONE_CHIP_FIXTURES[scenario]
  return (
    <div className="vocab-tone-chip-surface">
      <div className="vocab-tone-chip-stack">
        {chips.map((chip, i) => (
          <span
            key={i}
            className="vocab-tone-chip"
            style={{ '--tone': `var(--system-${chip.tone})` } as CSSProperties}
            aria-label="語氣標記"
          >
            {chip.text}
          </span>
        ))}
      </div>
    </div>
  )
}
