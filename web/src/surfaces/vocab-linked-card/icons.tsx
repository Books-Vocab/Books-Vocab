import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for LinkedCardOverlayStack — 24×24 grid、stroke:currentColor、純裝飾。
 * 對應 iOS `Image(systemName:)`：
 *   - rectangle.stack（VocabOverlayHeader systemImage，caption=sans 12 → 視覺 ~16）：堆疊矩形。
 *   - doc.text（VocabStateMessageCard「載入中」前綴 icon，iconSmall=symbol 12 medium /accent）。
 *   - xmark（close button，iconMedium=symbol 14 medium /secondaryText）。
 */

/** SF `rectangle.stack` — header 前綴：兩張上下錯位的矩形。 */
export const RectangleStackIcon = makeGlyph(
  '<rect x="5.5" y="8.5" width="13" height="10" rx="2"/><path d="M7.5 5.5h9"/>',
  { size: 16, strokeWidth: 1.5 },
)

/** SF `doc.text` — 「載入中」前綴：文件 + 折角 + 文字線。 */
export const DocTextIcon = makeGlyph(
  '<path d="M6.5 4.5h6l5 5v10a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1z"/><path d="M12.5 4.5v5h5"/><path d="M8.5 13h6"/><path d="M8.5 16h6"/>',
  { size: 18, strokeWidth: 1.5 },
)

/** SF `xmark` — close button 內的叉。 */
export const XmarkIcon = makeGlyph('<path d="M6 6 18 18"/><path d="M18 6 6 18"/>', {
  size: 17,
  strokeWidth: 1.6,
})
