import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Account Section · Section — 24×24 grid、純裝飾
 * （aria-hidden）。形狀沿用 settings/icons.tsx 已建立的鏡像，僅補本面新增的
 * `sparkles.rectangle.stack`（升級列 inactive）與 `exclamationmark.triangle.fill`
 * （登入錯誤狀態卡）。
 */

/** SF `person.crop.circle` — 帳號 section header（stroke）。 */
export const PersonCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="9"/>' +
    '<circle cx="12" cy="9.6" r="3.1"/>' +
    '<path d="M5.8 18.6c1.2-2.6 3.5-4 6.2-4s5 1.4 6.2 4"/>',
)

/** SF `checkmark.circle.fill` — 帳號列右側綠勾（symbolLarge 30）。 */
export const CheckCircleFillIcon = makeFilledGlyph(
  '<path d="M12 2.6A9.4 9.4 0 1 0 21.4 12 9.4 9.4 0 0 0 12 2.6zm-1.5 13.6l-3.6-3.6 1.4-1.4 2.2 2.2 5.2-5.2 1.4 1.4z"/>',
)

/** SF `checkmark.seal.fill` — 訂閱列 active（iconMedium 14，success）。 */
export const SealCheckFillIcon = makeFilledGlyph(
  '<path fill-rule="evenodd" clip-rule="evenodd" d="M12 2.2l2 1.7 2.6-.4 1 2.4 2.4 1-.4 2.6 1.7 2-1.7 2 .4 2.6-2.4 1-1 2.4-2.6-.4-2 1.7-2-1.7-2.6.4-1-2.4-2.4-1 .4-2.6-1.7-2 1.7-2-.4-2.6 2.4-1 1-2.4 2.6.4zm-1.4 12.9l-2.8-2.8 1.2-1.2 1.6 1.6 4.4-4.4 1.2 1.2z"/>',
)

/** SF `sparkles.rectangle.stack` — 訂閱列 inactive（iconMedium 14，accent）：
    後疊一張卡 + 前一張卡內含 sparkles。 */
export const SparklesRectangleStackIcon = makeGlyph(
  '<rect x="6.4" y="3.2" width="13" height="9.4" rx="2" fill="none"/>' +
    '<rect x="3.4" y="9.4" width="13" height="9.4" rx="2" fill="var(--card-bg, #fff)"/>' +
    '<path d="M8 11.6l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7zM12.4 14.6l.4 1.1 1.1.4-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4z" fill="currentColor" stroke="none"/>',
)

/** SF `sparkles` — PRO badge（caption 12，accent fill）。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `chevron.right` — navigation row trailing（iconTiny 10 thin）。 */
export const ChevronRightIcon = makeGlyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')

/** SF `apple.logo` — Apple 登入按鈕 badge（iconTiny 10，白）。 */
export const AppleLogoIcon = makeFilledGlyph(
  '<path d="M16.6 12.7c0-2 1.6-3 1.7-3-1-1.4-2.4-1.6-2.9-1.6-1.2-.1-2.4.7-3 .7-.6 0-1.6-.7-2.6-.7-1.3 0-2.6.8-3.3 2-1.4 2.4-.4 6 1 8 .7 1 1.5 2.1 2.5 2 1 0 1.4-.6 2.6-.6s1.5.6 2.6.6c1.1 0 1.8-1 2.4-2 .8-1.1 1.1-2.2 1.1-2.3 0 0-2.1-.8-2.1-3.1zM14.6 6.7c.5-.7.9-1.6.8-2.6-.8 0-1.8.6-2.3 1.2-.5.6-1 1.6-.8 2.5.9.1 1.8-.4 2.3-1.1z"/>',
)

/** SF `exclamationmark.triangle.fill` — 登入錯誤狀態卡（iconSmall 12，accent fill 三角 + 白驚嘆）。 */
export const WarningTriangleFillIcon = makeGlyph(
  '<path d="M12 4 21 19.5H3z" fill="currentColor" stroke="none"/>' +
    '<path d="M12 9.5v4.5" stroke="var(--card-bg, #fff)" stroke-width="2"/>' +
    '<circle cx="12" cy="16.8" r="1.05" fill="var(--card-bg, #fff)" stroke="none"/>',
)
