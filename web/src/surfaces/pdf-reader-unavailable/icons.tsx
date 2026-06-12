import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for PDF Reader Unavailable — 24×24 grid、stroke
 * currentColor、純裝飾。對齊 PDFReaderView.errorView 用的 SF symbol：
 *   hero = "exclamationmark.triangle"（無法開啟 PDF）
 *   CTA  = "arrow.clockwise"（重試載入 Label icon）
 */

/** SF `exclamationmark.triangle`（outline）— error hero（三角警示 + 驚嘆號）。 */
export const ExclamationTriangleIcon = makeGlyph(
  '<path d="M12 3.6L21.5 20H2.5z"/>' +
    '<path d="M12 9.4v5"/>' +
    '<path d="M12 17.4h0.01"/>',
)

/** SF `arrow.clockwise` — 「重試載入」CTA Label icon。沿用既有鏡像形狀。 */
export const RefreshIcon = makeGlyph(
  '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v4h-4"/>',
)
