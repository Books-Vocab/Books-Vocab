import { makeFilledGlyph } from '../../shared/glyph'
import type { CoverPattern } from './fixtures'

/**
 * PodcastHomeView 封面用 SF 圖示與 NotebookCoverPattern overlay 的 web 鏡像。
 *
 * pattern overlay 逐 case 對齊 iOS `NotebookCoverPattern.patternOverlay`（Canvas，
 * pt 單位 userSpaceOnUse tile）。白 stroke/fill opacity = patternOpacity(0.12)，
 * 以 literal 承載（同 PodcastSeriesCard/RailCard web 鏡像；notebook-cover token
 * 未在 kg-tokens 定義，故不依賴）。
 */

const OP = 0.12 // token-allow: NotebookStackMetrics.patternOpacity（cover pattern 白線透明度）

/** SF `waveform` — series card 封面右上 badge（caption2 bold primaryText）。
 *  9 條變高豎條（中央最高），對齊 PodcastSeriesCard web 鏡像。 */
export const WaveformBadgeIcon = makeFilledGlyph(
  '<rect x="2.0"  y="10.5" width="1.1" height="3"   rx="0.55"/>' +
    '<rect x="4.7"  y="8"    width="1.1" height="8"   rx="0.55"/>' +
    '<rect x="7.4"  y="5"    width="1.1" height="14"  rx="0.55"/>' +
    '<rect x="10.1" y="9.5"  width="1.1" height="5"   rx="0.55"/>' +
    '<rect x="12.8" y="3"    width="1.1" height="18"  rx="0.55"/>' +
    '<rect x="15.5" y="7"    width="1.1" height="10"  rx="0.55"/>' +
    '<rect x="18.2" y="9"    width="1.1" height="6"   rx="0.55"/>' +
    '<rect x="20.9" y="10.5" width="1.1" height="3"   rx="0.55"/>',
)

/** SF `star.fill` — series card 封面左上 followed badge（caption2 bold accent）。 */
export const StarFillIcon = makeFilledGlyph(
  '<path d="M12 2.2l2.93 5.94 6.55.95-4.74 4.62 1.12 6.52L12 17.17l-5.86 3.08 1.12-6.52L2.52 9.09l6.55-.95z"/>',
)

/** SF `play.fill` — continue rail card playDisc（onBrandHero）。 */
export const PlayFillIcon = makeFilledGlyph('<path d="M7 4.8v14.4l11.2-7.2z"/>')

/**
 * NotebookCoverPattern overlay。waves/dots/grid/lines 走 tile pattern；
 * circles 走置中同心圓（無法 tile）。鋪滿 cover box（100%）。
 */
export function PatternOverlay({ pattern }: { pattern: CoverPattern }) {
  if (pattern === 'circles') return <CirclesOverlay />
  return (
    <svg
      className="ph-cover-pattern"
      width="100%"
      height="100%"
      preserveAspectRatio="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>{patternDef(pattern)}</defs>
      <rect width="100%" height="100%" fill={`url(#ph-${pattern})`} />
    </svg>
  )
}

function patternDef(pattern: Exclude<CoverPattern, 'circles'>) {
  switch (pattern) {
    case 'dots':
      // iOS: spacing 16, radius 2.5, 圓點置於 spacing/2 grid
      return (
        <pattern id="ph-dots" width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="8" cy="8" r="2.5" fill="white" fillOpacity={OP} />
        </pattern>
      )
    case 'lines':
      // iOS: 斜紋 spacing 12, lineWidth 1.5（45°）
      return (
        <pattern
          id="ph-lines"
          width="12"
          height="12"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line x1="0" y1="0" x2="0" y2="12" stroke="white" strokeOpacity={OP} strokeWidth="1.5" />
        </pattern>
      )
    case 'grid':
      // iOS: 方格 spacing 20, lineWidth 0.8
      return (
        <pattern id="ph-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M0 0H20M0 0V20" stroke="white" strokeOpacity={OP} strokeWidth="0.8" fill="none" />
        </pattern>
      )
    case 'waves':
      // iOS: sin 波 amplitude 8 / wavelength 30 / row-spacing 20 / lineWidth 1.2
      return (
        <pattern id="ph-waves" width="30" height="20" patternUnits="userSpaceOnUse">
          <path
            d="M0 10 C 7.5 2, 7.5 2, 15 10 S 22.5 18, 30 10"
            stroke="white"
            strokeOpacity={OP}
            strokeWidth="1.2"
            fill="none"
          />
        </pattern>
      )
  }
}

/** circles：置中同心圓，ring step 15, lineWidth 1.0（iOS `.circles`）。 */
function CirclesOverlay() {
  const rings = [15, 30, 45, 60, 75, 90, 105, 120, 135, 150]
  return (
    <svg
      className="ph-cover-pattern"
      width="100%"
      height="100%"
      preserveAspectRatio="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {rings.map((r) => (
        <circle
          key={r}
          cx="50%"
          cy="50%"
          r={r}
          fill="none"
          stroke="white"
          strokeOpacity={OP}
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  )
}
