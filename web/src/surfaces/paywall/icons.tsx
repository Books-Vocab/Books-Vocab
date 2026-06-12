import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/** SF `sparkles.rectangle.stack.fill` — inactive hero（symbolHero 44 light，accent）。
 *  形狀沿用 settings-subscription 既有鏡像（雙層卡 + sparkle）。 */
export const SparklesRectangleStackFillIcon = makeGlyph(
  '<rect x="6.4" y="3.2" width="13" height="9.4" rx="2" fill="none"/>' +
    '<rect x="3.4" y="9.4" width="13" height="9.4" rx="2" fill="var(--page-bg, #f7f6f3)"/>' +
    '<path d="M8 11.6l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7zM12.4 14.6l.4 1.1 1.1.4-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4z" fill="currentColor" stroke="none"/>',
)

/** SF `checkmark.seal.fill` — active hero（symbolHero 44 light，success）。
 *  齒輪封章外緣 + 內部勾。 */
export const CheckmarkSealFillIcon = makeFilledGlyph(
  '<path d="M12 1.8l2.3 1.7 2.85-.35 1.15 2.62 2.62 1.15-.35 2.85L22 12l-1.58 2.3.35 2.85-2.62 1.15-1.15 2.62-2.85-.35L12 22.2l-2.3-1.58-2.85.35-1.15-2.62-2.62-1.15.35-2.85L1.8 12l1.58-2.3-.35-2.85 2.62-1.15L8.85 3.15 11.7 3.5z"/>' +
    '<path d="M8.4 12l2.4 2.4 4.8-4.8" fill="none" stroke="var(--page-bg, #f7f6f3)" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
)

/** SF `exclamationmark.triangle.fill` — cancelled hero（symbolHero 44 light，accent）。 */
export const ExclamationmarkTriangleFillIcon = makeFilledGlyph(
  '<path d="M12 3.2c.6 0 1.15.33 1.45.86l8 14.1c.62 1.1-.17 2.44-1.45 2.44H4c-1.28 0-2.07-1.34-1.45-2.44l8-14.1c.3-.53.85-.86 1.45-.86z"/>' +
    '<path d="M12 9.2v5" fill="none" stroke="var(--page-bg, #f7f6f3)" stroke-width="1.9" stroke-linecap="round"/>' +
    '<circle cx="12" cy="17.4" r="1.1" fill="var(--page-bg, #f7f6f3)" stroke="none"/>',
)

/** SF `checkmark.circle.fill` — active feature list 前導（iconMedium 14，success）。 */
export const CheckmarkCircleFillIcon = makeFilledGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<path d="M8.2 12.2l2.5 2.5 4.9-5" fill="none" stroke="var(--page-bg, #f7f6f3)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
)

/** SF `checkmark.circle.fill` — comparison table mark（iconMedium 14）。
 *  tone 由 currentColor 決定（free=success / pro=accent）。 */
export const CheckmarkCircleFillMark = CheckmarkCircleFillIcon

/** SF `sparkles` — inactive marketing feature list 前導（iconMedium 14，accent）。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M12 3l1.2 3.6L16.8 8l-3.6 1.4L12 13l-1.2-3.6L7.2 8l3.6-1.4z"/>' +
    '<path d="M17.6 13.4l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>' +
    '<path d="M6 14.2l.5 1.5 1.5.5-1.5.5L6 18.2l-.5-1.5-1.5-.5 1.5-.5z"/>',
)

/** SF `arrow.up.forward` — 管理訂閱 primary button trailing（iconSmall 12，quaternaryText）。 */
export const ArrowUpForwardIcon = makeGlyph(
  '<path d="M7.5 16.5 16.5 7.5M9.5 7.5h7v7"/>',
)
