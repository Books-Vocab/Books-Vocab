import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for Settings — 與 bookshelf/icons.tsx 同一視覺
 * 語言：24×24 grid、線條 stroke:currentColor；實心符號（checkmark.circle.fill
 * 等）另用 fill 工廠。glyph 純裝飾（aria-hidden），語意掛在外層元素。
 */
function glyph(paths: string) {
  return function Glyph({ size = 24, strokeWidth = 1.7, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
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
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}

/** 實心符號工廠（checkmark.circle.fill / apple.logo 等 filled glyph）。 */
function filledGlyph(paths: string) {
  return function FilledGlyph({ size = 24, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="currentColor"
        stroke="none"
        aria-hidden="true"
        focusable="false"
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}

/** SF `person.crop.circle` — 帳號 section header。 */
export const PersonCircleIcon = glyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<circle cx="12" cy="9.6" r="3.1"/>' +
    '<path d="M5.8 18.6c1.2-2.6 3.5-4 6.2-4s5 1.4 6.2 4"/>',
)

/** SF `slider.horizontal.3` — 偏好 section header。 */
export const SlidersIcon = glyph(
  '<path d="M4 7h7M15 7h5M4 12h2.5M10.5 12H20M4 17h9M17 17h3"/>' +
    '<circle cx="13" cy="7" r="1.9"/><circle cx="8.5" cy="12" r="1.9"/><circle cx="15" cy="17" r="1.9"/>',
)

/** SF `ellipsis.circle` — 其他 section header。 */
export const EllipsisCircleIcon = glyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<circle cx="7.5" cy="12" r="0.4"/><circle cx="12" cy="12" r="0.4"/><circle cx="16.5" cy="12" r="0.4"/>',
)

/** SF `circle.lefthalf.filled` — 外觀列。 */
export const AppearanceIcon = glyph(
  '<circle cx="12" cy="12" r="8.4"/>' +
    '<path d="M12 3.6a8.4 8.4 0 0 0 0 16.8z" fill="currentColor" stroke="none"/>',
)

/** 翻譯語言列 — iOS 圖示為「甲乙丙」字樣（character variant）。 */
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
export const TimerIcon = glyph(
  '<circle cx="12" cy="13" r="7.6"/>' +
    '<path d="M12 13l3.2-3.2M10 3.4h4"/>',
)

/** SF `arrow.triangle.2.circlepath` — 自動同步／同步狀態列。 */
export const SyncIcon = glyph(
  '<path d="M5.2 10a7 7 0 0 1 12-2.5l1.6 1.8M18.8 14a7 7 0 0 1-12 2.5l-1.6-1.8"/>' +
    '<path d="M18.9 5.2v4.1h-4.1M5.1 18.8v-4.1h4.1"/>',
)

/** SF `hand.raised` — 隱私政策列。 */
export const HandRaisedIcon = glyph(
  '<path d="M8.6 12.6V5.9a1.2 1.2 0 0 1 2.4 0v5.3V4.6a1.2 1.2 0 0 1 2.4 0v6.6-5.5a1.2 1.2 0 0 1 2.4 0v6.3-4.4a1.2 1.2 0 0 1 2.4 0v7.5c0 3.4-2.4 5.9-5.8 5.9-2.3 0-3.8-.8-5-2.6L5.1 14.7c-.6-.9-.5-1.8.2-2.3.7-.5 1.6-.3 2.2.5z"/>',
)

/** SF `doc.text` — 服務條款列。 */
export const DocTextIcon = glyph(
  '<path d="M7 3.5h7l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1-1.5z"/>' +
    '<path d="M14 3.5V8h4.3M9 12h6M9 15.5h6"/>',
)

/** SF `questionmark.circle` — 支援列。 */
export const QuestionCircleIcon = glyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M9.6 9.4a2.5 2.5 0 0 1 4.9.6c0 1.6-2.4 2-2.4 3.4"/>' +
    '<circle cx="12" cy="16.8" r="0.4"/>',
)

/** SF `star` — 為 App 評分列。 */
export const StarIcon = glyph(
  '<path d="M12 4.4l2.2 4.7 5 .6-3.7 3.5 1 5-4.5-2.5-4.5 2.5 1-5-3.7-3.5 5-.6z"/>',
)

/** SF `checkmark.circle.fill` — 帳號列右側綠勾。 */
export const CheckCircleFillIcon = filledGlyph(
  '<path d="M12 2.6A9.4 9.4 0 1 0 21.4 12 9.4 9.4 0 0 0 12 2.6zm-1.5 13.6l-3.6-3.6 1.4-1.4 2.2 2.2 5.2-5.2 1.4 1.4z"/>',
)

/** SF `checkmark.seal.fill` — 訂閱列（active）。 */
export const SealCheckFillIcon = filledGlyph(
  '<path fill-rule="evenodd" clip-rule="evenodd" d="M12 2.2l2 1.7 2.6-.4 1 2.4 2.4 1-.4 2.6 1.7 2-1.7 2 .4 2.6-2.4 1-1 2.4-2.6-.4-2 1.7-2-1.7-2.6.4-1-2.4-2.4-1 .4-2.6-1.7-2 1.7-2-.4-2.6 2.4-1 1-2.4 2.6.4zm-1.4 12.9l-2.8-2.8 1.2-1.2 1.6 1.6 4.4-4.4 1.2 1.2z"/>',
)

/** SF `sparkles` — PRO badge／升級列。 */
export const SparklesIcon = filledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `chevron.right` — navigation row trailing。 */
export const ChevronRightIcon = glyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')

/** SF `apple.logo` — Apple 登入按鈕 badge。 */
export const AppleLogoIcon = filledGlyph(
  '<path d="M16.6 12.7c0-2 1.6-3 1.7-3-1-1.4-2.4-1.6-2.9-1.6-1.2-.1-2.4.7-3 .7-.6 0-1.6-.7-2.6-.7-1.3 0-2.6.8-3.3 2-1.4 2.4-.4 6 1 8 .7 1 1.5 2.1 2.5 2 1 0 1.4-.6 2.6-.6s1.5.6 2.6.6c1.1 0 1.8-1 2.4-2 .8-1.1 1.1-2.2 1.1-2.3 0 0-2.1-.8-2.1-3.1zM14.6 6.7c.5-.7.9-1.6.8-2.6-.8 0-1.8.6-2.3 1.2-.5.6-1 1.6-.8 2.5.9.1 1.8-.4 2.3-1.1z"/>',
)

