import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { PlayFillIcon } from '../podcast/icons'
import { PODCAST_SHELF_FIXTURES, type ShelfCard } from './fixtures'
import './podcast-shelf.css'

/**
 * PodcastShelf surface — iOS `PodcastShelf` carousel container（PodcastShelf.swift:7）
 * 的 web 鏡像：section 標題 + 橫向 `PodcastContinueRailCard` rail。
 *
 * iOS view tree（scene wrapper：ScrollView { PodcastShelf(...).padding(.vertical, s4=16) }）：
 *   VStack(.leading, spacing: skin.spacing.statusHeroGap=12) {
 *     Text(title).font(sectionTitle=serif18 bold).fg(primaryText)
 *       .lineLimit(1).tail.padding(.horizontal, pageHorizontalPadding=s5=20)
 *     ScrollView(.horizontal, showsIndicators:false) {
 *       LazyHStack(spacing: AppSpacing.s3=12) { content() }
 *         .padding(.horizontal, pageHorizontalPadding=20)
 *     }
 *   }
 *
 * 每張卡 = `PodcastContinueRailCard`（cardWidth=150）：
 *   VStack(.leading, spacing: s2=8) {
 *     NotebookCoverView(color #AFC2D3, waves) 150×150 .clip(md=8) .overlay(.bottomTrailing){playDisc}
 *       .appElevation(.z1)
 *     VStack(.leading, spacing: tinyGap=4) {
 *       Text(series.title).font(caption=sans12 bold).fg(primaryText).lineLimit(1).tail
 *       Text(episode.displayTitle).font(caption2=sans11 reg).fg(tertiaryText).lineLimit(1).tail
 *       if fraction>0 { ProgressCapsule(h3, fill accent, track progressBarBackground).padding(.top tinyGap) }
 *       if remaining { Text(remaining).font(monoLabel=mono10 bold).fg(tertiaryText).monospacedDigit }
 *     }.frame(width:150,.leading)
 *   }.frame(width:150)
 *
 * waves overlay：white .12 / amplitude 8 / wavelength 30 / row-spacing 20 / lineWidth 1.2。
 * playDisc：Circle().fill(brandHero) 30×30 + play.fill(iconTiny) onBrandHero，pad s2=8。
 *
 * catalog scene = .fillH，畫布透明（corner srgba 0,0,0,0；Full 與 A11y3 byte-identical
 * — AppFonts 固定字級不隨 dynamicType 縮放）→ component crop（透明畫布）。
 * surface = scene wrapper 的 .padding(.vertical, s4=16) intrinsic box，width = 393pt
 * 全屏寬（.fillH），rail 溢出右緣由 crop 捕捉。
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
      className="psh-cover-pattern"
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

function RailCard({ card }: { card: ShelfCard }) {
  return (
    <div className="psh-card" style={{ '--rail-cover': card.coverColor } as CSSProperties}>
      {/* NotebookCoverView 150×150 + clip(md) + elevation z1 */}
      <div className="psh-cover">
        <WavesPattern />
        <span className="psh-cover-name">{card.coverName}</span>
        <span className="psh-play-disc" aria-hidden="true">
          <PlayFillIcon className="psh-play-glyph" />
        </span>
      </div>

      {/* meta VStack(spacing: tinyGap=4) */}
      <div className="psh-meta">
        <span className="psh-card-title">{card.title}</span>
        <span className="psh-episode">{card.episodeDisplay}</span>

        {card.fraction > 0 && (
          <div className="psh-progress">
            <span className="psh-progress-fill" style={{ width: `${card.fraction * 100}%` }} />
          </div>
        )}

        {card.remaining != null && <span className="psh-remaining">{card.remaining}</span>}
      </div>
    </div>
  )
}

export function PodcastShelfScreen({ scenario }: { scenario: ScenarioId<'podcast-shelf'> }) {
  const { shelfTitle, cards } = PODCAST_SHELF_FIXTURES[scenario]
  return (
    <div className="psh-surface">
      {/* VStack(.leading, spacing: statusHeroGap=12) */}
      <div className="psh-shelf">
        {/* Text(title).font(sectionTitle).lineLimit(1).pad(.horizontal, 20) */}
        <div className="psh-title">{shelfTitle}</div>

        {/* ScrollView(.horizontal){ LazyHStack(spacing s3=12).padding(.horizontal 20) } */}
        <div className="psh-rail">
          {cards.map((card, i) => (
            <RailCard key={i} card={card} />
          ))}
        </div>
      </div>
    </div>
  )
}
