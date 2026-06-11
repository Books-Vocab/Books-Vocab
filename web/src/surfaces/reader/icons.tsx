import type { SVGProps } from 'react'

/**
 * SF-Symbols-style glyphs for the Reader chrome — 同 notebook/settings 的視覺
 * 語言：24×24 grid、stroke:currentColor。glyph 純裝飾（aria-hidden），語意掛在
 * 外層按鈕。chrome 用的 SF symbol：book.closed / ellipsis / chevron.left /
 * list.bullet / textformat.size / text.book.closed / chevron.up /
 * exclamationmark.triangle。
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

/** SF `book.closed` — compact 進度膠囊前綴 + expanded text.book.closed 鈕共用書本形。 */
export const BookClosedIcon = glyph(
  '<rect x="5.5" y="4" width="13" height="16" rx="1.5"/>' +
    '<path d="M5.5 17.2h13"/>',
)

/** SF `ellipsis` — compact header 展開鈕（三點橫排）。 */
export const EllipsisIcon = glyph(
  '<circle cx="6" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="18" cy="12" r="0.9" fill="currentColor" stroke="none"/>',
)

/** SF `chevron.left` — expanded header 返回（書庫）。 */
export const ChevronLeftIcon = glyph('<path d="M14.5 5.5 8 12l6.5 6.5"/>')

/** SF `chevron.up` — expanded header 收起標題列。 */
export const ChevronUpIcon = glyph('<path d="M5.5 14.5 12 8l6.5 6.5"/>')

/** SF `list.bullet` — expanded header 目錄。 */
export const ListBulletIcon = glyph(
  '<path d="M9 6.5h10M9 12h10M9 17.5h10"/>' +
    '<circle cx="5" cy="6.5" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="5" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="5" cy="17.5" r="0.9" fill="currentColor" stroke="none"/>',
)

/** SF `textformat.size` — expanded header 閱讀設定（大小：大 A + 小 A）。 */
export const TextformatSizeIcon = glyph(
  '<path d="M3 17.5 6.5 7l3.5 10.5M3.9 14.5h5.2"/>' +
    '<path d="M14 17.5 16.6 10l2.6 7.5M14.6 15.3h4"/>',
)

/** SF `exclamationmark.triangle` — error 卡圖示。 */
export const WarningTriangleIcon = glyph(
  '<path d="M12 4 21 19.5H3z"/>' +
    '<path d="M12 9.5v4.5"/>' +
    '<circle cx="12" cy="16.8" r="0.95" fill="currentColor" stroke="none"/>',
)
