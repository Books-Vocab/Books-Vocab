import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Notebook surface — 同 settings/bookshelf 的
 * 視覺語言：24×24 grid、stroke:currentColor；實心符號另用 fill 工廠。glyph 純
 * 裝飾（aria-hidden），語意掛在外層元素。
 */

/** SF `sparkles` — CTA pill（未學複習）icon；複用 settings 的 sparkles 三星形狀。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `line.3.horizontal.decrease.circle` — 篩選 pill（圓圈內三條遞減橫線）。 */
export const FilterCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M7.4 9.2h9.2M8.8 12h6.4M10.4 14.8h3.2"/>',
)

/** SF `plus` — 新增 pill。 */
export const PlusIcon = makeGlyph('<path d="M12 5.5v13M5.5 12h13"/>')

/** SF `ellipsis` — notebook card more 選單觸發鈕（三點橫排）。 */
export const EllipsisIcon = makeGlyph(
  '<circle cx="6" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="18" cy="12" r="0.9" fill="currentColor" stroke="none"/>',
)

/** SF `pencil` — more 選單「編輯」選項。 */
export const PencilIcon = makeGlyph(
  '<path d="M4.5 19.5l1-3.6L15 6.4l2.6 2.6L8 18.5z"/>' + '<path d="M13.4 8.4l2.6 2.6"/>',
)

/** SF `trash` — more 選單「刪除」選項（destructive tone）。 */
export const TrashIcon = makeGlyph(
  '<path d="M5 6.5h14"/>' +
    '<path d="M9 6.5V4.8h6v1.7"/>' +
    '<path d="M6.5 6.5 7.4 19.2h9.2L17.5 6.5"/>' +
    '<path d="M10 10v6M14 10v6"/>',
)

/** SF `xmark` — sheet 關閉鈕。 */
export const XmarkIcon = makeGlyph('<path d="M6 6 18 18M18 6 6 18"/>')
