import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Archived Vocab surface — 同 selection/
 * vocabulary 視覺語言：24×24 grid、stroke:currentColor、glyph 純裝飾。
 */

/** SF `archivebox` — row leading 圖示（蓋+箱身+把手橫槽）。
 *  形狀沿用 selection/icons.tsx 的 ArchiveboxIcon（封存箱），strokeWidth 隨呼叫端調整。 */
export const ArchiveboxIcon = makeGlyph(
  '<path d="M4 7.5h16v2H4z"/>' +
    '<path d="M5 9.5h14V18a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18z"/>' +
    '<path d="M9.5 13h5"/>',
  { strokeWidth: 1.5 },
)

/** SF `magnifyingglass` — 底部 searchable 列前綴。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)
