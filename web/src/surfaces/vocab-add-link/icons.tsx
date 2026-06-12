import { makeGlyph } from '../../shared/glyph'

/**
 * Vocab · Add Link 圖示 — 對齊 iOS AddLinkSheet 的兩處 SF Symbol（皆 `magnifyingglass`）：
 *   1. searchField leading（Image("magnifyingglass") / tertiaryText）
 *   2. AppEmptyStateContent hero（systemImage:"magnifyingglass" symbolLarge 30 light）
 *
 * 形狀沿用 vocab-search-field / vocab-empty-state 既有 magnifyingglass（同一 SF symbol），
 * 維持 24-grid stroke 語言一致。
 */

/** SF `magnifyingglass` — search field 前綴 + empty state hero。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)
