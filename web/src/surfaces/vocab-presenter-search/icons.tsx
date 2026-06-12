import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Vocab Presenter (search) — 24×24 grid、
 * stroke currentColor、純裝飾。對齊 KGVocabPresenter / KGVocabEmptyState 用到的
 * SF symbol：sort pill 的 `arrow.up.arrow.down`、in-card 空狀態 hero
 * `magnifyingglass`（沿用 kg-empty-state 形狀）。
 */

/** SF `arrow.up.arrow.down` — VocabSortPill leading icon（雙向箭頭）。 */
export const ArrowUpArrowDownIcon = makeGlyph(
  '<path d="M7 4v16"/><path d="M4 7l3-3 3 3"/>' +
    '<path d="M17 20V4"/><path d="M14 17l3 3 3-3"/>',
)

/** SF `magnifyingglass` — search-no-match hero。沿用 kg-empty-state MagnifyingGlassIcon。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)
