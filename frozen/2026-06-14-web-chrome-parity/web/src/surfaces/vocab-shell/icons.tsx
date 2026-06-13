import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Vocab Shell primitive layer — 同 reader/
 * notebook/selection 的視覺語言：24×24 grid、stroke:currentColor、純裝飾。
 */

/** SF `arrow.up.arrow.down` — VocabSortPill 前導圖示（左箭頭朝上 + 右箭頭朝下）。 */
export const SortArrowsIcon = makeGlyph(
  // 左：朝上箭頭（stem + 頂端 chevron）
  '<path d="M8.5 18.5V6.8"/><path d="M5.5 9.8 8.5 6.5l3 3.3"/>' +
    // 右：朝下箭頭（stem + 底端 chevron）
    '<path d="M15.5 5.5v11.7"/><path d="M12.5 14.2 15.5 17.5l3-3.3"/>',
  { size: 15, strokeWidth: 1.8 },
)
