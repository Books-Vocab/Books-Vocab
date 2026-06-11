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
