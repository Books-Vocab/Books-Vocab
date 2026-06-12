import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyph for VocabToolbarGlyph — 24×24 grid、stroke:currentColor、
 * 純裝飾。形狀與 settings 的 SyncIcon 同源（SF `arrow.triangle.2.circlepath`），
 * 此處複製路徑保持 surface 自足。
 */

/** SF `arrow.triangle.2.circlepath` — VocabToolbarGlyph 預設圖示（雙箭頭循環）。 */
export const SyncIcon = makeGlyph(
  '<path d="M5.2 10a7 7 0 0 1 12-2.5l1.6 1.8M18.8 14a7 7 0 0 1-12 2.5l-1.6-1.8"/>' +
    '<path d="M18.9 5.2v4.1h-4.1M5.1 18.8v-4.1h4.1"/>',
)
