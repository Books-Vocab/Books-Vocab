import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyph for VocabAccessoryIconButton — 24×24 grid、
 * stroke:currentColor。形狀沿用 selection/icons.tsx 的 `trash`（蓋+把手+桶身+
 * 三豎槽），對應 iOS `Image(systemName: "trash")`。
 */

/** SF `trash` — accessory icon button「刪除」圖示（destructive 系統紅）。 */
export const TrashIcon = makeGlyph(
  '<path d="M5 7h14"/>' +
    '<path d="M9.5 7V5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7"/>' +
    '<path d="M6.5 7l.9 11.2a1.5 1.5 0 0 0 1.5 1.3h6.2a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>' +
    '<path d="M10 10.5v6M14 10.5v6"/>',
  { size: 26, strokeWidth: 1.6 },
)
