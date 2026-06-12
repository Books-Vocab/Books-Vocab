import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs for VocabReviewCTAPill — iOS `VocabReviewCTAPill`
 * 的前導圖示，依 due/unlearned 數量切換：
 *   - both types(menu) → `play.fill`
 *   - due only         → `clock.badge`
 *   - unlearned only   → `sparkles`
 * 24×24 grid、stroke/fill currentColor（= onBrandHero）、純裝飾（aria-hidden）。
 * 形狀複用既有 surface（podcast PlayFill / vocab-section-header ClockBadge /
 * notebook Sparkles），保持跨面一致。
 */

/** SF `play.fill` — both types menu CTA（實心三角，略偏右視覺置中）。 */
export const PlayFillIcon = makeFilledGlyph('<path d="M7 4.8v14.4l11.2-7.2z"/>')

/** SF `clock.badge` — due only CTA（時鐘面 + 指針 + 右上角實心徽記點）。 */
export const ClockBadgeIcon = makeGlyph(
  '<path d="M20.5 8.2A8.5 8.5 0 1 0 15.8 20.5"/>' +
    '<path d="M12 7v5l3.2 2"/>' +
    '<circle cx="19" cy="5" r="2.1" fill="currentColor" stroke="none"/>',
  { size: 13, strokeWidth: 1.4 },
)

/** SF `sparkles` — unlearned only CTA（三星實心形狀，複用 notebook/settings）。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)
