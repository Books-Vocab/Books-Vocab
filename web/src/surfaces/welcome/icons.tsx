import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for Welcome · onboarding walkthrough — 24×24 grid、
 * 純裝飾（aria-hidden）。對應 ios WelcomeView.swift 的 Image(systemName:)。
 *   tryItHint   sparkles                              → SparklesIcon（fill，沿用 account-section 形狀）
 *   step 1      text.viewfinder                       → TextViewfinderIcon（stroke）
 *   step 2      point.3.connected.trianglepath.dotted → ConnectedTrianglePathIcon（stroke + 三頂點實心）
 *   step 3      checkmark.circle.fill                 → CheckCircleFillIcon（fill）
 *   CTA         person.crop.circle.fill               → PersonCircleFillIcon（fill）
 */

/** SF `sparkles` — tryItHint 提示帶（caption 12，secondaryText）。沿用 account-section 形狀。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `text.viewfinder` — step 1（hero 40 regular，accent）：四角取景框 + 三行文字。 */
export const TextViewfinderIcon = makeGlyph(
  '<path d="M4 8V6.4A2.4 2.4 0 0 1 6.4 4H8"/>' +
    '<path d="M16 4h1.6A2.4 2.4 0 0 1 20 6.4V8"/>' +
    '<path d="M20 16v1.6a2.4 2.4 0 0 1-2.4 2.4H16"/>' +
    '<path d="M8 20H6.4A2.4 2.4 0 0 1 4 17.6V16"/>' +
    '<path d="M8 9.6h8"/>' +
    '<path d="M8 12.4h8"/>' +
    '<path d="M8 15.2h5"/>',
)

/** SF `point.3.connected.trianglepath.dotted` — step 2（hero 40 regular，accent）：
    三頂點實心圓以虛線三角路徑相連。 */
export const ConnectedTrianglePathIcon = makeGlyph(
  '<line x1="7.4" y1="9.6" x2="14.4" y2="6.6" stroke-dasharray="0.1 2.4"/>' +
    '<line x1="16.6" y1="8.6" x2="16.6" y2="14.4" stroke-dasharray="0.1 2.4"/>' +
    '<line x1="14.4" y1="16.6" x2="7.4" y2="11.6" stroke-dasharray="0.1 2.4"/>' +
    '<circle cx="6" cy="10.4" r="2.1" fill="currentColor" stroke="none"/>' +
    '<circle cx="16.6" cy="6.4" r="2.1" fill="currentColor" stroke="none"/>' +
    '<circle cx="16.6" cy="16.6" r="2.1" fill="currentColor" stroke="none"/>',
)

/** SF `checkmark.circle.fill` — step 3（hero 40 regular，accent）。沿用 account-section 形狀。 */
export const CheckCircleFillIcon = makeFilledGlyph(
  '<path d="M12 2.6A9.4 9.4 0 1 0 21.4 12 9.4 9.4 0 0 0 12 2.6zm-1.5 13.6l-3.6-3.6 1.4-1.4 2.2 2.2 5.2-5.2 1.4 1.4z"/>',
)

/** SF `person.crop.circle.fill` — 登入帳號 CTA（subhead 15 semibold，pageBackground on primaryText）。 */
export const PersonCircleFillIcon = makeFilledGlyph(
  '<path d="M12 2.6A9.4 9.4 0 1 0 21.4 12 9.4 9.4 0 0 0 12 2.6zm0 3.4a3 3 0 1 1 0 6 3 3 0 0 1 0-6zm0 14.2a8 8 0 0 1-5.2-1.9c.4-2.4 3.2-3.7 5.2-3.7s4.8 1.3 5.2 3.7A8 8 0 0 1 12 20.2z"/>',
)
