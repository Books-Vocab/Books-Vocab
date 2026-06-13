import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for KG Empty State — 24×24 grid、stroke currentColor、
 * 純裝飾。對齊 KGVocabEmptyState resolver 各分支選的 SF symbol（hero icon +
 * 按鈕 Label）。形狀沿用其它 surface 已建立的鏡像，僅 checkmark.seal（outline）
 * 為本 surface 新繪（settings 只有 .fill 變體，語意不同）。
 */

/** SF `books.vertical` — hasNoEntries hero（三本直立書）。沿用 vocabulary BooksIcon。 */
export const BooksVerticalIcon = makeGlyph(
  '<rect x="3.5" y="5" width="4" height="14" rx="0.9"/>' +
    '<rect x="9" y="5" width="4" height="14" rx="0.9"/>' +
    '<rect x="14.5" y="5" width="4" height="14" rx="0.9"/>',
)

/** SF `magnifyingglass` — search-no-match hero。沿用 search field 形狀。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)

/** SF `checkmark.seal`（outline）— single filter (due) hero（扇貝封緘 + 勾）。 */
export const CheckmarkSealIcon = makeGlyph(
  '<path d="M12 3.2l1.9 1.6 2.5-.4.95 2.35 2.35.95-.4 2.5 1.6 1.9-1.6 1.9.4 2.5-2.35.95-.95 2.35-2.5-.4-1.9 1.6-1.9-1.6-2.5.4-.95-2.35-2.35-.95.4-2.5-1.6-1.9 1.6-1.9-.4-2.5 2.35-.95.95-2.35 2.5.4z"/>' +
    '<path d="M8.8 12.1l2.3 2.3 4.1-4.8"/>',
)

/** SF `line.3.horizontal.decrease.circle` — multi filter hero（圈內遞減橫線）。沿用 notebook FilterCircleIcon。 */
export const FilterCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M7.4 9.2h9.2M8.8 12h6.4M10.4 14.8h3.2"/>',
)

/** SF `arrow.clockwise` — 「重新整理」CTA Label icon。沿用 vocabulary RefreshIcon。 */
export const RefreshIcon = makeGlyph(
  '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v4h-4"/>',
)
