import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for the vocab selection toolbar — 同 reader/notebook
 * 的視覺語言：24×24 grid、stroke:currentColor、glyph 純裝飾（aria-hidden）。
 * SelectionToolbar 用的 SF symbol：archivebox / trash。
 */
function glyph(paths: string) {
  return function Glyph({ size = 24, strokeWidth = 1.5, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
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

/** SF `archivebox` — 封存按鈕（蓋+箱身+把手橫槽）。 */
export const ArchiveboxIcon = glyph(
  '<path d="M4 7.5h16v2H4z"/>' +
    '<path d="M5 9.5h14V18a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18z"/>' +
    '<path d="M9.5 13h5"/>',
)

/** SF `trash` — 刪除按鈕（蓋+把手+桶身+三豎槽）。 */
export const TrashIcon = glyph(
  '<path d="M5 7h14"/>' +
    '<path d="M9.5 7V5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7"/>' +
    '<path d="M6.5 7l.9 11.2a1.5 1.5 0 0 0 1.5 1.3h6.2a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>' +
    '<path d="M10 10.5v6M14 10.5v6"/>',
)
