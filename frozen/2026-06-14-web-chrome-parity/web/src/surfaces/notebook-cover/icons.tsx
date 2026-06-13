import type { CoverPattern } from './fixtures'

/**
 * NotebookCoverPattern.patternOverlay 的 web 鏡像 — 逐 case 對齊 iOS Canvas 幾何
 * （spacing / radius / lineWidth / amplitude 等以 point 為單位，SVG userSpaceOnUse
 * tile 鏡射）。白色 stroke/fill opacity = NotebookStackMetrics.patternOpacity(0.12)，
 * 走 --notebook-cover-pattern-opacity token；noise 的 per-pixel 動態 opacity 為視覺
 * 特色，以離散 tile 的固定淡白近似（iOS max ≈ 0.15）。
 *
 * overlay 鋪滿 cover box（width/height 100%），allowsHitTesting=false → pointer-events none。
 */

const OP = 'var(--notebook-cover-pattern-opacity)'

export function PatternOverlay({ pattern }: { pattern: CoverPattern }) {
  return (
    <svg
      className="nbc-pattern"
      width="100%"
      height="100%"
      preserveAspectRatio="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>{patternDef(pattern)}</defs>
      <rect width="100%" height="100%" fill={`url(#nbc-${pattern})`} />
    </svg>
  )
}

function patternDef(pattern: CoverPattern) {
  switch (pattern) {
    case 'dots':
      // spacing 16, radius 2.5, dots centred at spacing/2 grid
      return (
        <pattern id="nbc-dots" width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="8" cy="8" r="2.5" fill="white" fillOpacity={OP} />
        </pattern>
      )
    case 'lines':
      // diagonal stripes, spacing 12 along x, slope down-left (move x,0 → x-h,h)
      return (
        <pattern
          id="nbc-lines"
          width="12"
          height="12"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line x1="0" y1="0" x2="0" y2="12" stroke="white" strokeOpacity={OP} strokeWidth="1.5" />
        </pattern>
      )
    case 'grid':
      // square grid spacing 20, lineWidth 0.8
      return (
        <pattern id="nbc-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M0 0H20M0 0V20" stroke="white" strokeOpacity={OP} strokeWidth="0.8" fill="none" />
        </pattern>
      )
    case 'waves':
      // sine waves: amplitude 8, wavelength 30, row spacing 20, lineWidth 1.2
      // one tile = wavelength 30 wide × spacing 20 tall, baseline at amplitude offset
      return (
        <pattern id="nbc-waves" width="30" height="20" patternUnits="userSpaceOnUse">
          <path
            d="M0 10 C 7.5 2, 7.5 2, 15 10 S 22.5 18, 30 10"
            stroke="white"
            strokeOpacity={OP}
            strokeWidth="1.2"
            fill="none"
          />
        </pattern>
      )
    case 'circles':
      // concentric rings centred on box, ring step 15, lineWidth 1.0
      // approximate via radial tiling is impossible; render explicit centred rings
      return null
    case 'noise':
      // per-pixel random ~4px tiles, white max ≈0.15; approximate as sparse fixed-opacity dots
      return (
        <pattern id="nbc-noise" width="16" height="16" patternUnits="userSpaceOnUse">
          <rect x="0" y="4" width="4" height="4" fill="white" fillOpacity="0.10" />
          <rect x="8" y="0" width="4" height="4" fill="white" fillOpacity="0.13" />
          <rect x="4" y="8" width="4" height="4" fill="white" fillOpacity="0.08" />
          <rect x="12" y="12" width="4" height="4" fill="white" fillOpacity="0.12" />
          <rect x="12" y="4" width="4" height="4" fill="white" fillOpacity="0.06" />
          <rect x="0" y="12" width="4" height="4" fill="white" fillOpacity="0.11" />
        </pattern>
      )
  }
}

/** circles pattern 走獨立 SVG（centred concentric rings，無法用 tile）。 */
export function CirclesOverlay() {
  // 同心圓：centre (50%,50%)，ring step 15，maxRadius = max(w,h)/2。
  // box 高 96 → centreY 48；以 % 半徑近似多環（15,30,45,60,75... 相對 box 高）。
  const rings = [15, 30, 45, 60, 75, 90, 105, 120, 135, 150]
  return (
    <svg
      className="nbc-pattern"
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
