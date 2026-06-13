import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for VocabChromeIconButton — 24×24 grid、
 * stroke:currentColor、純裝飾。對應 iOS `Image(systemName:)` +
 * `.font(iconMedium = symbol(size:14, .medium))`。
 */

/** SF `xmark` — Close 場景關閉鈕。size 22 → glyph body ≈11pt（對齊 catalog 33px@dpr3）。 */
export const XmarkIcon = makeGlyph('<path d="M6 6 18 18M18 6 6 18"/>', {
  size: 22,
  strokeWidth: 1.9,
})

/** SF `line.3.horizontal.decrease` — Toned(filter)：三條遞減橫線。size 24 → ≈14pt 寬。 */
export const FilterDecreaseIcon = makeGlyph('<path d="M5 8.5h14M7.5 12h9M10 15.5h4"/>', {
  size: 24,
  strokeWidth: 1.9,
})
