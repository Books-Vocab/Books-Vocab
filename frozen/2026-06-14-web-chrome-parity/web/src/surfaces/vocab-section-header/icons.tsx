import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyph for VocabSectionHeader — 24×24 grid、stroke:currentColor、
 * 純裝飾。iOS 用 iconTiny = symbol(size:10, weight:.thin)，故以細描邊 (1.4) 對齊。
 */

/** SF `clock.badge` — 時鐘面 + 指針 + 右上角小徽記點（待複習 section）。 */
export const ClockBadgeIcon = makeGlyph(
  // 時鐘外圈（避開右上 badge 的缺口）+ 指針（12→3 點方向）
  '<path d="M20.5 8.2A8.5 8.5 0 1 0 15.8 20.5"/>' +
    '<path d="M12 7v5l3.2 2"/>' +
    // 右上角 badge 點（實心）
    '<circle cx="19" cy="5" r="2.1" fill="currentColor" stroke="none"/>',
  { size: 13, strokeWidth: 1.4 },
)
