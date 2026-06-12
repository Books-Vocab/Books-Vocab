import { makeFilledGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyph for Knowledge Graph View empty/sign-in state.
 *
 * `person.crop.circle.badge.exclamationmark`（filled）— logged-out hero。
 * 一個圈內人像 + 左下角驚嘆號圓形徽章；iOS 走 symbolLarge(symbol 30 light)，
 * 但 .fill 變體渲染為實心人像 + 實心徽章，整體單色 tertiaryText。
 * 24×24 grid、fill currentColor、純裝飾（aria-hidden）。
 */
export const PersonCircleBadgeExclamationIcon = makeFilledGlyph(
  // 主圈（含一缺口讓徽章「咬」進去，模擬 SF crop.circle 與 badge 重疊處）
  '<path d="M11 3.2a8.8 8.8 0 0 1 7.2 13.85 4.6 4.6 0 0 0-6.3 6.27A8.8 8.8 0 0 1 11 3.2z' +
    // 圈內人像：頭
    'M11 7.1a2.55 2.55 0 1 1 0 5.1 2.55 2.55 0 0 1 0-5.1z' +
    // 圈內人像：肩（圓弧上身）
    'M11 13.2c2.55 0 4.7 1.45 5.55 3.5a8.05 8.05 0 0 1-11.1 0c.85-2.05 3-3.5 5.55-3.5z" fill-rule="evenodd"/>' +
    // 驚嘆號徽章（右下角實心圓）
    '<circle cx="17.4" cy="17.6" r="4.2"/>' +
    // 驚嘆號（挖空）
    '<path d="M17.4 14.9a.62.62 0 0 1 .62.66l-.14 2.2a.48.48 0 0 1-.96 0l-.14-2.2a.62.62 0 0 1 .62-.66z" fill="var(--card-bg)"/>' +
    '<circle cx="17.4" cy="19.7" r=".62" fill="var(--card-bg)"/>',
)
