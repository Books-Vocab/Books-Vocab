import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style line glyphs — 與 chrome-extension/shared/icons.js 同一
 * 視覺語言：24×24 grid、fill:none、stroke:currentColor（無 Apple 資產，
 * 手繪幾何線條）。glyph 純裝飾（aria-hidden），語意掛在外層元素。
 */

/** SF `book` — 攤開的書（封面 placeholder 與空書架共用）。 */
export const BookIcon = makeGlyph(
  '<path d="M12 6.2C10.3 4.9 8.1 4.4 5.5 4.4c-.9 0-1.5.7-1.5 1.5v11.3c0 .9.7 1.5 1.6 1.5 2.4.1 4.6.6 6.4 1.9 1.8-1.3 4-1.8 6.4-1.9.9 0 1.6-.6 1.6-1.5V5.9c0-.8-.6-1.5-1.5-1.5-2.6 0-4.8.5-6.5 1.8z"/>' +
    '<path d="M12 6.2v14.4"/>',
)

/** SF `icloud.and.arrow.down` — 雲＋下載箭頭（iCloud 待下載徽章）。 */
export const ICloudArrowDownIcon = makeGlyph(
  '<path d="M7.5 13.2h-.8a3.6 3.6 0 0 1-.4-7.2 5 5 0 0 1 9.8-.6 4 4 0 0 1 1 7.6"/>' +
    '<path d="M12 11v8M9 16.3 12 19.4l3-3.1"/>',
)

/** SF `ellipsis` — 書卡 more 選單觸發鈕（三點橫排）。 */
export const EllipsisIcon = makeGlyph(
  '<circle cx="6" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none"/>' +
    '<circle cx="18" cy="12" r="0.9" fill="currentColor" stroke="none"/>',
)

/** SF `pencil` — more 選單「改名」選項。 */
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

/** SF `doc` — 匯入 sheet 檔案 picker 視覺（單頁文件）。 */
export const DocIcon = makeGlyph(
  '<path d="M7 3.5h6.5L18 8v12.5H7z"/>' + '<path d="M13.5 3.5V8H18"/>',
)

/** SF `bookmark` — more 選單「綁定單字本」選項（書籤）。 */
export const BookmarkIcon = makeGlyph(
  '<path d="M6.5 4.5h11v15l-5.5-3.6-5.5 3.6z"/>',
)

/** SF `checkmark` — 綁定 picker 選中標記。 */
export const CheckIcon = makeGlyph('<path d="M5 12.5 10 17.5 19 6.5"/>')
