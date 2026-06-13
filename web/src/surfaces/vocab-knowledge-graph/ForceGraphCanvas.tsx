import { useEffect, useMemo, useRef, useState } from 'react'
import { resolveCanvasSize } from './canvasSize'
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
  /** Fallback dimensions used until the ResizeObserver reports the real box
   *  (and for SSR / node renders where layout is unmeasured). */
  width?: number
  height?: number
}) {
  // Measure the REAL rendered box so the force layout runs in actual pixel space
  // (fills the container) instead of a fixed 360×560 virtual box that gets scaled
  // — scaling clusters nodes in a virtual top-left corner and distorts on a wide
  // content pane. The SVG fills its host at 100%×100%, so its own client box is
  // the host's content box. Before the observer fires we use the fixed fallback,
  // so the phone-frame (<768) behaviour and tests are unchanged.
  const svgRef = useRef<SVGSVGElement>(null)
  const [measured, setMeasured] = useState<{ w: number; h: number }>({ w: 0, h: 0 })
  useEffect(() => {
    const el = svgRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const apply = () => setMeasured({ w: el.clientWidth, h: el.clientHeight })
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const { width: cw, height: ch } = resolveCanvasSize(measured.w, measured.h, width, height)

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
  // then keep nudging it live as forces change. Layout runs in the resolved
  // (measured-or-fallback) box `cw`×`ch` so it fills the real container.
  const [sim, setSim] = useState<SimNode[]>(() =>
    runSimulation(visible.nodes, visible.links, forces, cw, ch),
  )

  // Re-seed when the node set OR the canvas box changes (different graph / toggle /
  // resize) so the layout re-settles into the new dimensions rather than scaling.
  const nodeKey = visible.nodes.map((n) => n.id).join(',')
  const seedKey = `${nodeKey}@${cw}x${ch}`
  const seededRef = useRef(seedKey)
  if (seededRef.current !== seedKey) {
    seededRef.current = seedKey
    // Settle the new node set synchronously for a stable first paint.
    // (setState during render is allowed by React when conditional + cheap.)
    setSim(runSimulation(visible.nodes, visible.links, forces, cw, ch))
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
      setSim((prev) => stepSimulation(prev, linksRef.current, forcesRef.current, cw, ch))
      frames++
      // Run ~3s of relaxation then idle to avoid a permanent rAF burn; the layout
      // is settled by then. Slider changes remount the effect via deps and re-run.
      if (frames < 180) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // Restart the loop whenever forces/links identity OR the canvas box changes so
    // dragging a slider / resizing the pane re-energizes the layout.
  }, [forces, visible.links, cw, ch])

  const posById = useMemo(() => {
    const m = new Map<string, SimNode>()
    for (const n of sim) m.set(n.id, n)
    return m
  }, [sim])

  return (
    <svg
      ref={svgRef}
      className="vkg-graph-canvas"
      viewBox={`0 0 ${cw} ${ch}`}
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
