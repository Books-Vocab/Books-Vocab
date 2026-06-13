import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { useGesture } from '@use-gesture/react'
import { gentle, snappy } from '../../motion'
import { resolveCanvasSize } from './canvasSize'
import {
  initialLayout,
  runSimulation,
  stepSimulation,
  type ForceConfig,
  type SimNode,
} from './forceGraph'
import { nodeColor, type GraphData } from './graphData'
import {
  IDENTITY_VIEWPORT,
  clampScale,
  clientToUser,
  panBy,
  screenDeltaToUser,
  zoomAround,
  type Viewport,
} from './useGraphViewport'

/**
 * Self-contained, INTERACTIVE SVG force-graph — the web replacement for the iOS
 * `GraphWebView` (WKWebView/d3-force). No WKWebView, no graph deps: nodes/links
 * are plain SVG elements positioned by the `forceGraph` velocity-Verlet
 * simulation, animated with requestAnimationFrame and re-settled live as the
 * slider forces change.
 *
 * FEEL layer (Phase 2):
 *   • Pan / zoom — `@use-gesture` drag on the empty canvas pans; wheel + pinch
 *     zoom toward the cursor. The viewport transform lives in SVG user-space (a
 *     wrapper <g translate/scale>), composed via `useGraphViewport` math.
 *   • Drag-nodes — `@use-gesture` drag on a node pins it under the pointer and
 *     keeps it pinned afterwards (the sim relaxes the rest around it), mirroring
 *     d3-force's fx/fy drag-pin.
 *   • Node-tap feedback — a tap (no drag) selects a node: it springs up via the
 *     `snappy` motion preset and gets a focus ring. (There is no nav edge OUT of
 *     this surface in the shell nav graph, so tap stays a local selection — see
 *     the surface report; not a shell change.)
 *   • Entry + settle — the graph fades/scales in on mount (`gentle` preset) and
 *     the rAF relaxation visibly settles the layout.
 *
 * Reduced motion: every animation routes through framer-motion's
 * `useReducedMotion()` — entry becomes an instant appear, node-tap drops its
 * spring, and the rAF settle is pre-converged (one-shot `runSimulation`) so no
 * visible bouncing occurs. Pan/zoom/drag remain available (they are direct
 * manipulation, not decorative motion).
 *
 * Determinism: layout is seeded from node ids (no Math.random), so the first
 * settled frame is reproducible. The component is mounted ONLY inside the shell
 * (?shell=1) — the parity capture path never renders it, so the byte-identical
 * fixture render is preserved.
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
  const prefersReduced = useReducedMotion()

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

  // ── pinned nodes (drag-pin) ────────────────────────────────────────────────
  // A dragged node is pinned: the sim relaxes everything else around its held
  // position (mirrors d3-force fx/fy). Stored in a ref so the rAF loop reads the
  // latest pins without re-subscribing every drag tick.
  const pinnedRef = useRef<Map<string, { x: number; y: number }>>(new Map())
  // Re-pin pinned nodes onto a freshly-stepped layout (pure helper, no state).
  const applyPins = useCallback((nodes: SimNode[]): SimNode[] => {
    const pins = pinnedRef.current
    if (pins.size === 0) return nodes
    return nodes.map((n) => {
      const p = pins.get(n.id)
      return p ? { ...n, x: p.x, y: p.y, vx: 0, vy: 0 } : n
    })
  }, [])

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
    // Pins are layout-space; a re-seed (new node set / resized box) invalidates
    // them, so clear before settling the new layout.
    pinnedRef.current = new Map()
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
    // Reduced motion: the layout is already pre-converged by runSimulation on
    // (re)seed, so we skip the visible rAF relaxation entirely — no bouncing.
    if (prefersReduced) return
    let raf = 0
    let frames = 0
    const tick = () => {
      setSim((prev) =>
        applyPins(stepSimulation(prev, linksRef.current, forcesRef.current, cw, ch)),
      )
      frames++
      // Run ~3s of relaxation then idle to avoid a permanent rAF burn; the layout
      // is settled by then. Slider changes remount the effect via deps and re-run.
      if (frames < 180) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // Restart the loop whenever forces/links identity OR the canvas box changes so
    // dragging a slider / resizing the pane re-energizes the layout.
  }, [forces, visible.links, cw, ch, prefersReduced, applyPins])

  const posById = useMemo(() => {
    const m = new Map<string, SimNode>()
    for (const n of sim) m.set(n.id, n)
    return m
  }, [sim])

  // ── viewport (pan / zoom) ──────────────────────────────────────────────────
  const [viewport, setViewport] = useState<Viewport>(IDENTITY_VIEWPORT)
  // Latest box/scale read inside gesture handlers without re-binding.
  const boxRef = useRef({ cw, ch })
  boxRef.current = { cw, ch }
  const viewportRef = useRef(viewport)
  viewportRef.current = viewport

  /** Pixel rect of the SVG (for client→user conversions). */
  const svgRect = useCallback(() => svgRef.current?.getBoundingClientRect() ?? null, [])

  // Background pan (drag on empty canvas) + wheel/pinch zoom toward cursor.
  const bindCanvas = useGesture(
    {
      onDrag: ({ delta: [dx, dy], pinching, tap }) => {
        if (pinching || tap) return // pinch handled separately; taps don't pan
        const r = svgRect()
        const { cw: w, ch: h } = boxRef.current
        const u = screenDeltaToUser(dx, dy, r?.width ?? 0, r?.height ?? 0, w, h)
        setViewport((vp) => panBy(vp, u.dx, u.dy))
      },
      onWheel: ({ delta: [, wy], event }) => {
        event.preventDefault()
        const r = svgRect()
        const { cw: w, ch: h } = boxRef.current
        const px = r ? (event as WheelEvent).clientX - r.left : 0
        const py = r ? (event as WheelEvent).clientY - r.top : 0
        const { ax, ay } = clientToUser(px, py, r?.width ?? 0, r?.height ?? 0, w, h)
        // Exponential so each notch scales by a constant factor (smooth zoom).
        const factor = Math.exp(-wy * 0.0015)
        setViewport((vp) => zoomAround(vp, vp.scale * factor, ax, ay))
      },
      onPinch: ({ offset: [scale], origin: [ox, oy] }) => {
        const r = svgRect()
        const { cw: w, ch: h } = boxRef.current
        const px = r ? ox - r.left : 0
        const py = r ? oy - r.top : 0
        const { ax, ay } = clientToUser(px, py, r?.width ?? 0, r?.height ?? 0, w, h)
        setViewport((vp) => zoomAround(vp, scale, ax, ay))
      },
    },
    {
      drag: { filterTaps: true, pointer: { touch: true } },
      wheel: { eventOptions: { passive: false } },
      pinch: { scaleBounds: { min: clampScale(0), max: clampScale(Infinity) }, rubberband: false },
    },
  )

  // ── node interaction (drag-pin + tap-select) ───────────────────────────────
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draggingId, setDraggingId] = useState<string | null>(null)

  // Latest positions for the node-drag seed (avoids stale closure on posById).
  const posByIdRef = useRef(posById)
  posByIdRef.current = posById

  const bindNode = useGesture(
    {
      onDrag: ({ args, delta: [dx, dy], tap, first, last, event }) => {
        // Drag must not also pan the canvas behind it.
        event.stopPropagation()
        const id = args[0] as string
        // filterTaps surfaces a clean tap (no movement) on release → select it
        // locally (no nav edge out of this surface in the shell graph; see report).
        if (tap) {
          if (last) setSelectedId((cur) => (cur === id ? null : id))
          return
        }
        if (first) setDraggingId(id)
        const r = svgRect()
        const { cw: w, ch: h } = boxRef.current
        const vp = viewportRef.current
        // Convert the screen delta to user units, then undo the zoom so the node
        // tracks the pointer 1:1 regardless of current zoom.
        const u = screenDeltaToUser(dx, dy, r?.width ?? 0, r?.height ?? 0, w, h)
        const ux = u.dx / vp.scale
        const uy = u.dy / vp.scale
        // Seed the pin from the live sim position the first time the node moves.
        const live = posByIdRef.current.get(id)
        const cur = pinnedRef.current.get(id) ?? (live ? { x: live.x, y: live.y } : { x: w / 2, y: h / 2 })
        const next = { x: cur.x + ux, y: cur.y + uy }
        pinnedRef.current.set(id, next)
        // Reflect immediately so the dragged node follows the pointer even when
        // the rAF loop is idle (reduced motion) or between frames.
        setSim((prev) => prev.map((nd) => (nd.id === id ? { ...nd, ...next, vx: 0, vy: 0 } : nd)))
        if (last) setDraggingId(null)
      },
    },
    { drag: { filterTaps: true, pointer: { touch: true } } },
  )

  const entry = prefersReduced
    ? { initial: false as const, animate: { opacity: 1 } }
    : {
        initial: { opacity: 0, scale: 0.96 },
        animate: { opacity: 1, scale: 1 },
        transition: gentle,
      }

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
      data-dragging={draggingId ? '1' : undefined}
      style={{ touchAction: 'none' }}
      {...bindCanvas()}
    >
      {/* Viewport group: pan/zoom transform in SVG user-space. transform-origin
          stays at the user-space origin so the math in useGraphViewport holds. */}
      <motion.g
        {...entry}
        transform={`translate(${viewport.tx} ${viewport.ty}) scale(${viewport.scale})`}
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
            const isSelected = selectedId === n.id
            const isDragging = draggingId === n.id
            const targetScale = isSelected || isDragging ? (prefersReduced ? 1.25 : 1.3) : 1
            // The gesture binding (which carries plain React event handlers) lives
            // on a plain <g>; the spring scale lives on an inner motion.g so the
            // two prop surfaces never collide (framer-motion redefines a few of
            // the DOM handler types the @use-gesture bind also provides).
            return (
              <g
                key={n.id}
                className="vkg-graph-node-group"
                data-selected={isSelected ? '1' : undefined}
                transform={`translate(${p.x} ${p.y})`}
                style={{ cursor: 'grab' }}
                {...bindNode(n.id)}
              >
                <motion.g
                  animate={{ scale: targetScale }}
                  transition={prefersReduced ? { duration: 0 } : snappy}
                  style={{ transformOrigin: '0px 0px' }}
                >
                  {/* Focus ring for the tapped node — drawn behind the dot. */}
                  {isSelected ? (
                    <circle
                      r={forces.nodeSize + 4}
                      className="vkg-graph-node-ring"
                      fill="none"
                    />
                  ) : null}
                  <circle
                    r={forces.nodeSize}
                    fill={colorById.get(n.id)}
                    className="vkg-graph-node"
                  />
                  <text
                    x={0}
                    y={forces.nodeSize + 10}
                    textAnchor="middle"
                    className="vkg-graph-node-label"
                  >
                    {n.word}
                  </text>
                </motion.g>
              </g>
            )
          })}
        </g>
      </motion.g>
    </svg>
  )
}

/** Exposed for tests / external callers needing a one-shot settled layout. */
export { initialLayout }
