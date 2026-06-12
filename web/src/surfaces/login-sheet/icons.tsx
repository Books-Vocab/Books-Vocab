import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

/**
 * Glyphs for Auth · Login Sheet — 24×24 grid、純裝飾（aria-hidden）。
 * 形狀沿用 account-section/icons.tsx 已建立的鏡像（chevron.right / apple.logo /
 * exclamationmark.triangle.fill），就地複用以避免跨 surface import。
 * hero 書堆 brand 插畫（AppIconImage）為固定 raster asset，以獨立 SVG 重繪。
 */

/** SF `chevron.right` — 登入按鈕 trailing（iconTiny 10 thin / tertiaryText）。 */
export const ChevronRightIcon = makeGlyph('<path d="M9.5 5.5 16 12l-6.5 6.5"/>')

/** SF `apple.logo` — Apple 登入按鈕 badge（iconTiny 10，白 on appleBlack）。 */
export const AppleLogoIcon = makeFilledGlyph(
  '<path d="M16.6 12.7c0-2 1.6-3 1.7-3-1-1.4-2.4-1.6-2.9-1.6-1.2-.1-2.4.7-3 .7-.6 0-1.6-.7-2.6-.7-1.3 0-2.6.8-3.3 2-1.4 2.4-.4 6 1 8 .7 1 1.5 2.1 2.5 2 1 0 1.4-.6 2.6-.6s1.5.6 2.6.6c1.1 0 1.8-1 2.4-2 .8-1.1 1.1-2.2 1.1-2.3 0 0-2.1-.8-2.1-3.1zM14.6 6.7c.5-.7.9-1.6.8-2.6-.8 0-1.8.6-2.3 1.2-.5.6-1 1.6-.8 2.5.9.1 1.8-.4 2.3-1.1z"/>',
)

/** SF `exclamationmark.triangle.fill` — 登入錯誤狀態卡（iconSmall 12 / accent fill）。 */
export const WarningTriangleFillIcon = makeGlyph(
  '<path d="M12 4 21 19.5H3z" fill="currentColor" stroke="none"/>' +
    '<path d="M12 9.5v4.5" stroke="var(--card-bg, #fff)" stroke-width="2"/>' +
    '<circle cx="12" cy="16.8" r="1.05" fill="var(--card-bg, #fff)" stroke="none"/>',
)

/**
 * AppHeroIcon — 品牌書堆插畫（`AppIconImage` 80×80 raster asset 的 SVG 重繪）。
 * 三本書（金 #E5AD1F / 橙 #CE6629 / 綠 #72864A）+ 米黃書頁 #F3EDD8 + 灰藍對話框
 * #A8BAC9 內含深藍 #1A3D63 橫槓。色彩為固定 brand raster 固有值（非 theming token）。
 */
export function AppHeroIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 256 256"
      width={80}
      height={80}
      aria-hidden="true"
      focusable="false"
    >
      {/* bottom book — green */}
      <rect x="36" y="172" width="156" height="40" rx="8" fill="#72864A" />
      <rect x="46" y="166" width="146" height="34" rx="6" fill="#F3EDD8" />
      <rect x="78" y="180" width="44" height="6" rx="3" fill="#D8D2BC" />
      {/* middle book — orange */}
      <rect x="40" y="120" width="156" height="40" rx="8" fill="#CE6629" />
      <rect x="50" y="114" width="146" height="34" rx="6" fill="#F3EDD8" />
      <rect x="82" y="128" width="44" height="6" rx="3" fill="#D8D2BC" />
      {/* top book — gold */}
      <rect x="48" y="68" width="146" height="38" rx="8" fill="#E5AD1F" />
      <rect x="58" y="62" width="136" height="32" rx="6" fill="#F3EDD8" />
      <rect x="90" y="76" width="44" height="6" rx="3" fill="#D8D2BC" />
      {/* speech bubble — blue-grey */}
      <path
        d="M168 48a40 36 0 1 1 0 72 40 36 0 0 1-20-5l-22 9 7-18a36 32 0 0 1 35-58z"
        fill="#A8BAC9"
      />
      <rect x="168" y="78" width="32" height="8" rx="4" fill="#1A3D63" />
    </svg>
  )
}
