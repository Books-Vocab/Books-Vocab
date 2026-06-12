import type { ScenarioId } from '../../harness/scenarios'
import { PODCAST_BUBBLE_CELL_FIXTURES } from './fixtures'
import './podcast-bubble-cell.css'

/**
 * PodcastBubbleCell surface — iOS `PodcastBubbleCell`（PodcastTranscriptColumn.swift:193）
 * 的 web 鏡像。一個對話氣泡：speaker 標籤 + 文字氣泡。
 *
 * iOS view tree：
 *   HStack(alignment:.bottom, spacing:0) {
 *     if alignRight { Spacer(minLength:48) }
 *     VStack(alignment: alignRight ? .trailing : .leading, spacing: tinyGap=4) {
 *       if showSpeaker:
 *         Text(speaker).font(speakerFont = mono 11 bold)
 *           .foregroundStyle(tint.opacity(active ? 0.88 : 0.58))
 *       bubbleContent
 *     }
 *     if !alignRight { Spacer(minLength:48) }
 *   }
 *
 * bubbleContent（subtitleSize=.large）：
 *   text(sans 17) padding(.h s3=12 .v compactRowVerticalPadding=10)
 *   bg RoundedRect(radius card=8) fill tint.opacity(active?0.18:0.08)
 *      stroke tint.opacity(active?0.22:0.08) lineWidth active?1:0.8
 *   active = isHighlighted（catalog 無 selection）→ 文字 primaryText，否則 secondaryText
 *   vocab 命中詞：paper 螢光筆底色帶（line bottom 32%、word width+4、opacity 0.22）
 *
 * tint：slot0=Alex=accent(blue)、slot1=Jordan=success(green)。
 *
 * Scene = BubbleCellScene，wrapper `.padding(AppSpacing.s4=16)`（rig 慣例）。
 * catalog component scene 透明（corner srgba 0）：`?crop=component` 令 surface +
 * phone-frame 透明、shots `transparent:true` omitBackground 截圖。
 */
export function PodcastBubbleCellScreen({ scenario }: { scenario: ScenarioId<'podcast-bubble-cell'> }) {
  const fx = PODCAST_BUBBLE_CELL_FIXTURES[scenario]
  // tint var：slot0→--accent，slot1→--success
  const tintVar = fx.slot === 0 ? 'var(--accent)' : 'var(--success)'
  const rowClass = ['pbc-row', fx.alignRight ? 'pbc-row--right' : 'pbc-row--left'].join(' ')
  const stackClass = ['pbc-stack', fx.active ? 'pbc-stack--active' : 'pbc-stack--idle'].join(' ')

  return (
    <div className="podcast-bubble-cell-surface">
      <div className={rowClass} style={{ ['--pbc-tint' as string]: tintVar }}>
        <div className={stackClass}>
          <span className="pbc-speaker">{fx.speaker}</span>
          <div className="pbc-bubble">
            <p className="pbc-text">
              {fx.words.map((w, i) => (
                <span key={i}>
                  <span className={w.vocab ? 'pbc-word pbc-word--vocab' : 'pbc-word'}>{w.text}</span>
                  {i < fx.words.length - 1 ? ' ' : ''}
                </span>
              ))}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
