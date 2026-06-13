import { useEffect, useMemo, useRef, useState } from 'react'
import {
  initialLayout,
  runSimulation,
  stepSimulation,
  type ForceConfig,
  type SimNode,
} from './forceGraph'
import { nodeColor, type GraphData } from './graphData'

/**
 * Self-contained SVG force-graph — the web replacement for the iOS `GraphWebView`
 * (WKWebView/d3-force). No WKWebView, no graph deps: nodes/links are plain SVG
 * elements positioned by the `forceGraph` velocity-Verlet simulation, animated
 * with requestAnimationFrame and re-settled live as the slider forces change.
 *
 * Determinism: layout is seeded from node ids (no Math.random), so the first
 * settled frame is reproducible. The rAF loop only ever runs inside the shell
 * (this component is mounted only when ?shell=1) — the parity capture path never
 * sees it, so the byte-identical fixture render is preserved.
 */
export function ForceGraphCanvas({
  graph,
  forces,
  showIsolated,
  width = 360,
  height = 560,
}: {
  graph: GraphData
  forces: ForceConfig
  showIsolated: boolean
  width?: number
  height?: number
}) {
  // Hide isolated (unlinked) nodes unless the "孤立節點" toggle is on.
  const visible = useMemo(() => {
    if (showIsolated) return graph
    const linked = new Set<string>()
    for (const l of graph.links) {
      linked.add(l.source)
      linked.add(l.target)
    }
    return {
      nodes: graph.nodes.filter((n) => linked.has(n.id)),
      links: graph.links,
    }
  }, [graph, showIsolated])

  const colorById = useMemo(() => {
    const m = new Map<string, string>()
    for (const n of visible.nodes) m.set(n.id, nodeColor(n))
    return m
  }, [visible.nodes])

  // Pre-settle so the graph appears already laid out on mount (no visible bounce),
  // then keep nudging it live as forces change.
  const [sim, setSim] = useState<SimNode[]>(() =>
    runSimulation(visible.nodes, visible.links, forces, width, height),
  )

  // Re-seed when the node set changes (different graph / toggle).
  const nodeKey = visible.nodes.map((n) => n.id).join(',')
  const seededRef = useRef(nodeKey)
  if (seededRef.current !== nodeKey) {
    seededRef.current = nodeKey
    // Settle the new node set synchronously for a stable first paint.
    // (setState during render is allowed by React when conditional + cheap.)
    setSim(runSimulation(visible.nodes, visible.links, forces, width, height))
  }

  // Live relaxation loop — a handful of ticks per frame keeps it lively but cheap.
  const forcesRef = useRef(forces)
  forcesRef.current = forces
  const linksRef = useRef(visible.links)
  linksRef.current = visible.links
  useEffect(() => {
    let raf = 0
    let frames = 0
    const tick = () => {
      setSim((prev) => stepSimulation(prev, linksRef.current, forcesRef.current, width, height))
      frames++
      // Run ~3s of relaxation then idle to avoid a permanent rAF burn; the layout
      // is settled by then. Slider changes remount the effect via deps and re-run.
      if (frames < 180) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // Restart the loop whenever forces/links identity changes so dragging a
    // slider re-energizes the layout.
  }, [forces, visible.links, width, height])

  const posById = useMemo(() => {
    const m = new Map<string, SimNode>()
    for (const n of sim) m.set(n.id, n)
    return m
  }, [sim])

  return (
    <svg
      className="vkg-graph-canvas"
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height="100%"
      role="img"
      aria-label="知識關聯圖"
      preserveAspectRatio="xMidYMid meet"
    >
      <g className="vkg-graph-links">
        {visible.links.map((l, i) => {
          const a = posById.get(l.source)
          const b = posById.get(l.target)
          if (!a || !b) return null
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              strokeWidth={forces.linkThickness}
              className="vkg-graph-edge"
            />
          )
        })}
      </g>
      <g className="vkg-graph-nodes">
        {visible.nodes.map((n) => {
          const p = posById.get(n.id)
          if (!p) return null
          return (
            <g key={n.id} transform={`translate(${p.x} ${p.y})`}>
              <circle r={forces.nodeSize} fill={colorById.get(n.id)} className="vkg-graph-node" />
              <text
                x={0}
                y={forces.nodeSize + 10}
                textAnchor="middle"
                className="vkg-graph-node-label"
              >
                {n.word}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}

/** Exposed for tests / external callers needing a one-shot settled layout. */
export { initialLayout }
