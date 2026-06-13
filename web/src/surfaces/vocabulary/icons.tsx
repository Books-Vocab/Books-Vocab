import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for the Vocabulary surface — 同 notebook/settings 視覺
 * 語言：24×24 grid、stroke:currentColor。glyph 純裝飾（aria-hidden）。
 */

/** SF `magnifyingglass` — 搜尋欄前綴 + no-match empty state。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)

/** SF `arrow.up.arrow.down` — sort pill。 */
export const SortIcon = makeGlyph(
  '<path d="M7 4v15M7 19l-3-3M7 19l3-3M17 20V5M17 5l-3 3M17 5l3 3"/>',
)

/** SF `sparkles` — 未學複習 CTA pill；複用 notebook/settings 的三星形狀。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `books.vertical` — zero-data empty state（三本直立書，皆 upright）。 */
export const BooksIcon = makeGlyph(
  '<rect x="3.5" y="5" width="4" height="14" rx="0.9"/>' +
    '<rect x="9" y="5" width="4" height="14" rx="0.9"/>' +
    '<rect x="14.5" y="5" width="4" height="14" rx="0.9"/>' +
    '<path d="M3.5 8.5h4M9 8.5h4M14.5 8.5h4"/>',
)

/** SF `arrow.clockwise` — zero-data CTA 按鈕（重新整理）。 */
export const RefreshIcon = makeGlyph(
  '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v4h-4"/>',
)

/**
 * SF `point.3.connected.trianglepath.dotted` — 知識圖譜 header 鈕（鏡射 iOS
 * KnowledgeGraphPresenter systemImage 與 shell/icons.tsx KnowledgeGraphIcon）。
 * 三節點三角佈局 + 虛線連邊。
 */
export const KnowledgeGraphIcon = makeGlyph(
  '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/>' +
    '<path d="M10.5 6.7 6.5 16.3M13.5 6.7l4 9.6M7 18h10" stroke-dasharray="0.1 3"/>',
)

/** SF `plus` — 新增連結 header 鈕（沿用 notebook/settings 的 plus 形狀）。 */
export const PlusIcon = makeGlyph('<path d="M12 5.5v13M5.5 12h13"/>')

/**
 * SF `speaker.wave.2` — 卡片發音鈕（Web Speech API 朗讀）。喇叭本體 + 兩道聲波。
 */
export const SpeakerIcon = makeGlyph(
  '<path d="M4 9.5h3l4-3.2v11.4l-4-3.2H4z"/>' +
    '<path d="M14.5 9a4 4 0 0 1 0 6"/>' +
    '<path d="M16.8 6.8a7 7 0 0 1 0 10.4"/>',
)

/**
 * SF `square.and.arrow.up` — 分享 / 複製卡片鈕。向上箭頭出自方框（iOS 分享語意）。
 */
export const ShareIcon = makeGlyph(
  '<path d="M12 4v11"/><path d="M8.5 7.5 12 4l3.5 3.5"/>' +
    '<path d="M7 11.5H5.5v7h13v-7H17"/>',
)

/** SF `arrow.triangle.2.circlepath` 同家族「今日複習」CTA glyph（環形複習箭頭）。 */
export const ReviewIcon = makeGlyph(
  '<path d="M19 12a7 7 0 1 1-2-4.9"/><path d="M19 4.5V8h-3.5"/>',
)
