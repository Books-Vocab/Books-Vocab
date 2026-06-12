import type { SVGProps } from 'react'
import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/** SF `sparkles.rectangle.stack` — Section header（caption 12，secondaryText）。
 *  形狀沿用 account-section 既有鏡像。 */
export const SparklesRectangleStackIcon = makeGlyph(
  '<rect x="6.4" y="3.2" width="13" height="9.4" rx="2" fill="none"/>' +
    '<rect x="3.4" y="9.4" width="13" height="9.4" rx="2" fill="var(--card-bg, #fff)"/>' +
    '<path d="M8 11.6l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7zM12.4 14.6l.4 1.1 1.1.4-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4z" fill="currentColor" stroke="none"/>',
)

/** SF `key` — 「權限來源」row 前導圖示（iconSmall 12 medium，secondaryText）。 */
export const KeyIcon = makeGlyph(
  '<circle cx="8" cy="8" r="3.4"/>' +
    '<path d="M10.4 10.4 19 19M15.6 15.6l2-2M17.6 13.6l1.8 1.8"/>',
)

/** SF `wrench.and.screwdriver` — 「管理方式」row 前導圖示。 */
export const WrenchScrewdriverIcon = makeGlyph(
  '<path d="M14.3 4.2a3.5 3.5 0 0 0 4.5 4.5L20 9.9a4.8 4.8 0 0 1-6.6-6.6z"/>' +
    '<path d="M13.4 9.4 5.2 17.6a1.7 1.7 0 0 0 2.4 2.4l8.2-8.2"/>' +
    '<path d="M5.5 4.2 9 7.7M4.2 5.5 7.7 9M4 4l1.6 1.6"/>',
)

/** SF `arrow.clockwise` — 「恢復購買」row 前導圖示。 */
export const ArrowClockwiseIcon = makeGlyph(
  '<path d="M19 6.5v4h-4"/>' +
    '<path d="M18.4 10.5A7 7 0 1 0 19 13"/>',
)

/** SF `info.circle` — Pricing-unavailable 卡片標題圖示（iconSmall 12，accent）。 */
export const InfoCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.5"/>' +
    '<path d="M12 11v5"/>' +
    '<path d="M12 7.6h.01"/>',
)

/** SF `arrow.clockwise.circle` — Pricing-unavailable refreshing 變體標題圖示。 */
export const ArrowClockwiseCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.5"/>' +
    '<path d="M15.5 9v2.4h-2.4"/>' +
    '<path d="M15.1 11.4A3.4 3.4 0 1 0 15.5 13"/>',
)

/** SF `arrow.right.circle.fill` — CTA 前導圖示（iconMedium 14，primaryText，實心）。 */
export const ArrowRightCircleFillIcon = makeFilledGlyph(
  '<path d="M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z" />' +
    '<path d="M11 8.2 14.8 12 11 15.8M14.4 12H7.6" fill="none" stroke="var(--card-bg, #fff)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
)

/** SF `chevron.right` — CTA / row trailing（iconTiny 10 thin，tertiaryText）。 */
export const ChevronRightIcon = makeGlyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')

/** ProgressView(.small) 替身 — CTA isRefreshing / pricing refreshing 的 spinner。
 *  iOS 用 system spinner；以 12-輻條灰圈鏡像（mono 視覺密度）。 */
export function SpinnerIcon({ size = 18, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
  const spokes = Array.from({ length: 12 }, (_, i) => {
    const angle = (i * 30 * Math.PI) / 180
    const x1 = 12 + 5 * Math.cos(angle)
    const y1 = 12 + 5 * Math.sin(angle)
    const x2 = 12 + 8.5 * Math.cos(angle)
    const y2 = 12 + 8.5 * Math.sin(angle)
    return (
      <line
        key={i}
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        opacity={0.25 + (i / 12) * 0.75}
      />
    )
  })
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {spokes}
    </svg>
  )
}
