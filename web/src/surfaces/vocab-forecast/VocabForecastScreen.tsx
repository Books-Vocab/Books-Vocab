import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_FORECAST_FIXTURES, type ForecastBucket } from './fixtures'
import './vocab-forecast.css'

/**
 * VocabForecast surface — iOS `VocabForecastChart`(VocabForecastChart.swift) 的 web 鏡像。
 * 複習排程預測長條圖。
 *
 * iOS scene（ForecastScene）：
 *   AppThemeContainer { VocabForecastChart(buckets:).frame(height:160).padding() }
 *   layout .fillH → 撐滿裝置寬；.padding() = 16；frame height 160。
 *
 * iOS view tree（VocabForecastChart.body）：
 *   GeometryReader { geo in
 *     labelHeight=16; countLabelHeight = isCompact ? 0 : 14
 *     chartHeight = geo.h - labelHeight - countLabelHeight - inlineGap(8)
 *     columnWidth = geo.w / buckets.count
 *     ZStack(.bottom) {
 *       // baseline：Rectangle(divider).frame(height:1).offset(y:-labelHeight)
 *       // bars：HStack(.bottom, spacing 0) { ForEach → barColumn.frame(maxWidth:.infinity) }
 *     }.frame(maxW:.infinity, maxH:.infinity, alignment:.bottom)
 *   }
 *   isCompact = buckets.count > 14
 *   maxCount  = buckets.map(count).max()
 *
 * barColumn（VStack spacing 0）：
 *   barHeight = count>0 ? max(chartHeight * count/maxCount, 4) : 0
 *   barWidth  = columnWidth * 0.5
 *   1. count label（!compact && count>0）：Text("\(count)").font(monoLabel=mono 10 bold)
 *        .fg(tertiaryText).frame(height 14)；否則 Spacer(height: compact?0:14)
 *   2. bar area：VStack{ Spacer(minLength 0); if count>0 RoundedRect(radius xs=4)
 *        .fill(index==0 ? chartHighlight : chartHighlight.opacity(0.35))
 *        .frame(width barWidth, height barHeight) }.frame(height chartHeight)
 *   3. date label（labelHeight 16）：
 *        index==0 → "今天"
 *        index==6 && count>7（即 buckets.count>7）→ "1週"
 *        index==last → bucket.label（"+{n}d"）
 *        else → 空（Color.clear）
 *        .font(monoLabel=mono 10 bold).fg(quaternaryText)
 *
 * catalog 4 scene 畫布皆透明（alpha-mean≈0.04~0.12，.fillH 全寬透明背景）：
 * manifest transparent:true、phone-frame 背景透明。
 */
export function VocabForecastScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-forecast'>
}) {
  const { buckets } = VOCAB_FORECAST_FIXTURES[scenario]
  const isCompact = buckets.length > 14
  const maxCount = Math.max(1, ...buckets.map((b) => b.count))

  // iOS 高度常數（pt）
  const TOTAL = 160
  const labelHeight = 16
  const countLabelHeight = isCompact ? 0 : 14
  const inlineGap = 8
  const chartHeight = TOTAL - labelHeight - countLabelHeight - inlineGap

  return (
    <div className="vocab-forecast-surface" data-compact={isCompact ? '1' : undefined}>
      <div
        className="vocab-forecast-chart"
        style={
          {
            '--vf-chart-height': `${chartHeight}px`,
            '--vf-label-height': `${labelHeight}px`,
            '--vf-count-height': `${countLabelHeight}px`,
          } as CSSProperties
        }
      >
        {/* baseline：offset(y:-labelHeight) → 位於底部往上 labelHeight 處 */}
        <div className="vocab-forecast-baseline" />
        <div className="vocab-forecast-bars">
          {buckets.map((bucket, index) => (
            <BarColumn
              key={index}
              bucket={bucket}
              index={index}
              total={buckets.length}
              maxCount={maxCount}
              chartHeight={chartHeight}
              isCompact={isCompact}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function BarColumn({
  bucket,
  index,
  total,
  maxCount,
  chartHeight,
  isCompact,
}: {
  bucket: ForecastBucket
  index: number
  total: number
  maxCount: number
  chartHeight: number
  isCompact: boolean
}) {
  const barHeight =
    bucket.count > 0 ? Math.max((chartHeight * bucket.count) / maxCount, 4) : 0

  // index==0 高亮，其餘 chartHighlight.opacity(0.35)
  const isHighlight = index === 0

  // date label 規則（iOS dateLabel）
  const dateLabel: string | null = (() => {
    if (index === 0) return '今天'
    if (index === 6 && total > 7) return '1週'
    if (index === total - 1) return bucket.label
    return null
  })()

  return (
    <div className="vocab-forecast-column">
      {/* count label（!compact && count>0） */}
      {!isCompact && bucket.count > 0 ? (
        <span className="vocab-forecast-count">{bucket.count}</span>
      ) : (
        <span className="vocab-forecast-count vocab-forecast-count-spacer" aria-hidden="true" />
      )}

      {/* bar area：VStack{ Spacer; bar }.frame(height: chartHeight) → bottom-align */}
      <div className="vocab-forecast-bararea">
        {bucket.count > 0 && (
          <div
            className="vocab-forecast-bar"
            data-highlight={isHighlight ? '1' : undefined}
            style={{ height: `${barHeight}px` }}
          />
        )}
      </div>

      {/* date label */}
      <span className="vocab-forecast-date">{dateLabel ?? ' '}</span>
    </div>
  )
}
