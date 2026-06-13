import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabCalendarGrid scenario fixtures — 對齊 VocabCalendarGridScenarios.swift
 * 「Vocab Calendar」5 態。元件為純展示：displayedMonth + [dayKey: activityCount]
 * + selectedDay。
 *
 * iOS fixture 合成邏輯（VocabCalendarGridScene）：
 *   - fixedMonth() = 2024-03（除 currentMonth 外全用）
 *   - currentMonth = Date()（snapshot 捕捉於 2026-06-11，故月份 = 2026-06、today=11）
 *   - gradientActivity: day % 4 != 0 → ((day*2)%18)+1（覆蓋 1-3/4-7/8-14/15+ 全色階）
 *   - constantActivity(20): 每天 20（heavy）
 *   - daySelected: gradient + 初始選中 day=15
 *
 * activity map 在此以「日 → count」整數對映寫死（逐字等於 iOS gradient/constant
 * 演算法的輸出，見 fixtures.ts 上游量測）。month/today/selectedDay 由 fixture 帶。
 */

export type CalendarFixture = {
  /** 0-indexed month: 2024-03 → year 2024, month 2（與 JS Date 對齊） */
  year: number
  month: number // 0-indexed
  /** day(1..n) → activity count；缺鍵 = 無活動 */
  activity: Record<number, number>
  /** 初始選中的日（1..n），無則 null */
  selectedDay: number | null
  /** today 的日（1..n），無 today 在此月則 null */
  today: number | null
}

// gradient: day % 4 != 0 → ((day*2)%18)+1
function gradient(daysInMonth: number): Record<number, number> {
  const m: Record<number, number> = {}
  for (let d = 1; d <= daysInMonth; d++) {
    if (d % 4 !== 0) m[d] = ((d * 2) % 18) + 1
  }
  return m
}

// constant: 每天同一 count
function constant(daysInMonth: number, count: number): Record<number, number> {
  const m: Record<number, number> = {}
  for (let d = 1; d <= daysInMonth; d++) m[d] = count
  return m
}

const MARCH_2024_DAYS = 31
const JUNE_2026_DAYS = 30

export const VOCAB_CALENDAR_FIXTURES: Record<
  ScenarioId<'vocab-calendar'>,
  CalendarFixture
> = {
  // Active month — 2024-03 gradient，無選中、無 today
  'active-month': {
    year: 2024,
    month: 2,
    activity: gradient(MARCH_2024_DAYS),
    selectedDay: null,
    today: null,
  },
  // Day selected — 2024-03 gradient，初始選中 15
  'day-selected': {
    year: 2024,
    month: 2,
    activity: gradient(MARCH_2024_DAYS),
    selectedDay: 15,
    today: null,
  },
  // Heavy intensity — 2024-03 全 20（逼出最深 cellFill / 滿 dot）
  'heavy-intensity': {
    year: 2024,
    month: 2,
    activity: constant(MARCH_2024_DAYS, 20),
    selectedDay: null,
    today: null,
  },
  // No activity — 2024-03 空（僅日期數字 + 格線）
  'no-activity': {
    year: 2024,
    month: 2,
    activity: {},
    selectedDay: null,
    today: null,
  },
  // Current month with today — 2026-06 gradient，today=11（chartHighlight 文字色）
  'current-month': {
    year: 2026,
    month: 5,
    activity: gradient(JUNE_2026_DAYS),
    selectedDay: null,
    today: 11,
  },
}
