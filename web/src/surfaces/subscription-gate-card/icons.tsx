import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * Hero glyphs for `ProAccessGateCard`（SubscriptionViews.swift）— symbolHero
 * = symbol 44 light（.foregroundStyle(accent)）。stroke glyph 以淡 strokeWidth
 * 對應 light weight；fill glyph 對應 SF `.fill` 變體。
 *
 * sparkles — 複用 notebook/settings 既有三星實心形狀（跨面一致）。
 * graduationcap.fill / clock.badge.checkmark / headphones — 本面新繪。
 */

/** SF `sparkles` — 三星實心（複用 notebook SparklesIcon 形狀）。 */
export const SparklesIcon = makeFilledGlyph(
  '<path d="M9.5 4.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3L5 9l3.3-1.2zM16.8 12.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9zM16 3.8l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>',
)

/** SF `graduationcap.fill` — 實心學士帽（菱形帽板 + 帽身 + 流蘇）。 */
export const GraduationCapFillIcon = makeFilledGlyph(
  // 帽板（菱形）
  '<path d="M12 4 22 8.4 12 12.8 2 8.4z"/>' +
    // 帽身（戴在頭上的下半部，避開兩側）
    '<path d="M7 11.1v3.3c0 1.3 2.2 2.4 5 2.4s5-1.1 5-2.4v-3.3l-5 2.2z"/>' +
    // 流蘇（從帽板右後垂下）
    '<path d="M20.4 9.1v3.9" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/>' +
    '<circle cx="20.4" cy="13.8" r="1"/>',
)

/** SF `clock.badge.checkmark` — 時鐘（外圈避開右下缺口）+ 指針 + 右下打勾徽記。 */
export const ClockBadgeCheckmarkIcon = makeGlyph(
  '<path d="M19.6 14.4A8.5 8.5 0 1 0 14.2 19.7"/>' +
    '<path d="M11 7.5v4.5l3 1.8"/>' +
    // 右下角 badge 圓 + 勾
    '<circle cx="18.5" cy="18.5" r="3.8" fill="currentColor" stroke="none"/>' +
    '<path d="M16.9 18.6l1.1 1.1 2-2.3" stroke="var(--card-bg)" stroke-width="1.3" fill="none"/>',
  { strokeWidth: 1.5 },
)

/** SF `headphones` — 頭帶弧 + 左右耳罩（圓角實心兩側）。 */
export const HeadphonesIcon = makeGlyph(
  // 頭帶（半圓弧）
  '<path d="M4 13v-1a8 8 0 0 1 16 0v1"/>' +
    // 左耳罩
    '<path d="M4 13.5a1.8 1.8 0 0 1 1.8-1.8h.8a1 1 0 0 1 1 1v4.6a1 1 0 0 1-1 1h-.8A1.8 1.8 0 0 1 4 16.5z" fill="currentColor" stroke="none"/>' +
    // 右耳罩
    '<path d="M20 13.5a1.8 1.8 0 0 0-1.8-1.8h-.8a1 1 0 0 0-1 1v4.6a1 1 0 0 0 1 1h.8A1.8 1.8 0 0 0 20 16.5z" fill="currentColor" stroke="none"/>',
  { strokeWidth: 1.7 },
)
