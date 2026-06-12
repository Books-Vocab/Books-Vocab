import type { SVGProps } from 'react'
import { makeGlyph } from '../../shared/glyph'

/**
 * Settings · Preferences row glyphs — SF-Symbols-style，24×24 grid，stroke:currentColor，
 * 純裝飾（aria-hidden）。形狀沿用 settings/icons.tsx 的同名符號（同一 iOS 元件家族），
 * 在地化定義避免跨 surface import 耦合。
 */

/** SF `slider.horizontal.3` — 偏好 section header（與 settings/icons SlidersIcon 同形）。 */
export const SlidersIcon = makeGlyph(
  '<path d="M4 7h7M15 7h5M4 12h2.5M10.5 12H20M4 17h9M17 17h3"/>' +
    '<circle cx="13" cy="7" r="1.9"/><circle cx="8.5" cy="12" r="1.9"/><circle cx="15" cy="17" r="1.9"/>',
)

/** SF `circle.lefthalf.filled` — 外觀列。 */
export const AppearanceIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.4"/>' +
    '<path d="M12 3.6a8.4 8.4 0 0 0 0 16.8z" fill="currentColor" stroke="none"/>',
)

/** SF `textformat.abc` → iOS 渲染為「甲乙丙」字樣（翻譯語言列）。 */
export function TranslateIcon({ size = 24, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false" {...rest}>
      <text
        x="12"
        y="16"
        textAnchor="middle"
        fontSize="9"
        fontWeight="600"
        fill="currentColor"
        style={{ fontFamily: 'inherit' }}
      >
        甲乙丙
      </text>
    </svg>
  )
}

/** SF `character.bubble` — 語言列（字泡）。 */
export function LanguageBubbleIcon({ size = 24, strokeWidth = 1.7, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d="M12 4.2c4.9 0 8.4 3 8.4 7.2s-3.5 7.2-8.4 7.2c-.7 0-1.4-.1-2-.2L6 20.2l.8-3.1c-1.9-1.3-3.2-3.3-3.2-5.7 0-4.2 3.5-7.2 8.4-7.2z" />
      <text x="12" y="14.6" textAnchor="middle" fontSize="8" fontWeight="600" fill="currentColor" stroke="none" style={{ fontFamily: 'inherit' }}>
        字
      </text>
    </svg>
  )
}

/** SF `timer` — 複習節奏列。 */
export const TimerIcon = makeGlyph('<circle cx="12" cy="13" r="7.6"/>' + '<path d="M12 13l3.2-3.2M10 3.4h4"/>')

/** SF `arrow.triangle.2.circlepath` — 自動同步列。 */
export const SyncIcon = makeGlyph(
  '<path d="M5.2 10a7 7 0 0 1 12-2.5l1.6 1.8M18.8 14a7 7 0 0 1-12 2.5l-1.6-1.8"/>' +
    '<path d="M18.9 5.2v4.1h-4.1M5.1 18.8v-4.1h4.1"/>',
)

/** SF `chevron.right` — navigation row trailing（iconTiny 10 thin）。 */
export const ChevronRightIcon = makeGlyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')

/** SF `chevron.up.chevron.down` — Menu picker trailing（iconTiny 10 thin）。 */
export const ChevronUpDownIcon = makeGlyph('<path d="M8 10.5 12 6l4 4.5M8 13.5 12 18l4-4.5"/>')
