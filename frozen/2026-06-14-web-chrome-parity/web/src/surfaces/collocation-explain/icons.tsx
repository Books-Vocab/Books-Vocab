import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for CollocationExplainSheet footer chrome buttons —
 * 24×24 grid、stroke:currentColor、純裝飾。對應 iOS `VocabChromeIconButton`
 * 內 `Image(systemName:).font(iconMedium = symbol(size:14, .medium))`。
 *
 * 視覺尺寸與 strokeWidth 對齊既有 `vocab-chrome-icon-button` surface 的 xmark
 * （size 22 / strokeWidth 1.9 → 32pt card 內 glyph body ≈ catalog 33px@dpr3），
 * 兩鈕等大。
 */

/** SF `trash` — destructive 刪除鈕。形狀沿用 selection/vocab-accessory 的 trash。 */
export const TrashIcon = makeGlyph(
  '<path d="M5 7h14"/>' +
    '<path d="M9.5 7V5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7"/>' +
    '<path d="M6.5 7l.9 11.2a1.5 1.5 0 0 0 1.5 1.3h6.2a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>' +
    '<path d="M10 10.5v6M14 10.5v6"/>',
  { size: 22, strokeWidth: 1.7 },
)

/** SF `xmark` — 關閉鈕。沿用 vocab-chrome-icon-button 的 xmark 形狀與尺寸。 */
export const XmarkIcon = makeGlyph('<path d="M6 6 18 18M18 6 6 18"/>', {
  size: 22,
  strokeWidth: 1.9,
})
