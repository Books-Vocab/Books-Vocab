import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for TranslationLanguageSettings — 24×24 grid。
 * 對應 iOS `SettingsSectionHeader(icon:)` 與 `SettingsSelectableRow` 的 SF Symbols：
 * - book              → 閱讀語言 section header
 * - character.bubble  → 翻譯語言 section header
 * - checkmark         → 選定列尾勾（iconSmall = symbol 12 medium / accent）
 */

/** SF `book` — 閱讀語言 header（攤開書本輪廓）。 */
export const BookIcon = makeGlyph(
  '<path d="M12 6.5C12 5.5 10.5 4.8 8.2 4.8 6 4.8 4.5 5.3 4 5.8v12c.5-.5 2-1 4.2-1 2.3 0 3.8.7 3.8 1.7"/>' +
    '<path d="M12 6.5C12 5.5 13.5 4.8 15.8 4.8 18 4.8 19.5 5.3 20 5.8v12c-.5-.5-2-1-4.2-1-2.3 0-3.8.7-3.8 1.7"/>' +
    '<path d="M12 6.5v12"/>',
  { size: 16, strokeWidth: 1.6 },
)

/** SF `character.bubble` — 翻譯語言 header（對話框內字符）。 */
export const CharacterBubbleIcon = makeGlyph(
  '<path d="M4 6.5C4 5.4 4.9 4.5 6 4.5h12c1.1 0 2 .9 2 2v7c0 1.1-.9 2-2 2H10l-4 3v-3H6c-1.1 0-2-.9-2-2z"/>' +
    '<path d="M9.2 13 12 6.5 14.8 13M10.2 10.8h3.6"/>',
  { size: 16, strokeWidth: 1.5 },
)

/** SF `checkmark` — 選定列尾勾（accent）。 */
export const CheckmarkIcon = makeGlyph('<path d="M5 12.5 10 17.5 19 6.5"/>', {
  size: 15,
  strokeWidth: 2,
})
