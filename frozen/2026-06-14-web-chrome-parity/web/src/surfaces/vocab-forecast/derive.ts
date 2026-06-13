import type { CardResponse } from '../../api/types'
import type { ForecastBucket } from './fixtures'

/**
 * vocab-forecast 的純衍生 — 鏡像 iOS `StatsPresentation.buildSummary` 的 forecast：
 *   - 只取「會出現在知識列表」的卡（!archived && !deleted；對齊 shouldAppearInKnowledgeList）。
 *     web 的 CardResponse 無 isSynced 欄位，故以 archived/deleted 為過濾依據。
 *   - 依每卡 nextReviewAt 的 local dayKey 分桶；dayKey <= todayKey → 折進「今天」桶（overdue）。
 *   - 產出 forecastDays 個桶（default 14），由今天起逐日；label = "+{i}d"（與 fixture 對齊）。
 *
 * date label 的「今天 / 1週 / 末位」顯示規則仍由 Screen 處理（與 fixture 路徑共用）。
 */

/** local 年-月-日 字串（yyyy-MM-dd），對齊 iOS Calendar.current dayKey。 */
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

export function deriveForecastBuckets(
  cards: CardResponse[],
  forecastDays = 14,
  now: Date = new Date(),
): ForecastBucket[] {
  const todayKey = dayKey(now)
  const forecastMap: Record<string, number> = {}

  for (const card of cards) {
    if (card.isArchived || card.isDeleted) continue
    // 未學卡（無 nextReviewAt）視為今天到期（與 iOS：nextReviewAt 預設為 now 一致）。
    const next = card.nextReviewAt ? new Date(card.nextReviewAt) : now
    const key = Number.isNaN(next.getTime()) ? todayKey : dayKey(next)
    const bucketKey = key <= todayKey ? todayKey : key
    forecastMap[bucketKey] = (forecastMap[bucketKey] ?? 0) + 1
  }

  const buckets: ForecastBucket[] = []
  for (let offset = 0; offset < forecastDays; offset++) {
    const key = dayKey(addDays(now, offset))
    buckets.push({ label: `+${offset}d`, count: forecastMap[key] ?? 0 })
  }
  return buckets
}
