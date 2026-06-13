import { makeGlyph } from './glyph'

/**
 * SF-Symbols-style glyphs for shared VocabSceneShell — 24×24 grid、stroke
 * currentColor、純裝飾。對齊 VocabSceneShellScenarios.swift 各態使用的 SF symbol。
 */

/** SF `arrow.clockwise` — Loading 態 hero 圖示（順時針箭頭）。 */
export const ArrowClockwiseIcon = makeGlyph(
  '<path d="M19 12a7 7 0 1 1-2.05-4.95"/>' +
    '<path d="M19 4.5V8h-3.5"/>',
)

/** SF `sparkles` — Empty「尚無已收錄單字」hero 圖示（三顆閃光）。 */
export const SparklesIcon = makeGlyph(
  '<path d="M12 4.2l1.4 3.6 3.6 1.4-3.6 1.4L12 14.2l-1.4-3.6L7 9.2l3.6-1.4z"/>' +
    '<path d="M18 14l.7 1.8 1.8.7-1.8.7L18 19l-.7-1.8-1.8-.7 1.8-.7z"/>' +
    '<path d="M6.5 14.5l.5 1.3 1.3.5-1.3.5-.5 1.3-.5-1.3-1.3-.5 1.3-.5z"/>',
)

/** SF `magnifyingglass` — Empty「沒有符合的單字」hero 圖示。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)

/** SF `exclamationmark.triangle` — Error「無法載入單字」hero 圖示。 */
export const ExclamationmarkTriangleIcon = makeGlyph(
  '<path d="M12 4.8 20.5 19.2H3.5z"/>' +
    '<path d="M12 10v4"/><path d="M12 16.6h.01"/>',
)

/** SF `book` — Empty CTA「前往閱讀」按鈕 Label 圖示。 */
export const BookIcon = makeGlyph(
  '<path d="M12 6.2C10.3 4.9 8.1 4.4 5.5 4.4c-.9 0-1.5.7-1.5 1.5v11.3c0 .9.7 1.5 1.6 1.5 2.4.1 4.6.6 6.4 1.9 1.8-1.3 4-1.8 6.4-1.9.9 0 1.6-.6 1.6-1.5V5.9c0-.8-.6-1.5-1.5-1.5-2.6 0-4.8.5-6.5 1.8z"/>' +
    '<path d="M12 6.2v14.4"/>',
)
