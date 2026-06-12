import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_CALENDAR_FIXTURES, type CalendarFixture } from './fixtures'
import './vocab-calendar.css'

/**
 * VocabCalendar surface — iOS `VocabCalendarGrid`(VocabCalendarGrid.swift) 的 web 鏡像。
 *
 * iOS view tree：
 *   VStack(spacing: microGap=6) {
 *     LazyVGrid(7 cols, spacing s1=4) { 7×weekday header: Text(symbol)
 *       .font(monoLabel = mono 10 bold).foregroundStyle(quaternaryText) }
 *     LazyVGrid(7 cols, spacing s1=4) { 每 cell:
 *       blank → Color.clear.aspectRatio(1)
 *       day   → Button { VStack(spacing 1) {
 *                 Text(day).font(caption = sans 12 bold)
 *                   .foregroundStyle(today? chartHighlight : selected? primaryText : secondaryText)
 *                 Circle(dotColor or clear).frame(5×5)
 *               }.aspectRatio(1)
 *               .background(RoundedRect(tiny=6, selected? mutedFill : clear))
 *               .overlay(RoundedRect(tiny=6, count>0? cellFill(count) : clear))
 *               .overlay(RoundedRect(tiny=6, stroke cardBorder.opacity(0.5), lw 0.5)) }
 *     }
 *   }
 *
 * weekday header（Monday-first，zh）：一 二 三 四 五 六 日（量自 catalog ref）。
 *
 * cellFill(count)（chart-highlight 疊不同 opacity，米色卡片上的色階）：
 *   1-3 → 0.12, 4-7 → 0.16, 8-14 → 0.20, 15+ → 0.26
 * dotColor(count)：1-3 → 0.5, 4-7 → 0.75, 8+ → 1.0
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0）：
 * crop=component + transparent:true，crop 到 .vocab-calendar-surface。
 */

const WEEKDAY_SYMBOLS = ['一', '二', '三', '四', '五', '六', '日'] // i18n-allow: catalog ref locale = zh, Monday-first

// chart-highlight RGB（#F0CA89 = 240,202,137），cellFill 以 rgba 疊 opacity（資料色階，非 token）
const CHART_HIGHLIGHT_RGB = '240, 202, 137' // token-allow: AppColors.chartHighlight #F0CA89 衍生色階基底

function cellFillOpacity(count: number): number {
  if (count <= 3) return 0.12
  if (count <= 7) return 0.16
  if (count <= 14) return 0.2
  return 0.26
}

function dotOpacity(count: number): number {
  if (count <= 3) return 0.5
  if (count <= 7) return 0.75
  return 1.0
}

type Cell = { day: number; key: string } | null

function buildCells(fx: CalendarFixture): Cell[] {
  // mondayOffset：iOS (firstWeekday+5)%7。JS getDay: Sun=0..Sat=6 → (getDay+6)%7
  const firstDow = new Date(fx.year, fx.month, 1).getDay()
  const mondayOffset = (firstDow + 6) % 7
  const daysInMonth = new Date(fx.year, fx.month + 1, 0).getDate()

  const cells: Cell[] = []
  for (let i = 0; i < mondayOffset; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d, key: `${fx.year}-${fx.month}-${d}` })
  return cells
}

export function VocabCalendarScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-calendar'>
}) {
  const fx = VOCAB_CALENDAR_FIXTURES[scenario]
  const cells = buildCells(fx)

  return (
    <div className="vocab-calendar-surface">
      <div className="vocab-calendar-grid">
        {/* Weekday header */}
        <div className="vocab-calendar-row">
          {WEEKDAY_SYMBOLS.map((sym) => (
            <span key={sym} className="vocab-calendar-weekday">
              {sym}
            </span>
          ))}
        </div>

        {/* Day grid */}
        <div className="vocab-calendar-row vocab-calendar-days">
          {cells.map((cell, i) => {
            if (cell === null) {
              return <div key={`blank-${i}`} className="vocab-calendar-cell vocab-calendar-cell-blank" />
            }
            const count = fx.activity[cell.day] ?? 0
            const isSelected = fx.selectedDay === cell.day
            const isToday = fx.today === cell.day

            const digitClass = isToday
              ? 'vocab-calendar-digit-today'
              : isSelected
                ? 'vocab-calendar-digit-selected'
                : 'vocab-calendar-digit'

            return (
              <div key={cell.key} className="vocab-calendar-cell">
                {/* 固定 21pt 內方塊（aspectRatio .fit 內容高），欄內置中。
                    fill/stroke/selected-bg/content 全定位於此方塊。 */}
                <div className="vocab-calendar-cell-square">
                  {/* selected mutedFill 底（最底層 background） */}
                  {isSelected && <div className="vocab-calendar-cell-selected-bg" />}
                  {/* cellFill overlay（count > 0） */}
                  {count > 0 && (
                    <div
                      className="vocab-calendar-cell-fill"
                      style={{
                        background: `rgba(${CHART_HIGHLIGHT_RGB}, ${cellFillOpacity(count)})`,
                      }}
                    />
                  )}
                  {/* cardBorder.opacity(0.5) stroke overlay */}
                  <div className="vocab-calendar-cell-stroke" />
                  {/* content: digit + dot */}
                  <div className="vocab-calendar-cell-content">
                    <span className={digitClass}>{cell.day}</span>
                    <span
                      className="vocab-calendar-dot"
                      style={{
                        background:
                          count > 0
                            ? `rgba(${CHART_HIGHLIGHT_RGB}, ${dotOpacity(count)})`
                            : 'transparent',
                      }}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
