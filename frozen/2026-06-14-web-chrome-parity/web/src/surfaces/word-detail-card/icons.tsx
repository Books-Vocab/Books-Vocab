import { makeGlyph } from '../../shared/glyph'

/**
 * Word Detail · Card Document 用 SF Symbol glyph。
 * 對應 iOS：speaker.wave.2.fill（hero 朗讀鈕）、text.word.spacing（搭配 label）、
 * book.closed（來源 label）。
 */

/** SF `speaker.wave.2.fill` — hero 朗讀鈕（實心喇叭 + 兩道音波）。iconSmall(12) medium。
 *  喇叭主體實心填滿、音波保持 stroke（與 iOS .fill 變體一致：箱體填色、波紋線條）。 */
export const SpeakerWaveFillIcon = makeGlyph(
  '<path d="M4 9.5h3l4-3.2v11.4l-4-3.2H4z" fill="currentColor" stroke="none"/>' +
    '<path d="M14.4 9.2a3.6 3.6 0 0 1 0 5.6"/>' +
    '<path d="M16.6 7.2a6.4 6.4 0 0 1 0 9.6"/>',
)

/** SF `text.word.spacing` — 「搭配」section label 前綴（三行遞減文字，字距記號）。
 *  iconTiny(10) thin。 */
export const TextWordSpacingIcon = makeGlyph(
  '<path d="M4 7h16M4 12h11M4 17h7"/>',
  { strokeWidth: 1.4 },
)

/** SF `book.closed` — 「來源」section label 前綴（閉合書本，書脊在左）。iconTiny(10) thin。
 *  沿用 vocab-empty-state BookClosedIcon 形狀。 */
export const BookClosedIcon = makeGlyph(
  '<path d="M6.5 4.5h9.5a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5H6.5"/>' +
    '<path d="M6.5 4.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5"/>' +
    '<path d="M8 4.5v15"/>',
  { strokeWidth: 1.4 },
)
