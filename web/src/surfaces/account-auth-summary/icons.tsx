import { makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Account Section · Auth Summary（24×24 grid、純裝飾）。
 * 形狀沿用 account-section/icons.tsx 已建立的鏡像（同一 SettingsAuthSummary 元件）。
 */

/** SF `checkmark.circle.fill` — 帳號列右側綠勾（symbolLarge 30，success）。 */
export const CheckCircleFillIcon = makeFilledGlyph(
  '<path d="M12 2.6A9.4 9.4 0 1 0 21.4 12 9.4 9.4 0 0 0 12 2.6zm-1.5 13.6l-3.6-3.6 1.4-1.4 2.2 2.2 5.2-5.2 1.4 1.4z"/>',
)

/** SF `sparkles` — PRO badge（caption 12，accent fill）。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)
