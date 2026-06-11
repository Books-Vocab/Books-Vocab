import type { ScenarioId } from '../../harness/scenarios'
import { OVERVIEW_FIXTURES } from './fixtures'
import type { HeatLevel, OverviewFixture } from './fixtures'
import {
  CalendarIcon,
  ChartBarIcon,
  ChartBarXAxisIcon,
  FlameIcon,
  GraphNodesIcon,
  TrophyIcon,
} from './icons'
import './overview.css'

/**
 * Overview surface — iOS OverviewTab → StatsPresenter（學習統計儀表板）的 web 重寫。
 * 結構順序逐一對齊 StatsPresenter.body（VStack spacing = sectionGap 14pt）：
 *   graphEntrySection（白卡：「關聯圖」header + 1:1 body，catalog WKWebView no-op →
 *     ProgressView spinner；graphLinks 空 → header 無 node/link count、有 chevron）
 *   → streakSection（連續學習 / 最長紀錄 雙卡，serif numericHero）
 *   → heatmapSection（學習日曆 header + 白卡 heatmap，trailing 叢集 + legend）
 *   → forecastSection（複習預測 header + 7/14/30 selector；chart 本體在 2556 fold
 *     之下被 capture 裁掉，故不渲染 chart 內容只渲染白卡頂緣）
 *
 * 幾何常數對齊 iOS AppSkin baseMetrics/baseSpacing（見 overview.css 的 px 註解，
 * measured 標 0608 PNG 實測值）。catalog scene 走 .fill（無 NavigationStack/nav
 * title），故 web 也 full-bleed 還原，頂部僅留 catalog 的 .fill 上 inset。
 *
 * 此 surface 為靜態呈現（鏡射凍結的 catalog 渲染輸出）——無互動 store，初始 DOM
 * 即 parity 契約。
 */

const WEEKDAY_LABELS = ['一', '三', '五', '日'] as const // iOS weekdayIndices [0,2,4,6] = 週一/三/五/日

/** 熱力圖一格：依 level 決定填色（透明/灰/amber 三階）與大小（level≥3 = 1.15×）。 */
function HeatCell({ level }: { level: HeatLevel }) {
  if (level === 0) return <span className="ov-heat-cell" aria-hidden="true" />
  return (
    <span className="ov-heat-cell" aria-hidden="true">
      <span className={`ov-heat-dot ov-heat-dot-l${level}`} />
    </span>
  )
}

function GraphCard() {
  return (
    <div className="ov-card ov-graph-card">
      <div className="ov-graph-header">
        <GraphNodesIcon size={14} className="ov-graph-icon" />
        <span className="ov-graph-title">關聯圖</span>
        <span className="ov-graph-spacer" />
        <ChevronRight />
      </div>
      {/* catalog 內 GraphThumbnailWebView no-op → loading spinner（.loading kind）。 */}
      <div className="ov-graph-body">
        <span className="ov-spinner" aria-hidden="true" />
      </div>
    </div>
  )
}

function ChevronRight() {
  return (
    <svg
      className="ov-chevron"
      viewBox="0 0 24 24"
      width={13}
      height={13}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M9 5.5 15.5 12 9 18.5" />
    </svg>
  )
}

function StatCard({
  icon,
  title,
  value,
}: {
  icon: React.ReactNode
  title: string
  value: number
}) {
  return (
    <div className="ov-card ov-stat-card">
      <div className="ov-stat-head">
        {icon}
        <span className="ov-stat-title">{title}</span>
      </div>
      <div className="ov-stat-value">
        <span className="ov-stat-num">{value}</span>
        <span className="ov-stat-unit">天</span>
      </div>
    </div>
  )
}

function HeatmapCard({ heatmap }: { heatmap: HeatLevel[][] }) {
  return (
    <div className="ov-card ov-heat-card">
      <div className="ov-heat-grid-row">
        {/* weekday labels（週一/三/五/日，monoLabel）— 每隔一列標一個。 */}
        <div className="ov-heat-labels">
          {[0, 1, 2, 3, 4, 5, 6].map((row) => (
            <span className="ov-heat-label-cell" key={row}>
              {row % 2 === 0 ? WEEKDAY_LABELS[row / 2] : ''}
            </span>
          ))}
        </div>
        {/* 可見 trailing 欄，右對齊貼齊卡片右內緣（左側留白 = 過往空欄）。 */}
        <div className="ov-heat-spacer" />
        <div className="ov-heat-cols">
          {heatmap.map((col, ci) => (
            <div className="ov-heat-col" key={ci}>
              {col.map((level, ri) => (
                <HeatCell level={level} key={ri} />
              ))}
            </div>
          ))}
        </div>
      </div>
      {/* legend：少 ●●●● 多（level 1..4） */}
      <div className="ov-heat-legend">
        <span className="ov-heat-legend-label">少</span>
        {([1, 2, 3, 4] as HeatLevel[]).map((level) => (
          <span className={`ov-heat-dot ov-heat-dot-l${level}`} key={level} />
        ))}
        <span className="ov-heat-legend-label">多</span>
      </div>
    </div>
  )
}

function ForecastSection({ selected }: { selected: 7 | 14 | 30 }) {
  return (
    <div className="ov-forecast">
      <div className="ov-section-header-row">
        <span className="ov-section-header">
          <ChartBarIcon size={12} className="ov-section-icon" />
          <span>複習預測</span>
        </span>
        <span className="ov-section-spacer" />
        <div className="ov-tab-selector" role="tablist" aria-label="複習預測天數">
          {([7, 14, 30] as const).map((days) => (
            <span
              className={`ov-tab-option${days === selected ? ' ov-tab-option-selected' : ''}`}
              key={days}
              role="tab"
              aria-selected={days === selected}
            >
              {days}天
            </span>
          ))}
        </div>
      </div>
      {/* chart 白卡本體在 2556 fold 之下被 capture 裁掉，僅渲染頂緣。 */}
      <div className="ov-card ov-forecast-card" />
    </div>
  )
}

function EmptyState() {
  return (
    <div className="ov-empty-wrap">
      <div className="ov-card ov-empty-card">
        <ChartBarXAxisIcon size={36} className="ov-empty-icon" />
        <span className="ov-empty-title">尚無學習資料</span>
        <p className="ov-empty-desc">完成同步並開始複習後，這裡會顯示你的進度與預測。</p>
      </div>
    </div>
  )
}

export function OverviewScreen({ scenario }: { scenario: ScenarioId<'overview'> }) {
  const fixture: OverviewFixture = OVERVIEW_FIXTURES[scenario]

  if (fixture.empty) {
    return (
      <div className="overview" data-scenario={scenario}>
        <EmptyState />
      </div>
    )
  }

  return (
    <div className="overview" data-scenario={scenario}>
      <div className="ov-scroll">
        <GraphCard />
        <div className="ov-streak-row">
          <StatCard
            icon={<FlameIcon size={12} className="ov-stat-icon" />}
            title="連續學習"
            value={fixture.currentStreak}
          />
          <StatCard
            icon={<TrophyIcon size={12} className="ov-stat-icon" />}
            title="最長紀錄"
            value={fixture.longestStreak}
          />
        </div>
        <div className="ov-heat-section">
          <span className="ov-section-header">
            <CalendarIcon size={12} className="ov-section-icon" />
            <span>學習日曆</span>
            <span className="ov-section-spacer" />
            <ChevronRight />
          </span>
          <HeatmapCard heatmap={fixture.heatmap} />
        </div>
        <ForecastSection selected={fixture.forecastSelected} />
      </div>
    </div>
  )
}
