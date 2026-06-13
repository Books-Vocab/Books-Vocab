import type { ScenarioId } from '../../harness/scenarios'
import { PODCAST_HERO_FIXTURES, HERO_COVER_COLOR } from './fixtures'
import './podcast-hero.css'

/**
 * Podcast Hero surface — web mirror of iOS `PodcastSeriesHero`
 * (Views/Podcast/PodcastSeriesHero.swift).
 *
 * iOS view tree:
 *   VStack(spacing: statusHeroGap=12) {
 *     backdrop (band height 196, full-width)            // ambient glow + floating cover
 *       .overlay { NotebookCoverView(136×136, radius md=8, z3 elevation) }
 *     Text(title)  font displayTitle(serif 24 bold) / primaryText, center, lineLimit 3
 *     if meta { Text(meta) font caption(sans 12 bold) / tertiaryText, center, lineLimit 2 }
 *   }
 *
 * backdrop = ZStack {
 *   LinearGradient(top→bottom)[coverColor·0.42, coverColor·0.12, .clear]
 *   // coverImagePath nil here → no blurred artwork layer
 * }.frame(height 196).overlay { LinearGradient[.clear,.clear,pageBackground] }  // bottom fade
 *
 * NotebookCoverView (no image, pattern .waves):
 *   ZStack { color · waves Canvas(white 0.12) · Text(name) body(sans 17 semibold) white + shadow,
 *            lineLimit 2, minimumScaleFactor 0.85, center, .padding(.horizontal s2=8) }
 *   cover color = #AFC2D3 (series.color #4A90D9 → legacyMigration, render-time DATA color).
 *
 * catalog scene layout = .fill (full device frame 1179×2556, canvas transparent
 * corner srgba 0,0,0,0). Content top-anchored within the centered band region —
 * ref shows the hero vertically centered in the frame. web = full phone-frame
 * capture (NO crop=component): surface fills 393×852, content vertically centered;
 * phone-frame transparent, shots transparent:true → content-over-transparent.
 */
export function PodcastHeroScreen({ scenario }: { scenario: ScenarioId<'podcast-hero'> }) {
  const fixture = PODCAST_HERO_FIXTURES[scenario]
  return (
    <div className="podcast-hero-surface" data-a11y3={fixture.a11y3 ? '1' : undefined}>
      <div className="podcast-hero">
        <div
          className="podcast-hero-backdrop"
          style={{ ['--hero-cover-color' as string]: HERO_COVER_COLOR }}
        >
          <div className="podcast-hero-backdrop-wash" />
          <div className="podcast-hero-backdrop-fade" />
          <div className="podcast-hero-cover">
            <CoverWaves />
            <div className="podcast-hero-cover-name">{fixture.title}</div>
          </div>
        </div>

        <div className="podcast-hero-title">{fixture.title}</div>

        {fixture.meta ? <div className="podcast-hero-meta">{fixture.meta}</div> : null}
      </div>
    </div>
  )
}

/**
 * waves pattern overlay — mirrors NotebookCoverPattern.waves Canvas:
 * amplitude 8, wavelength 30, row spacing 20, white opacity 0.12 (patternOpacity),
 * lineWidth 1.2. Cover is 136×136; rows from y=10 stepping 20.
 */
function CoverWaves() {
  const size = 136
  const amplitude = 8
  const wavelength = 30
  const spacing = 20
  const rows: string[] = []
  for (let yOffset = spacing / 2; yOffset < size + amplitude; yOffset += spacing) {
    let d = `M 0 ${yOffset}`
    for (let x = 0; x <= size; x += 2) {
      const y = yOffset + amplitude * Math.sin((x / wavelength) * Math.PI * 2)
      d += ` L ${x} ${y.toFixed(2)}`
    }
    rows.push(d)
  }
  return (
    <svg
      className="podcast-hero-cover-waves"
      viewBox={`0 0 ${size} ${size}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {rows.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={1.2} />
      ))}
    </svg>
  )
}
