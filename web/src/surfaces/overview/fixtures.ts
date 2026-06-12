import type { ScenarioId } from '../../harness/scenarios'

/**
 * Overview（統計儀表板）fixtures — 鏡射 iOS StatsViewScenarios.swift（Stats View）
 * 的**渲染輸出**，而非重算日期邏輯。
 *
 * iOS 的 StatsPresenter / VocabActivityHeatmap 以「reference date」為錨計算 streak /
 * heatmap / forecast。StatsViewScenarios 已把該 scenario 的 now 凍結在
 * `StatsViewFixtures.fixedNow`（2026-06-01，並注入一個 paused 的 reviewSettingsStore
 * 讓 presenter `.task` 重算也用同一錨），故 catalog PNG 是「now=2026-06-01 的決定性
 * 渲染結果」，不再隨 capture 日漂移。fixture 凍結那一刻的**像素輸出**（streak=10、
 * heatmap trailing 數欄叢集），而非在 JS 重現 now-relative 種子。RMSE 對位移穩定。
 *
 * 視覺結構順序對齊 StatsPresenter.body（VStack spacing = sectionGap 14pt）：
 *   graphEntrySection（白卡：header「關聯圖」+ 1:1 body，catalog 內 WKWebView no-op
 *     → ProgressView spinner；graphLinks 空 → header 無 node/link count）
 *   → streakSection（連續學習 / 最長紀錄 雙卡，10/10 天）
 *   → heatmapSection（學習日曆 header + 白卡 heatmap，trailing 叢集 + legend）
 *   → forecastSection（複習預測 header + 7/14/30 selector；chart 本體在 fold 之下）
 *   → totalsFooter（fold 之下，不可見）
 *
 * empty：VocabSceneShell.empty → 置中空卡（chart.bar.xaxis + 標題 + 描述）。
 */

/** 熱力圖一格的強度等級（0 = 無活動，1..4 對齊 iOS VocabActivityHeatmap levelColor）。 */
export type HeatLevel = 0 | 1 | 2 | 3 | 4

export type OverviewFixture = {
  /** 空態（無學習資料）→ 置中空卡，其餘 section 不渲染。 */
  empty: boolean
  /** 連續學習天數（流式 serif numericHero）。 */
  currentStreak: number
  /** 最長紀錄天數。 */
  longestStreak: number
  /**
   * 熱力圖可見格 — iOS heatmap 是水平 ScrollView，auto-scroll 到 trailing，capture
   * 只看得到最後 7 欄（trailing window）。每欄 7 格（週一→週日，row 0..6），值為
   * HeatLevel。凍結 0608 PNG 的 trailing「J」叢集像素輸出。
   */
  heatmap: HeatLevel[][]
  /** 複習預測目前選中的天數（7/14/30）。 */
  forecastSelected: 7 | 14 | 30
}

/**
 * heatmap 可見 trailing 欄（每欄 = 一週 7 格，row 0=週一 … 6=週日），鏡射 0608 PNG
 * 像素取樣（5 個可見欄 × 7 列，cell pitch 16pt、auto-scroll 到 trailing 右對齊）。
 * level 由 dot 顏色判讀：
 *   1 = mutedFill 淺灰（rgba(0,0,0,0.04)，srgb ≈ 245）
 *   2 = chartHighlight@0.35（srgb ≈ 250,237,214）
 *   3 = chartHighlight@0.6 大圈（srgb ≈ 246,223,184）
 *   4 = chartHighlight 實心 大圈（#f0ca89 = 240,202,137）
 * 欄序：左→右（最後一欄貼齊卡片右內緣）；row 序：週一→週日。
 * 量測法：`magick <png> -format "%[pixel:p{x,y}]"` 在 5 欄 ×7 列格點取色再分級。
 */
const POPULATED_HEATMAP: HeatLevel[][] = [
  // col -5  col -4  col -3  col -2  col -1（右對齊；row 0=週一 … 6=週日）
  [0, 0, 0, 0, 0, 0, 0], // col -5（空）
  [0, 1, 0, 1, 0, 1, 0], // col -4
  [1, 0, 1, 0, 1, 0, 0], // col -3
  [0, 1, 0, 1, 0, 1, 0], // col -2
  [0, 4, 3, 2, 4, 3, 0], // col -1（trailing，最密；amber 4/3/2 階梯）
]

const POPULATED: OverviewFixture = {
  empty: false,
  currentStreak: 10,
  longestStreak: 10,
  heatmap: POPULATED_HEATMAP,
  forecastSelected: 30,
}

const EMPTY: OverviewFixture = {
  empty: true,
  currentStreak: 0,
  longestStreak: 0,
  heatmap: [],
  forecastSelected: 30,
}

export const OVERVIEW_FIXTURES: Record<ScenarioId<'overview'>, OverviewFixture> = {
  populated: POPULATED,
  empty: EMPTY,
}
