import type { SVGProps } from 'react'

/**
 * Tab-bar SF-Symbol-style line glyphs，沿用各 surface icons.tsx 的 glyph 工廠
 * 慣例：24×24 grid、fill:none、stroke:currentColor、純裝飾（aria-hidden）。
 * 對應 iOS AppPrimarySection.systemImage（ContentView.swift）：
 *   bookshelf  → books.vertical
 *   podcasts   → waveform
 *   notebooks  → character.book.closed
 *   overview   → chart.bar
 */
function glyph(paths: string) {
  return function Glyph({ size = 25, strokeWidth = 1.7, ...rest }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}

/** SF `books.vertical` — 三本直立書。 */
export const BooksVerticalIcon = glyph(
  '<rect x="3.5" y="4.5" width="3.4" height="15" rx="0.8"/>' +
    '<rect x="8.3" y="4.5" width="3.4" height="15" rx="0.8"/>' +
    '<path d="M13.6 6.1 16.9 5l3.2 13.9-3.3 1.1z"/>',
)

/** SF `waveform` — 等化器豎條。 */
export const WaveformIcon = glyph(
  '<path d="M4 10v4"/><path d="M8 7v10"/><path d="M12 4v16"/><path d="M16 7v10"/><path d="M20 10v4"/>',
)

/** SF `character.book.closed` — 闔起的書（單字本）。 */
export const CharacterBookClosedIcon = glyph(
  '<path d="M6 3.5h11a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2z"/>' +
    '<path d="M4 17.5a2 2 0 0 1 2-2h12"/>' +
    '<path d="M9.2 11.3h3.6M11 8.4v5.4"/>',
)

/** SF `chart.bar` — 水平長條圖（總覽）。 */
export const ChartBarIcon = glyph(
  '<path d="M4 5.5h9"/><path d="M4 12h13"/><path d="M4 18.5h6"/>',
)

/** SF `chevron.left` — back chevron（push/pop 導航）。 */
export const ChevronLeftIcon = glyph('<path d="M14.5 5.5 8 12l6.5 6.5"/>')

/* ── 桌面殼層 secondary nav glyphs（設定 / 同步 / 帳號）。
   tablet+ 才掛載，故僅 ResponsiveShell chrome 使用，parity 不經此處。 */

/** SF `gearshape` — 設定齒輪。 */
export const GearIcon = glyph(
  '<circle cx="12" cy="12" r="3"/>' +
    '<path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18.4 5.6l-1.55 1.55M7.15 16.85 5.6 18.4M18.4 18.4l-1.55-1.55M7.15 7.15 5.6 5.6"/>',
)

/** SF `arrow.triangle.2.circlepath` — 同步循環箭頭。 */
export const SyncCircleIcon = glyph(
  '<path d="M4.5 9a7.5 7.5 0 0 1 13-2.5"/>' +
    '<path d="M18 4v3.2h-3.2"/>' +
    '<path d="M19.5 15a7.5 7.5 0 0 1-13 2.5"/>' +
    '<path d="M6 20v-3.2h3.2"/>',
)

/** SF `person.crop.circle` — 帳號。 */
export const PersonIcon = glyph(
  '<circle cx="12" cy="12" r="8.5"/>' +
    '<circle cx="12" cy="10" r="2.8"/>' +
    '<path d="M6.5 18.2a5.6 5.6 0 0 1 11 0"/>',
)

/**
 * SF `point.3.connected.trianglepath.dotted` — 知識圖譜（三節點 + 虛線連邊）。
 * 鏡射 iOS KnowledgeGraphPresenter 的 systemImage 與 web vocab-knowledge-graph
 * surface 的 GraphNodesIcon 同一幾何；shell 自有 glyph（不從 surface import，
 * 避免殼層依賴 Phase 2 surface 層）。
 */
export const KnowledgeGraphIcon = glyph(
  '<circle cx="5" cy="7.5" r="2"/>' +
    '<circle cx="19" cy="7.5" r="2"/>' +
    '<circle cx="8" cy="18" r="2"/>' +
    '<path d="M7 7.5h10" stroke-dasharray="1.4 1.8"/>' +
    '<path d="M6.4 9.1 7 16.4" stroke-dasharray="1.4 1.8"/>' +
    '<path d="M9.8 16.7 17.4 9" stroke-dasharray="1.4 1.8"/>',
)
