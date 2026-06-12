import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { PlayFillIcon } from '../podcast/icons'
import { PODCAST_RAIL_CARD_FIXTURES } from './fixtures'
import './podcast-rail-card.css'

/**
 * PodcastContinueRailCard surface — iOS `PodcastContinueRailCard`
 * (PodcastShelf.swift:36) 的 web 鏡像（resume-rail 卡，cardWidth=150）。
 *
 * iOS view tree：
 *   VStack(.leading, spacing: AppSpacing.s2=8) {
 *     NotebookCoverView(color, pattern: waves, name: series.title)   // 150×150
 *       .clipShape(RoundedRectangle(radius: AppRadius.md=8, .continuous))
 *       .overlay(.bottomTrailing) { playDisc }                       // 30×30 brandHero circle
 *       .appElevation(.z1)
 *     VStack(.leading, spacing: skin.spacing.tinyGap=4) {
 *       Text(series.title).font(caption=sans12 bold).fg(primaryText).lineLimit(1).tail
 *       Text(episode.displayTitle).font(caption2=sans11 reg).fg(tertiaryText).lineLimit(1).tail
 *       if fraction>0 { ProgressCapsule(height:3, fill:accent, track:progressBarBackground)
 *                         .padding(.top, tinyGap=4) }
 *       if let remaining { Text(remaining).font(monoLabel=mono10 bold).fg(tertiaryText).monospacedDigit }
 *     }.frame(width:150, .leading)
 *   }.frame(width:150)
 *
 * NotebookCoverView：ZStack { color ; waves pattern overlay（white opacity 0.12,
 * amplitude 8 / wavelength 30 / row-spacing 20 / lineWidth 1.2）; centered white name
 * (body=sans17 semibold, lineLimit 2, shadow black .3) }。color 已 legacy-migrate 至
 * "#AFC2D3"（notebook palette 資料色，以 inline --rail-cover 承載，非視覺 token）。
 *
 * playDisc：Circle().fill(brandHero) + play.fill (iconTiny=10pt thin, onBrandHero)，
 * 30×30，.appElevation(.z1)，.padding(AppSpacing.s2=8) → 距 cover 邊 8pt。
 *
 * catalog scene 畫布透明（component-isolated，corner srgba 0）：`?crop=component`
 * 令 surface + phone-frame 透明、shots `transparent:true` omitBackground 截圖。
 * surface = scene 的 .padding(24) intrinsic box。
 *
 * a11y3 場景 iOS 套 .accessibility3，但 AppFonts 固定字級不隨 dynamicType 縮放，
 * catalog PNG 與其餘態同尺寸 → web 無需特殊處理。
 */

/** waves pattern overlay — 對齊 NotebookCoverPatterns.waves（pt 單位，150×150 cover）。 */
function WavesPattern() {
  const amplitude = 8
  const wavelength = 30
  const spacing = 20
  const size = 150
  const rows: string[] = []
  for (let y0 = spacing / 2; y0 < size + amplitude; y0 += spacing) {
    let d = `M 0 ${y0}`
    for (let x = 0; x <= size; x += 2) {
      const y = y0 + amplitude * Math.sin((x / wavelength) * Math.PI * 2)
      d += ` L ${x} ${y.toFixed(2)}`
    }
    rows.push(d)
  }
  return (
    <svg
      className="prc-cover-pattern"
      viewBox={`0 0 ${size} ${size}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      {rows.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="#ffffff" strokeOpacity={0.12} strokeWidth={1.2} />
      ))}
    </svg>
  )
}

export function PodcastRailCardScreen({ scenario }: { scenario: ScenarioId<'podcast-rail-card'> }) {
  const f = PODCAST_RAIL_CARD_FIXTURES[scenario]
  return (
    <div className="prc-surface">
      <div className="prc-card" style={{ '--rail-cover': f.coverColor } as CSSProperties}>
        {/* NotebookCoverView 150×150 + clip(radius md) + elevation z1 */}
        <div className="prc-cover">
          <WavesPattern />
          <span className="prc-cover-name">{f.coverName}</span>
          {/* playDisc：bottomTrailing overlay, brandHero circle */}
          <span className="prc-play-disc" aria-hidden="true">
            <PlayFillIcon className="prc-play-glyph" />
          </span>
        </div>

        {/* meta VStack(spacing: tinyGap=4) */}
        <div className="prc-meta">
          <span className="prc-title">{f.title}</span>
          <span className="prc-episode">{f.episodeDisplay}</span>

          {f.fraction > 0 && (
            <div className="prc-progress">
              <span className="prc-progress-fill" style={{ width: `${f.fraction * 100}%` }} />
            </div>
          )}

          {f.remaining != null && <span className="prc-remaining">{f.remaining}</span>}
        </div>
      </div>
    </div>
  )
}
