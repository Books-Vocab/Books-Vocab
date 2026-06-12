import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabActivityHeatmap scenario fixtures — 對齊 VocabActivityHeatmapScenarios.swift
 * 「Vocab Heatmap」5 態。
 *
 * iOS fixtures 以 `[String: Int]`（"yyyy-MM-dd" -> count）合成，且 grid 由
 * `VocabActivityHeatmap.buildGrid(activity:weeks:)` 在 runtime 依 `Date()` 推週一回填
 * `weeks` 週 × 7 天。catalog 於 2026-06-11 截圖，故此處以**固定參考日 2026-06-11**
 * 重建相同 grid（否則 web 在不同日期 render 會與 ref 漂移）。
 *
 * 強度分級（intensityLevel + levelColor，見 VocabActivityHeatmap.swift）：
 *   count == 0        → level 0 → 透明（不畫圓）
 *   thresholds < 3 個 → level 1（flat，No thresholds 態全部 muted）
 *   count <= t0(2)    → level 1 → mutedFill (rgba(0,0,0,0.04))
 *   count <= t1(5)    → level 2 → chartHighlight 0.35
 *   count <= t2(9)    → level 3 → chartHighlight 0.60（圓放大 1.15×）
 *   else              → level 4 → chartHighlight 1.0（圓放大 1.15×）
 */

/** 參考「今天」= catalog 截圖日（runtime Date() 的凍結值）。 */
const REFERENCE_TODAY = new Date(2026, 5, 11) // 2026-06-11（月份 0-indexed）

function dayKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

/** gradedActivity：過去 120 天中 offset%4 != 0 的日子，count = (offset%13)+1（循環 1...13）。 */
function gradedActivity(): Record<string, number> {
  const a: Record<string, number> = {}
  for (let offset = 0; offset < 120; offset++) {
    if (offset % 4 === 0) continue
    a[dayKey(addDays(REFERENCE_TODAY, -offset))] = (offset % 13) + 1
  }
  return a
}

/** sparseActivity：每 11 天一個 count=1 的低活躍日。 */
function sparseActivity(): Record<string, number> {
  const a: Record<string, number> = {}
  for (let offset = 0; offset < 120; offset += 11) {
    a[dayKey(addDays(REFERENCE_TODAY, -offset))] = 1
  }
  return a
}

export type HeatmapScenario = {
  activity: Record<string, number>
  /** intensity thresholds [t0,t1,t2]；< 3 個 → flat level 1 */
  thresholds: number[]
  weeks: number
}

export const VOCAB_HEATMAP_FIXTURES: Record<
  ScenarioId<'vocab-heatmap'>,
  HeatmapScenario
> = {
  'dense-graded': { activity: gradedActivity(), thresholds: [2, 5, 9], weeks: 20 },
  empty: { activity: {}, thresholds: [2, 5, 9], weeks: 20 },
  'no-thresholds': { activity: gradedActivity(), thresholds: [], weeks: 20 },
  'short-range': { activity: gradedActivity(), thresholds: [2, 5, 9], weeks: 8 },
  sparse: { activity: sparseActivity(), thresholds: [2, 5, 9], weeks: 20 },
}

/** 參考日，供 Screen 重建 grid。 */
export const HEATMAP_REFERENCE_TODAY = REFERENCE_TODAY
