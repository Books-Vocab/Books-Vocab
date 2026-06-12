import type { ScenarioId } from '../../harness/scenarios'
import {
  VOCAB_HEATMAP_FIXTURES,
  HEATMAP_REFERENCE_TODAY,
  type HeatmapScenario,
} from './fixtures'
import './vocab-heatmap.css'

/**
 * VocabActivityHeatmap surface — iOS `VocabActivityHeatmap`
 * (Views/Vocabulary/Components/VocabActivityHeatmap.swift) 的 web 鏡像。
 *
 * iOS view tree：
 *   VStack(alignment:.leading, spacing: appSkin.spacing.microGap=6) {
 *     ScrollView(.horizontal) { HStack(alignment:.top, spacing:0) {
 *       // weekday labels: VStack(.trailing, spacing:0)，7 列，僅 row 0/2/4/6 顯字
 *       VStack(.trailing){ ForEach(0..<7){ row in
 *         labeled(row∈{0,2,4,6}) ? Text(一/三/五/日).monoLabel.quaternaryText.frame(h:16)
 *                                : Color.clear.frame(h:16) }}.padding(.trailing, 6)
 *       // grid: HStack(spacing:3){ ForEach(weeks){ VStack(spacing:3){ ForEach(7days){ cell }}}}
 *     }}.onAppear{ scrollTo(last, .trailing) }   // 對齊到最新一週（trailing）
 *     // Legend: HStack(spacing:6){ Text(少) ●●●● Text(多) }
 *   }.padding(16)
 *
 * cell：count==0 → 透明（不畫圓）；否則畫 Circle(levelColor)，
 *       level≥3 圓放大 1.15×，外框固定 13×13 維持 grid 間距。
 *
 * grid 由 buildGrid 依「本週一」回推 weeks 週；以固定參考日 2026-06-11 重建（見 fixtures）。
 * ScrollView 已 scrollTo(.trailing) → 只看得到最右側（最新）幾週；web 以
 * overflow + 容器寬限制等效呈現（intrinsic crop 涵蓋全 grid，截圖對齊靠 crop selector）。
 *
 * catalog component scene 透明畫布（corner srgba 0,0,0,0）→ crop=component + transparent。
 */

const CELL = 13 // cellSize pt
const SPACING = 3 // cellSpacing pt
const WEEKDAY_LABELS = ['一', '三', '五', '日'] // i18n-allow: zh 短週名 一/三/五/日（Mon/Wed/Fri/Sun，every-other-row）
const LABELED_ROWS = [0, 2, 4, 6] // weekdayIndices（Monday=0）

type Cell = { key: string; count: number; isFuture: boolean }

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

/** 對齊 buildGrid：找本週一，回推 weeks 週，每欄 7 天（Mon..Sun）。 */
function buildGrid(activity: Record<string, number>, weeks: number): Cell[][] {
  const today = HEATMAP_REFERENCE_TODAY
  // 本週一：getDay() 週日=0，Mon=1。算出到本週一的偏移。
  const dow = today.getDay() // 0..6
  const deltaToMonday = dow === 0 ? -6 : 1 - dow
  const thisMonday = addDays(today, deltaToMonday)

  const columns: Cell[][] = []
  for (let weekOffset = -(weeks - 1); weekOffset <= 0; weekOffset++) {
    const weekStart = addDays(thisMonday, weekOffset * 7)
    const column: Cell[] = []
    for (let dayOffset = 0; dayOffset < 7; dayOffset++) {
      const date = addDays(weekStart, dayOffset)
      const key = dayKey(date)
      column.push({ key, count: activity[key] ?? 0, isFuture: date > today })
    }
    columns.push(column)
  }
  return columns
}

function intensityLevel(count: number, thresholds: number[]): number {
  if (count <= 0) return 0
  if (thresholds.length < 3) return 1
  if (count <= thresholds[0]) return 1
  if (count <= thresholds[1]) return 2
  if (count <= thresholds[2]) return 3
  return 4
}

export function VocabHeatmapScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-heatmap'>
}) {
  const fixture: HeatmapScenario = VOCAB_HEATMAP_FIXTURES[scenario]
  const grid = buildGrid(fixture.activity, fixture.weeks)

  return (
    <div className="vocab-heatmap-surface">
      <div className="vocab-heatmap-stack">
        <div className="vocab-heatmap-grid-row">
          {/* weekday labels：7 列，僅 0/2/4/6 顯字 */}
          <div className="vocab-heatmap-weekdays">
            {Array.from({ length: 7 }, (_, row) => {
              const labelIdx = LABELED_ROWS.indexOf(row)
              return (
                <div key={row} className="vocab-heatmap-weekday-cell">
                  {labelIdx >= 0 ? WEEKDAY_LABELS[labelIdx] : ''}
                </div>
              )
            })}
          </div>
          {/* grid：weeks 欄 × 7 天 */}
          <div className="vocab-heatmap-grid">
            {grid.map((column, w) => (
              <div key={w} className="vocab-heatmap-week">
                {column.map((cell) => {
                  if (cell.isFuture) {
                    return <div key={cell.key} className="vocab-heatmap-cell" />
                  }
                  const level = intensityLevel(cell.count, fixture.thresholds)
                  return (
                    <div key={cell.key} className="vocab-heatmap-cell">
                      {level > 0 && (
                        <span
                          className="vocab-heatmap-dot"
                          data-level={level}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
        {/* Legend：少 ●●●● 多 */}
        <div className="vocab-heatmap-legend">
          <span className="vocab-heatmap-legend-label">少{/* i18n-allow: zh 圖例「少」 */}</span>
          {[1, 2, 3, 4].map((level) => (
            <span key={level} className="vocab-heatmap-dot" data-level={level} />
          ))}
          <span className="vocab-heatmap-legend-label">多{/* i18n-allow: zh 圖例「多」 */}</span>
        </div>
      </div>
    </div>
  )
}

export const __HEATMAP_GEOMETRY = { CELL, SPACING }
