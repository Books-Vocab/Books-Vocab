import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { PODCAST_SERIES_CARD_FIXTURES, metaLine } from './fixtures'
import { WaveformBadgeIcon } from './icons'
import './podcast-series-card.css'

/**
 * PodcastSeriesCard surface — iOS `PodcastSeriesCard`（poster-style series tile）
 * 的 web 鏡像。
 *
 * view tree（PodcastSeriesCard.body）：
 *   VStack(.leading, spacing s2)[
 *     coverView                                  — NotebookCoverView aspectRatio 2/3
 *       .frame(height coverHeightCompact=210)    — clip radius coverCornerRadius=10
 *       .overlay(topTrailing) waveform badge     — caption2(bold) primaryText
 *                                                  + ultraThinMaterial radius sm(6)
 *                                                  + inner pad s1(4) / outer pad s2(8)
 *       .appElevation(.z0)                        — z0 = none
 *     VStack(.leading, spacing tinyGap=3)[
 *       Text(title)  caption(medium=500) primaryText  lineLimit(2, reservesSpace)
 *       Text(meta)   caption2() tertiaryText          lineLimit(1) tail
 *     ]
 *   ]
 *
 * 封面：solid coverColor（#4A90D9 → migrated #AFC2D3）+ waves pattern overlay
 * （white 0.12 strokes，amplitude 8 / wavelength 30 / spacing 20 / lineWidth 1.2）
 * + 置中白字 name（body 17 semibold，shadow 黑 0.3 r2 y1，minScale 0.85）。
 *
 * catalog 元件 scene 透明（component-isolated，corner srgba 0,0,0,0）：crop 目標 =
 * scene wrapper（card + iOS `.padding()`=16），surface 與 phone-frame 在
 * crop=component 下透明，shots omitBackground 截圖。
 */
export function PodcastSeriesCardScreen({
  scenario,
}: {
  scenario: ScenarioId<'podcast-series-card'>
}) {
  const f = PODCAST_SERIES_CARD_FIXTURES[scenario]
  const cardStyle = {
    '--psc-card-width': `${f.width}px`,
    '--psc-cover-color': f.coverColor,
  } as CSSProperties

  return (
    <div className="podcast-series-card-surface">
      <div className="psc-card" style={cardStyle}>
        {/* 封面 — color + waves overlay + 置中白字 name；topTrailing waveform badge */}
        <div className="psc-cover">
          <div className="psc-cover-waves" aria-hidden="true" />
          <span className="psc-cover-name">{f.title}</span>
          <div className="psc-badge" aria-hidden="true">
            <WaveformBadgeIcon className="psc-badge-icon" />
          </div>
        </div>

        {/* 元資料 */}
        <div className="psc-meta">
          <span className="psc-title">{f.title}</span>
          <span className="psc-subtitle">{metaLine(f)}</span>
        </div>
      </div>
    </div>
  )
}
