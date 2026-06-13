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

/** SF `arrow.uturn.backward` — 還原（取消封存）。 */
export const ArrowUTurnIcon = makeGlyph(
  '<path d="M9 7H15a4 4 0 0 1 0 8H6"/><path d="M9 4 6 7l3 3"/>',
)

/** SF `trash` — 刪除。 */
export const TrashIcon = makeGlyph(
  '<path d="M5 7h14"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>' +
    '<path d="M6.5 7l.8 11a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4L18 7"/>',
)
