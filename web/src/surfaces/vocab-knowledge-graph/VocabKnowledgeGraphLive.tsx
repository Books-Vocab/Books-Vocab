import { useMemo, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { gentle } from '../../motion'
import { GraphNodesIcon, XmarkIcon } from './icons'
import {
  REVIEW_GRADIENT_BAR_STOPS,
  LEGEND_COLORS,
} from './fixtures'
import { ForceGraphCanvas } from './ForceGraphCanvas'
import { hasLinks, type GraphData } from './graphData'
import { graphDensityStats } from './density'
import { type ForceConfig } from './forceGraph'
import {
  formatForceValue,
  sliderFill,
  useForceStore,
  type ForceStore,
} from './store'
import { useKnowledgeGraphApiStore } from './useKnowledgeGraphApiStore'

/**
 * Live (?shell=1) Knowledge Graph — drives a real, dependency-free force-directed
 * SVG graph from the backend via `useKnowledgeGraphApiStore` (graph.list +
 * vocabulary.list, fused by `toGraphFromApi`). The settings drawer sliders mutate
 * the live `ForceConfig` and persist it to the `auto_link` config group via
 * `user.updateConfig`.
 *
 * This component is ONLY mounted behind the shell gate — the parity capture path
 * (no ?shell=1) renders the untouched static fixture screen, so the byte-identical
 * snapshot DOM is preserved.
 *
 * `emptyVariant` pins the empty-state demo scenarios from the catalog (so those
 * scenarios still render their fixed copy under the shell). When undefined (the
 * default/populated scenario) the surface fetches real data:
 *   - 'empty'    → static "知識圖譜為空" card (scenario-pinned, no fetch).
 *   - 'no-links' → static "尚無知識連結" card (scenario-pinned, no fetch).
 *   - undefined  → live force graph over the backend's GraphData.
 */
export function VocabKnowledgeGraphLive({
  emptyVariant,
}: {
  emptyVariant?: 'empty' | 'no-links'
}) {
  const store = useForceStore()
  const [showSettings, setShowSettings] = useState(false)

  // Scenario-pinned empty demos render their fixed copy without touching the API
  // (these are catalog scenarios, not live data). Default scenario → live fetch.
  if (emptyVariant === 'empty' || emptyVariant === 'no-links') {
    return <PinnedEmptyState variant={emptyVariant} store={store} />
  }

  return (
    <LiveGraph store={store} showSettings={showSettings} setShowSettings={setShowSettings} />
  )
}

/** Live data path: fetch the real graph, then render loading / ready / error / empty. */
function LiveGraph({
  store,
  showSettings,
  setShowSettings,
}: {
  store: ForceStore
  showSettings: boolean
  setShowSettings: React.Dispatch<React.SetStateAction<boolean>>
}) {
  const { status, graph, retry } = useKnowledgeGraphApiStore()

  if (status === 'loading') {
    return (
      <EmptyCard
        title="載入知識圖譜…"
        description="正在與伺服器同步單字與連結。"
      />
    )
  }

  if (status === 'error') {
    return (
      <EmptyCard
        title="無法載入知識圖譜"
        description="與伺服器連線時發生問題，請稍後再試。"
        action={{ label: '重試', onClick: retry }}
      />
    )
  }

  return (
    <GraphView
      graph={graph}
      store={store}
      showSettings={showSettings}
      setShowSettings={setShowSettings}
    />
  )
}

/** Scenario-pinned empty demos (catalog 'empty' / 'no-links') — no fetch. */
function PinnedEmptyState({
  variant,
  store,
}: {
  variant: 'empty' | 'no-links'
  store: ForceStore
}) {
  if (variant === 'no-links') {
    return (
      <EmptyCard
        title="尚無知識連結"
        description="持續收錄相關單字，系統會自動建立關聯。或在設定中開啟「孤立節點」以瀏覽所有單字。"
        action={{ label: '顯示孤立節點', onClick: store.toggleIsolated }}
      />
    )
  }
  return (
    <EmptyCard
      title="知識圖譜為空"
      description="尚無已收錄單字，或尚未與伺服器同步。"
    />
  )
}

/** Centered empty / loading / error card (no legend / no canvas) — shared chrome. */
function EmptyCard({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: { label: string; onClick: () => void }
}) {
  return (
    <div className="vkg-surface vkg-surface--empty" data-live="1">
      <div className="vkg-empty-card">
        <div className="vkg-empty-content">
          <GraphNodesIcon className="vkg-empty-icon" size={30} strokeWidth={1.4} />
          <div className="vkg-empty-title">{title}</div>
          <div className="vkg-empty-description">{description}</div>
          {action ? (
            <button type="button" className="vkg-empty-action" onClick={action.onClick}>
              {action.label}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/**
 * Presentational graph view over a resolved `GraphData`. Renders the force canvas
 * + legend + settings when there's something to draw; otherwise the data-driven
 * empty / no-links card (mirroring iOS `KnowledgeGraphPresentation.emptyState`:
 * synced words but no links → "尚無知識連結"; nothing at all → "知識圖譜為空").
 */
function GraphView({
  graph,
  store,
  showSettings,
  setShowSettings,
}: {
  graph: GraphData
  store: ForceStore
  showSettings: boolean
  setShowSettings: React.Dispatch<React.SetStateAction<boolean>>
}) {
  // Empty / no-links → centered empty card (no legend / no canvas), unless the
  // user opens 孤立節點 on the no-links graph (then we render the isolated nodes).
  const renderableLinks = hasLinks(graph)
  const showIsolatedNodes = store.showIsolated && graph.nodes.length > 0
  const showCanvas = renderableLinks || showIsolatedNodes

  if (!showCanvas) {
    const hasNodes = graph.nodes.length > 0
    if (hasNodes) {
      return (
        <EmptyCard
          title="尚無知識連結"
          description="持續收錄相關單字，系統會自動建立關聯。或在設定中開啟「孤立節點」以瀏覽所有單字。"
          action={{ label: '顯示孤立節點', onClick: store.toggleIsolated }}
        />
      )
    }
    return (
      <EmptyCard
        title="知識圖譜為空"
        description="尚無已收錄單字，或尚未與伺服器同步。"
      />
    )
  }

  return (
    <div className="vkg-surface" data-live="1">
      <div className="vkg-graph-host">
        <ForceGraphCanvas
          graph={graph}
          forces={store.forces}
          showIsolated={store.showIsolated}
        />
      </div>

      <LiveLegend />

      {/* Density indicator — conveys the graph's overall link density (sparse →
          dense) so a richly-linked vocabulary reads visually denser. */}
      <DensityIndicator graph={graph} />

      {/* Drawer toggle (gear chip) — opens the live settings overlay. */}
      <button
        type="button"
        className="vkg-gear-button"
        aria-label="關聯圖設定"
        aria-expanded={showSettings}
        onClick={() => setShowSettings((s) => !s)}
      >
        <GraphNodesIcon className="vkg-gear-icon" size={15} strokeWidth={1.5} />
      </button>

      {showSettings ? (
        <LiveSettingsOverlay store={store} onClose={() => setShowSettings(false)} />
      ) : null}
    </div>
  )
}

/** Static legend chip (re-rendered live; identical to the parity legend). */
function LiveLegend() {
  return (
    <div className="vkg-legend">
      <div className="vkg-legend-bar">
        {REVIEW_GRADIENT_BAR_STOPS.map((c, i) => (
          // token-allow review-gradient stop
          <span key={i} className="vkg-legend-bar-seg" style={{ background: c }} />
        ))}
      </div>
      <div className="vkg-legend-labels">
        {/* token-allow ReviewGradient.color(for:) data colors */}
        <span className="vkg-legend-label" style={{ color: LEGEND_COLORS.safe }}>
          安全
        </span>
        <span className="vkg-legend-spacer" />
        <span className="vkg-legend-label" style={{ color: LEGEND_COLORS.due }}>
          到期
        </span>
        <span className="vkg-legend-spacer" />
        <span className="vkg-legend-label" style={{ color: LEGEND_COLORS.overdue }}>
          逾期
        </span>
      </div>
      <div className="vkg-legend-unlearned">
        <span className="vkg-legend-dot" />
        <span className="vkg-legend-unlearned-text">未學習 / 封存</span>
      </div>
    </div>
  )
}

/** Coarse Chinese label per density band (presentational only). */
const DENSITY_BAND_LABEL: Record<'sparse' | 'moderate' | 'dense', string> = {
  sparse: '稀疏',
  moderate: '中等',
  dense: '緊密',
}

/**
 * Edge-density indicator chip (live/shell only) — a compact readout of how richly
 * the vocabulary is interlinked: a filled density bar (realised vs. possible
 * edges), the band label, and the edge/node counts. The fill width IS the
 * density signal, so a denser graph literally reads as a fuller bar. Entry uses
 * the shared `gentle` motion preset and collapses to an instant appear under
 * prefers-reduced-motion.
 */
function DensityIndicator({ graph }: { graph: GraphData }) {
  const prefersReduced = useReducedMotion()
  const stats = useMemo(() => graphDensityStats(graph), [graph])
  const pct = Math.round(stats.density * 100)
  const entry = prefersReduced
    ? { initial: false as const, animate: { opacity: 1 } }
    : { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: gentle }

  return (
    <motion.div
      className="vkg-density"
      data-band={stats.band}
      role="status"
      aria-label={`連結密度 ${DENSITY_BAND_LABEL[stats.band]}，${stats.edgeCount} 條連結、${stats.nodeCount} 個節點`}
      {...entry}
    >
      <div className="vkg-density-head">
        <span className="vkg-density-title">連結密度</span>
        <span className="vkg-density-band">{DENSITY_BAND_LABEL[stats.band]}</span>
      </div>
      <div className="vkg-density-bar">
        <span className="vkg-density-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="vkg-density-meta">
        {stats.edgeCount} 連結 · {stats.nodeCount} 節點
      </div>
    </motion.div>
  )
}

type ForceRow = { field: keyof ForceConfig; label: string; min: number; max: number; step: number }

const FORCE_ROWS: ForceRow[] = [
  { field: 'centerForce', label: '向心力', min: 0, max: 1, step: 0.01 },
  { field: 'repelForce', label: '排斥力', min: 0, max: 1, step: 0.01 },
  { field: 'linkForce', label: '連結強度', min: 0, max: 1, step: 0.01 },
  { field: 'linkDistance', label: '連結距離', min: 20, max: 300, step: 1 },
]

const DISPLAY_ROWS: ForceRow[] = [
  { field: 'nodeSize', label: '節點大小', min: 1, max: 10, step: 0.1 },
  { field: 'linkThickness', label: '連結粗細', min: 0.5, max: 3, step: 0.1 },
]

/** Interactive settings drawer — real sliders bound to the live force store. */
function LiveSettingsOverlay({
  store,
  onClose,
}: {
  store: ReturnType<typeof useForceStore>
  onClose: () => void
}) {
  return (
    <div className="vkg-settings">
      <div className="vkg-settings-card">
        <div className="vkg-overlay-header">
          <button type="button" className="vkg-inline-action" onClick={store.reset}>
            重設
          </button>
          <span className="vkg-overlay-title">
            <GraphNodesIcon className="vkg-overlay-title-icon" size={13} strokeWidth={1.5} />
            <span>關聯圖</span>
          </span>
          <span className="vkg-overlay-spacer" />
          <button type="button" className="vkg-chrome-button" aria-label="關閉" onClick={onClose}>
            <XmarkIcon className="vkg-chrome-icon" size={15} strokeWidth={1.6} />
          </button>
        </div>

        <div className="vkg-overlay-divider" />

        <div className="vkg-settings-body">
          <div className="vkg-settings-section">
            <div className="vkg-section-header">
              <span className="vkg-section-header-title">力</span>
            </div>
            {FORCE_ROWS.map((row) => (
              <LiveSliderRow key={row.field} row={row} store={store} />
            ))}
          </div>

          <div className="vkg-card-section-divider" />

          <div className="vkg-settings-section">
            <div className="vkg-section-header">
              <span className="vkg-section-header-title">顯示</span>
            </div>
            {DISPLAY_ROWS.map((row) => (
              <LiveSliderRow key={row.field} row={row} store={store} />
            ))}

            <div className="vkg-toggle-row">
              <span className="vkg-toggle-label">孤立節點</span>
              <button
                type="button"
                className="vkg-toggle-switch"
                role="switch"
                aria-checked={store.showIsolated}
                aria-label="孤立節點"
                data-on={store.showIsolated ? '1' : undefined}
                onClick={store.toggleIsolated}
              >
                <span className="vkg-toggle-knob" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/** A single live slider row — native range input styled over the track. */
function LiveSliderRow({
  row,
  store,
}: {
  row: ForceRow
  store: ReturnType<typeof useForceStore>
}) {
  const value = store.forces[row.field]
  const fill = sliderFill(row.field, value)
  return (
    <div className="vkg-slider-row">
      <span className="vkg-slider-label">{row.label}</span>
      <span className="vkg-slider-track vkg-slider-track--live">
        <span className="vkg-slider-fill" style={{ width: `${fill * 100}%` }} />
        <input
          type="range"
          className="vkg-slider-input"
          min={row.min}
          max={row.max}
          step={row.step}
          value={value}
          aria-label={row.label}
          onChange={(e) => store.setForce(row.field, Number(e.target.value))}
        />
      </span>
      <span className="vkg-slider-value">{formatForceValue(row.field, value)}</span>
    </div>
  )
}
