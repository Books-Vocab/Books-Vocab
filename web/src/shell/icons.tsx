import type { SVGProps } from 'react'

/**
 * Tab-bar SF-Symbol-style line glyphs，沿用各 surface icons.tsx 的 glyph 工廠
 * 慣例：24×24 grid、fill:none、stroke:currentColor、純裝飾（aria-hidden）。
 * 對應 iOS AppPrimarySection.systemImage（ContentView.swift）：
 *   bookshelf  → books.vertical
 *   podcasts   → waveform
 *   notebooks  → character.book.closed
 *   overview   → chart.bar
 */
function glyph(paths: string) {
  return function Glyph({ size = 25, strokeWidth = 1.7, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
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

/** SF `books.vertical` — 三本直立書。 */
export const BooksVerticalIcon = glyph(
  '<rect x="3.5" y="4.5" width="3.4" height="15" rx="0.8"/>' +
    '<rect x="8.3" y="4.5" width="3.4" height="15" rx="0.8"/>' +
    '<path d="M13.6 6.1 16.9 5l3.2 13.9-3.3 1.1z"/>',
)

/** SF `waveform` — 等化器豎條。 */
export const WaveformIcon = glyph(
  '<path d="M4 10v4"/><path d="M8 7v10"/><path d="M12 4v16"/><path d="M16 7v10"/><path d="M20 10v4"/>',
)

/** SF `character.book.closed` — 闔起的書（單字本）。 */
export const CharacterBookClosedIcon = glyph(
  '<path d="M6 3.5h11a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2z"/>' +
    '<path d="M4 17.5a2 2 0 0 1 2-2h12"/>' +
    '<path d="M9.2 11.3h3.6M11 8.4v5.4"/>',
)

/** SF `chart.bar` — 水平長條圖（總覽）。 */
export const ChartBarIcon = glyph(
  '<path d="M4 5.5h9"/><path d="M4 12h13"/><path d="M4 18.5h6"/>',
)

/** SF `chevron.left` — back chevron（push/pop 導航）。 */
export const ChevronLeftIcon = glyph('<path d="M14.5 5.5 8 12l6.5 6.5"/>')
