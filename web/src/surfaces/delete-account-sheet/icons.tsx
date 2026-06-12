import { makeFilledGlyph, makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for SettingsDeleteAccountSheet — 24×24 grid、
 * stroke/fill:currentColor、純裝飾（aria-hidden）。對應 iOS SF Symbols：
 *
 *   hero        exclamationmark.triangle.fill  symbolHero(44, light)  destructive
 *   header      trash / checkmark.square / keyboard  caption(sans 12 bold)  secondaryText
 *   row icons   person.crop.circle / books.vertical /
 *               point.3.connected.trianglepath.dotted / book.closed /
 *               checkmark.seal  iconMedium(14, medium)  destructive
 *   button      trash.fill  iconMedium  destructive
 *
 * stroke 線寬走既有 surface 慣例（iconMedium ≈ strokeWidth 1.7）。
 */

/** exclamationmark.triangle.fill — hero（symbolHero 44 light / destructive，實心三角 + 鏤空驚嘆號） */
export const ExclamationTriangleFillIcon = makeFilledGlyph(
  '<path d="M11.13 3.3a1 1 0 0 1 1.74 0l8.6 15.2A1 1 0 0 1 20.6 20H3.4a1 1 0 0 1-.87-1.5z"/>' +
    '<path fill="#fff" d="M11 8h2v6h-2z"/>' +
    '<circle fill="#fff" cx="12" cy="16.6" r="1.1"/>',
)

/** trash — consequences section header */
export const TrashIcon = makeGlyph(
  '<path d="M5 7h14"/>' +
    '<path d="M9.5 7V5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7"/>' +
    '<path d="M6.5 7l.9 11.2a1.5 1.5 0 0 0 1.5 1.3h6.2a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>' +
    '<path d="M10 10.5v6M14 10.5v6"/>',
)

/** trash.fill — delete button leading icon（實心垃圾桶） */
export const TrashFillIcon = makeFilledGlyph(
  '<path d="M4.5 6.5h15v1.2h-15z"/>' +
    '<path d="M9 6.5V5.4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1.1h-1.4V5.6h-3.2v.9z"/>' +
    '<path d="M6.2 8.4h11.6l-.85 10.6a1.4 1.4 0 0 1-1.4 1.3H8.45a1.4 1.4 0 0 1-1.4-1.3z"/>',
)

/** checkmark.square — acknowledgements section header */
export const CheckmarkSquareIcon = makeGlyph(
  '<rect x="4" y="4" width="16" height="16" rx="3"/>' +
    '<path d="M8.5 12.3l2.4 2.4 4.6-5"/>',
)

/** keyboard — confirmation section header */
export const KeyboardIcon = makeGlyph(
  '<rect x="3" y="6" width="18" height="12" rx="2"/>' +
    '<path d="M6.5 9.2h.01M9.5 9.2h.01M12.5 9.2h.01M15.5 9.2h.01M18 9.2h.01"/>' +
    '<path d="M6.5 12h.01M9.5 12h.01M12.5 12h.01M15.5 12h.01M18 12h.01"/>' +
    '<path d="M8.5 14.8h7"/>',
)

/** person.crop.circle — 帳號資訊 */
export const PersonCropCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.5"/>' +
    '<circle cx="12" cy="10" r="2.6"/>' +
    '<path d="M6.6 18.2a5.6 5.6 0 0 1 10.8 0"/>',
)

/** books.vertical — 雲端生詞與筆記本 */
export const BooksVerticalIcon = makeGlyph(
  '<rect x="4.5" y="4.5" width="3.4" height="15" rx="0.8"/>' +
    '<rect x="9.3" y="4.5" width="3.4" height="15" rx="0.8"/>' +
    '<path d="M14.6 5.2l3.3 0.9a0.8 0.8 0 0 1 0.55 1l-3.1 13.1"/>',
)

/** point.3.connected.trianglepath.dotted — 知識圖譜與關聯 */
export const GraphConnectedIcon = makeGlyph(
  '<circle cx="12" cy="5" r="2.1"/>' +
    '<circle cx="5.5" cy="17.5" r="2.1"/>' +
    '<circle cx="18.5" cy="17.5" r="2.1"/>' +
    '<path stroke-dasharray="1.6 2.2" d="M11 6.8 6.4 15.7M13 6.8l4.6 8.9M7.6 17.5h8.8"/>',
)

/** book.closed — 閱讀進度與書架 */
export const BookClosedIcon = makeGlyph(
  '<rect x="5.5" y="4.5" width="13" height="15" rx="1.6"/>' +
    '<path d="M8.2 4.5v15"/>',
)

/** checkmark.seal — 訂閱記錄 */
export const CheckmarkSealIcon = makeGlyph(
  '<path d="M12 3.2l2 1.5 2.5-.3 1 2.3 2.3 1-.3 2.5 1.5 2-1.5 2 .3 2.5-2.3 1-1 2.3-2.5-.3-2 1.5-2-1.5-2.5.3-1-2.3-2.3-1 .3-2.5-1.5-2 1.5-2-.3-2.5 2.3-1 1-2.3 2.5.3z"/>' +
    '<path d="M8.8 12l2.2 2.2 4.2-4.4"/>',
)
