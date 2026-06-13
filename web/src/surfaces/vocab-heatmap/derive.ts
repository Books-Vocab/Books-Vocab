import type { ReviewEventEntry } from '../../api/types'
import type { HeatmapScenario } from './fixtures'

/**
 * vocab-heatmap 的純衍生 — 鏡像 iOS：
 *   - activity：review event log 依 local dayKey 聚合（對齊 ReviewActivityLog.activity）。
 *   - thresholds：自適應強度分級，對齊 StatsPresentation.buildSummary：
 *       nonZeroCounts = sorted([count for count in activity.values if count > 0])
 *       若 < 4 筆 → [1, 2, 3]（simple fallback）
 *       否則 → [p25, p50, p75]（index = n/4, n/2, n*3/4，與 Swift 整數除法一致）。
 *   - weeks：固定 20 週（對齊 catalog dense scene 預設；grid 由 Screen 依 today 回推）。
 */

const HEATMAP_WEEKS = 20

/** local 年-月-日 字串（yyyy-MM-dd），對齊 Screen buildGrid dayKey。 */
function dayKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function deriveActivity(events: ReviewEventEntry[]): Record<string, number> {
  const activity: Record<string, number> = {}
  for (const event of events) {
    const d = new Date(event.reviewed_at)
    if (Number.isNaN(d.getTime())) continue
    const key = dayKey(d)
    activity[key] = (activity[key] ?? 0) + 1
  }
  return activity
}

export function deriveThresholds(activity: Record<string, number>): number[] {
  const nonZero = Object.values(activity)
    .filter((c) => c > 0)
    .sort((a, b) => a - b)
  if (nonZero.length < 4) return [1, 2, 3]
  const n = nonZero.length
  return [nonZero[Math.floor(n / 4)]!, nonZero[Math.floor(n / 2)]!, nonZero[Math.floor((n * 3) / 4)]!]
}

export function deriveHeatmapFixture(events: ReviewEventEntry[]): HeatmapScenario {
  const activity = deriveActivity(events)
  return { activity, thresholds: deriveThresholds(activity), weeks: HEATMAP_WEEKS }
}
