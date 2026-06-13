import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for LinkReasonSheet — 24×24 grid、stroke:currentColor、純裝飾。
 * 對應 iOS `Image(systemName:)`：paperclip(iconSmall=symbol 12 .medium，header) ·
 * arrow.up.right / eye.slash(iconTiny=symbol 10 .thin，footer ghost button)。
 *
 * iconTiny=.thin → strokeWidth 1.3；iconSmall=.medium → strokeWidth 1.7。
 * 視覺尺寸於 Screen 以 size prop 指定（header 19 / footer 16），對齊 catalog 12/10pt 比例。
 */

/** SF `paperclip` — header「相似用法」前綴。對角迴紋針 swoosh。 */
export const PaperclipIcon = makeGlyph(
  '<path d="M15.5 7.4l-6 6a2 2 0 0 1-2.83-2.83l6.4-6.4a3.3 3.3 0 0 1 4.66 4.66l-6.5 6.5a4.6 4.6 0 0 1-6.5-6.5l5.6-5.6"/>',
  { size: 19, strokeWidth: 1.7 },
)

/** SF `arrow.up.right` —「查看詳情」後綴。對角線 + 角箭頭。 */
export const ArrowUpRightIcon = makeGlyph(
  '<path d="M7 17 17 7"/><path d="M9 7h8v8"/>',
  { size: 16, strokeWidth: 1.3 },
)

/** SF `eye.slash` —「隱藏此連結」前綴。眼形 + 瞳孔 + 斜線。 */
export const EyeSlashIcon = makeGlyph(
  '<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6c-1.6 0-3-.4-4.3-1"/><circle cx="12" cy="12" r="2.2"/><path d="M4 4 20 20"/>',
  { size: 16, strokeWidth: 1.3 },
)
