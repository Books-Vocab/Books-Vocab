import { makeGlyph } from '../../shared/glyph'

/**
 * Overview（統計儀表板）glyphs — 對齊 StatsPresenter / VocabActivityHeatmap 的
 * SF Symbols。24×24 grid、stroke:currentColor、純裝飾（aria-hidden）。
 */

/** SF `point.3.connected.trianglepath.dotted` — graph card header（amber）。
 *  三節點三角 + 虛線連邊，鏡射 iOS 關聯圖入口圖示。 */
export const GraphNodesIcon = makeGlyph(
  '<circle cx="5" cy="7.5" r="2"/>' +
    '<circle cx="19" cy="7.5" r="2"/>' +
    '<circle cx="8" cy="18" r="2"/>' +
    '<path d="M7 7.5h10" stroke-dasharray="1.4 1.8"/>' +
    '<path d="M6.4 9.1 7 16.4" stroke-dasharray="1.4 1.8"/>' +
    '<path d="M9.8 16.7 17.4 9" stroke-dasharray="1.4 1.8"/>',
)

/** SF `flame` — 連續學習卡。 */
export const FlameIcon = makeGlyph(
  '<path d="M12 3.5c2.2 3 1 5-.2 6.4-.8 1-1.3 1.9-1.3 3a3 3 0 0 0 3 3 3.2 3.2 0 0 0 3.3-3.3c0-2.2-1.2-3.4-1.2-3.4s.4 1.6-.7 2.2c.6-2.4-1.3-4.7-2.7-5.6.5 1.5-.3 2.6-1 3.3-.6-2 .7-4 .7-5.3z"/>',
)

/** SF `trophy` — 最長紀錄卡。 */
export const TrophyIcon = makeGlyph(
  '<path d="M7 4.5h10v3.5a5 5 0 0 1-10 0z"/>' +
    '<path d="M7 5.5H4.6a1 1 0 0 0-1 1.1c.2 1.8 1.2 3 3.4 3.4"/>' +
    '<path d="M17 5.5h2.4a1 1 0 0 1 1 1.1c-.2 1.8-1.2 3-3.4 3.4"/>' +
    '<path d="M12 13v3.5"/><path d="M9 19.5h6"/><path d="M9.5 19.5l.6-3h3.8l.6 3"/>',
)

/** SF `calendar` — 學習日曆 header。 */
export const CalendarIcon = makeGlyph(
  '<rect x="4" y="5.5" width="16" height="14" rx="2.2"/>' +
    '<path d="M4 9.5h16"/><path d="M8 3.5v3M16 3.5v3"/>',
)

/** SF `chart.bar` — 複習預測 header。3 條水平長條。 */
export const ChartBarIcon = makeGlyph(
  '<path d="M4 5.5h9"/><path d="M4 12h13"/><path d="M4 18.5h6"/>',
)

/** SF `chart.bar.xaxis` — empty state（尚無學習資料）。直立長條 + x 軸底線。 */
export const ChartBarXAxisIcon = makeGlyph(
  '<path d="M5 18V11"/><path d="M10 18V6"/><path d="M15 18V13"/><path d="M20 18V8"/>' +
    '<path d="M3.5 20.5h17"/>',
)
