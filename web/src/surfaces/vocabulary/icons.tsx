import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for the Vocabulary surface — 同 notebook/settings 視覺
 * 語言：24×24 grid、stroke:currentColor。glyph 純裝飾（aria-hidden）。
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

/** SF `magnifyingglass` — 搜尋欄前綴 + no-match empty state。 */
export const MagnifyingGlassIcon = glyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)

/** SF `arrow.up.arrow.down` — sort pill。 */
export const SortIcon = glyph(
  '<path d="M7 4v15M7 19l-3-3M7 19l3-3M17 20V5M17 5l-3 3M17 5l3 3"/>',
)

/** SF `sparkles` — 未學複習 CTA pill；複用 notebook/settings 的三星形狀。 */
export const SparklesIcon = filledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `books.vertical` — zero-data empty state（三本直立書，皆 upright）。 */
export const BooksIcon = glyph(
  '<rect x="3.5" y="5" width="4" height="14" rx="0.9"/>' +
    '<rect x="9" y="5" width="4" height="14" rx="0.9"/>' +
    '<rect x="14.5" y="5" width="4" height="14" rx="0.9"/>' +
    '<path d="M3.5 8.5h4M9 8.5h4M14.5 8.5h4"/>',
)

/** SF `arrow.clockwise` — zero-data CTA 按鈕（重新整理）。 */
export const RefreshIcon = glyph(
  '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v4h-4"/>',
)
