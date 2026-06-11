import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for the Notebook surface — 同 settings/bookshelf 的
 * 視覺語言：24×24 grid、stroke:currentColor；實心符號另用 fill 工廠。glyph 純
 * 裝飾（aria-hidden），語意掛在外層元素。
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

/** SF `sparkles` — CTA pill（未學複習）icon；複用 settings 的 sparkles 三星形狀。 */
export const SparklesIcon = filledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `line.3.horizontal.decrease.circle` — 篩選 pill（圓圈內三條遞減橫線）。 */
export const FilterCircleIcon = glyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M7.4 9.2h9.2M8.8 12h6.4M10.4 14.8h3.2"/>',
)

/** SF `plus` — 新增 pill。 */
export const PlusIcon = glyph('<path d="M12 5.5v13M5.5 12h13"/>')
