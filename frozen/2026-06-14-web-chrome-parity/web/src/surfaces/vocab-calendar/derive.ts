import type { ReviewEventEntry } from '../../api/types'
import type { CalendarFixture } from './fixtures'

/**
 * vocab-calendar 的純衍生 — 鏡像 iOS：日曆顯示「當月」每日的複習活動次數，活動量
 * 來源為 review event log（每筆 event = 一次複習），對齊 `ReviewActivityLog.activity`
 * 以 local dayKey 聚合（StatsPresentation.buildSummary → activity[String:Int]）。
 *
 * 顯示「當月」（now 的年月）+ today = now 的日；activity 只取落在當月、依「日」聚合的
 * count。selectedDay 在 shell 模式無預設選中（null），對齊 iOS Stats 進入時未選日。
 */

/** local 年-月-日 → 與 iOS dayKey（Calendar.current 本地時區）對齊。 */
function localDayParts(iso: string): { year: number; month: number; day: number } | null {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return { year: d.getFullYear(), month: d.getMonth(), day: d.getDate() }
}

export function deriveCalendarFixture(
  events: ReviewEventEntry[],
  now: Date = new Date(),
): CalendarFixture {
  const year = now.getFullYear()
  const month = now.getMonth() // 0-indexed
  const today = now.getDate()

  const activity: Record<number, number> = {}
  for (const event of events) {
    const parts = localDayParts(event.reviewed_at)
    if (!parts) continue
    if (parts.year !== year || parts.month !== month) continue
    activity[parts.day] = (activity[parts.day] ?? 0) + 1
  }

  return { year, month, activity, selectedDay: null, today }
}
