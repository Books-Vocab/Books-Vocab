import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Vocab · Empty State — 24×24 grid、stroke:
 * currentColor、純裝飾。對齊 VocabComponentScenarios.swift「Vocab Components ·
 * Empty State」4 態使用的 SF symbol（icon 與按鈕 Label）。
 */

/** SF `book.closed` — Content「尚無單字」hero 圖示（閉合書本，書脊在左）。 */
export const BookClosedIcon = makeGlyph(
  '<path d="M6.5 4.5h9.5a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5H6.5"/>' +
    '<path d="M6.5 4.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5"/>' +
    '<path d="M8 4.5v15"/>',
)

/** SF `checkmark.circle` — Content「今天沒有要複習的單字」hero 圖示。 */
export const CheckmarkCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.2"/><path d="M8.4 12.2l2.7 2.7 4.7-5.6"/>',
)

/** SF `tray` — Card「詞庫是空的」hero 圖示（收件匣托盤）。 */
export const TrayIcon = makeGlyph(
  '<path d="M5 13.5 7 5.6A1.5 1.5 0 0 1 8.45 4.5h7.1A1.5 1.5 0 0 1 17 5.6l2 7.9"/>' +
    '<path d="M5 13.5v3.5a1.5 1.5 0 0 0 1.5 1.5h11a1.5 1.5 0 0 0 1.5-1.5v-3.5h-4.2a2.8 2.8 0 0 1-5.6 0H5z"/>',
)

/** SF `magnifyingglass` — Card「找不到符合的單字」hero 圖示（同 search field）。 */
export const MagnifyingGlassIcon = makeGlyph(
  '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4 4"/>',
)

/** SF `book` — Card「開始閱讀」按鈕 Label 圖示（沿用 bookshelf BookIcon 形狀）。 */
export const BookIcon = makeGlyph(
  '<path d="M12 6.2C10.3 4.9 8.1 4.4 5.5 4.4c-.9 0-1.5.7-1.5 1.5v11.3c0 .9.7 1.5 1.6 1.5 2.4.1 4.6.6 6.4 1.9 1.8-1.3 4-1.8 6.4-1.9.9 0 1.6-.6 1.6-1.5V5.9c0-.8-.6-1.5-1.5-1.5-2.6 0-4.8.5-6.5 1.8z"/>' +
    '<path d="M12 6.2v14.4"/>',
)

/** SF `list.bullet` — Content「查看全部單字」按鈕 Label 圖示。 */
export const ListBulletIcon = makeGlyph(
  '<path d="M9.5 7h9M9.5 12h9M9.5 17h9"/>' +
    '<path d="M5.5 7h.01M5.5 12h.01M5.5 17h.01"/>',
  { strokeWidth: 2 },
)
