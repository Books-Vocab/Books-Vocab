import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Vocabulary · Knowledge Graph。24×24 grid、stroke
 * currentColor、純裝飾。對齊 KnowledgeGraphPresenter 用到的 SF symbol：
 *   - empty/no-links hero + overlay header = `point.3.connected.trianglepath.dotted`
 *   - overlay 關閉鈕 = `xmark`（VocabChromeIconButton）
 * GraphNodesIcon 形狀沿用 overview/icons.tsx 的 graph 入口圖示，保持跨 surface 一致。
 */

/** SF `point.3.connected.trianglepath.dotted` — 三節點三角 + 虛線連邊。 */
export const GraphNodesIcon = makeGlyph(
  '<circle cx="5" cy="7.5" r="2"/>' +
    '<circle cx="19" cy="7.5" r="2"/>' +
    '<circle cx="8" cy="18" r="2"/>' +
    '<path d="M7 7.5h10" stroke-dasharray="1.4 1.8"/>' +
    '<path d="M6.4 9.1 7 16.4" stroke-dasharray="1.4 1.8"/>' +
    '<path d="M9.8 16.7 17.4 9" stroke-dasharray="1.4 1.8"/>',
)

/** SF `xmark` — overlay header 關閉鈕（VocabChromeIconButton, iconMedium）。 */
export const XmarkIcon = makeGlyph('<path d="M6 6l12 12M18 6L6 18"/>')
