import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols glyphs for review-banner CTAs。24×24 grid，aria-hidden 純裝飾。
 *
 * VocabReviewBanner.reviewButton 依狀態用不同 Label systemImage：
 *   - hasBothTypes / due-only-menu primary → `play.fill`
 *   - due only          → `clock.badge`
 *   - unlearned only    → `sparkles`
 * 三角 play.fill 複用 podcast-continue-card 形狀（catalog 慣例每 surface 自持）。
 */

/** SF `play.fill` — 「開始複習」primary CTA（hasBothTypes）。 */
export const PlayFillIcon = makeFilledGlyph('<path d="M7 4.8v14.4l11.2-7.2z"/>')

/** SF `clock.badge` — 「到期複習」due-only CTA。clock dial + 右上 badge dot。 */
export const ClockBadgeIcon = makeGlyph(
  '<circle cx="10.5" cy="13.5" r="7"/>' +
    '<path d="M10.5 9.5v4l2.6 1.6"/>' +
    '<circle cx="18.5" cy="6" r="2.4" fill="currentColor" stroke="none"/>',
  { strokeWidth: 1.7 },
)

/** SF `sparkles` — 「未學複習」unlearned-only CTA。三星形狀（複用 settings sparkles）。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M12 3.2l1.5 4.1 4.1 1.5-4.1 1.5L12 14.4l-1.5-4.1L6.4 8.8l4.1-1.5z"/>' +
    '<path d="M18 13.6l.8 2.1 2.1.8-2.1.8-.8 2.1-.8-2.1-2.1-.8 2.1-.8z"/>' +
    '<path d="M6 14.4l.6 1.6 1.6.6-1.6.6L6 19.4l-.6-1.6-1.6-.6 1.6-.6z"/>',
)
