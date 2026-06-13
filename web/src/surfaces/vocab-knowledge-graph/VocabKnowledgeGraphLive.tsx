import { useState } from 'react'
import { GraphNodesIcon, XmarkIcon } from './icons'
import {
  REVIEW_GRADIENT_BAR_STOPS,
  LEGEND_COLORS,
} from './fixtures'
import { ForceGraphCanvas } from './ForceGraphCanvas'
import { EMPTY_GRAPH, MOCK_GRAPH, hasLinks, type GraphData } from './graphData'
import { type ForceConfig } from './forceGraph'
import {
  formatForceValue,
  sliderFill,
  useForceStore,
} from './store'

/**
 * Live (?shell=1) Knowledge Graph — drives a real, dependency-free force-directed
 * SVG graph from `loadGraphData(notebookId)` (mock-first; swaps onto
 * `useApi().graph.list` once the P1 GraphClient lands). The settings drawer
 * sliders mutate the live `ForceConfig` and persist it to the `auto_link` config
 * group via `user.updateConfig`.
 *
 * This component is ONLY mounted behind the shell gate — the parity capture path
 * (no ?shell=1) renders the untouched static fixture screen, so the byte-identical
 * snapshot DOM is preserved.
 *
 * `emptyVariant`:
 *   - 'empty'    → no nodes at all (knowledge graph empty).
 *   - 'no-links' → nodes exist but no links (尚無知識連結; toggle 孤立節點 to see them).
 *   - undefined  → live force graph over MOCK_GRAPH.
 */
export function VocabKnowledgeGraphLive({
  emptyVariant,
}: {
  emptyVariant?: 'empty' | 'no-links'
}) {
  const graph: GraphData =
    emptyVariant === 'empty'
      ? EMPTY_GRAPH
      : emptyVariant === 'no-links'
        ? { nodes: MOCK_GRAPH.nodes, links: [] }
        : MOCK_GRAPH

  const store = useForceStore()
  const [showSettings, setShowSettings] = useState(false)

  // Empty / no-links → centered empty card (no legend / no canvas), unless the
  // user opens 孤立節點 on the no-links graph (then we render the isolated nodes).
  const renderableLinks = hasLinks(graph)
  const showIsolatedNodes = store.showIsolated && graph.nodes.length > 0
  const showCanvas = renderableLinks || showIsolatedNodes

  if (!showCanvas) {
    const copy =
      emptyVariant === 'no-links'
        ? {
            title: '尚無知識連結',
            description:
              '持續收錄相關單字，系統會自動建立關聯。或在設定中開啟「孤立節點」以瀏覽所有單字。',
          }
        : {
            title: '知識圖譜為空',
            description: '尚無已收錄單字，或尚未與伺服器同步。',
          }
    return (
      <div className="vkg-surface vkg-surface--empty" data-live="1">
        <div className="vkg-empty-card">
          <div className="vkg-empty-content">
            <GraphNodesIcon className="vkg-empty-icon" size={30} strokeWidth={1.4} />
            <div className="vkg-empty-title">{copy.title}</div>
            <div className="vkg-empty-description">{copy.description}</div>
            {emptyVariant === 'no-links' ? (
              <button
                type="button"
                className="vkg-empty-action"
                onClick={store.toggleIsolated}
              >
                顯示孤立節點
              </button>
            ) : null}
          </div>
        </div>
      </div>
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
