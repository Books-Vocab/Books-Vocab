import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * VocabSearchField 圖示 — 對齊 iOS AppSearchField 的兩顆 SF Symbol：
 *   leading `magnifyingglass`（iconSmall = symbol 12 medium）
 *   trailing clear `xmark.circle.fill`（iconMedium = symbol 14 medium，僅 query 非空時顯示）
 *
 * magnifyingglass 形狀沿用 vocabulary/icons.tsx（同一 SF symbol），此處重描以維持
 * 24-grid stroke 語言一致；xmark.circle.fill 為實心圓 + 內部 X negative space。
 */

/** SF `magnifyingglass` — 搜尋欄前綴。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)

/** SF `xmark.circle.fill` — 清除按鈕（實心圓底，X 為留白）。 */
export const XmarkCircleFillIcon = makeFilledGlyph(
  '<path fill-rule="evenodd" clip-rule="evenodd" d="M12 2a10 10 0 100 20 10 10 0 000-20zM8.4 7.1a.9.9 0 00-1.3 1.3L10.7 12l-3.6 3.6a.9.9 0 101.3 1.3L12 13.3l3.6 3.6a.9.9 0 101.3-1.3L13.3 12l3.6-3.6a.9.9 0 10-1.3-1.3L12 10.7 8.4 7.1z"/>',
)
