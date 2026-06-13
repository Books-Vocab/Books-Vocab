// Self-contained force-directed graph simulation — zero dependencies.
//
// Replaces the iOS `GraphWebView` (a WKWebView running d3-force in graph.html).
// Per P7e: NO WKWebView, no heavy deps. This is a small velocity-Verlet style
// integrator with the same three force knobs the iOS `GraphForces` exposes
// (center / repel / link) plus display knobs (link distance / node size / link
// thickness) — so the settings drawer sliders drive a real layout.
//
// Every function here is PURE and deterministic (seeded layout, no Math.random),
// which keeps the rendered DOM stable and makes the simulation unit-testable.

import type { GraphLink, GraphNode } from './graphData'

/** Mirrors iOS `GraphForces` (KnowledgeGraphPresenter PreviewData defaults). */
export interface ForceConfig {
  /** 向心力 — pull toward viewport center. 0…1. */
  centerForce: number
  /** 排斥力 — node-node repulsion. 0…1. */
  repelForce: number
  /** 連結強度 — spring stiffness on links. 0…1. */
  linkForce: number
  /** 連結距離 — spring rest length, px. 20…300. */
  linkDistance: number
  /** 節點大小 — node radius, px. 1…10. */
  nodeSize: number
  /** 連結粗細 — edge stroke width, px. 0.5…3. */
  linkThickness: number
}

/** iOS PreviewData force values (VocabScenarios.swift). */
export const DEFAULT_FORCES: ForceConfig = {
  centerForce: 0.24,
  repelForce: 0.76,
  linkForce: 0.32,
  linkDistance: 120,
  nodeSize: 4.2,
  linkThickness: 1.1,
}

/** iOS GraphForces slider bounds — used by both clamp + slider rendering. */
export const FORCE_BOUNDS: Record<keyof ForceConfig, [number, number]> = {
  centerForce: [0, 1],
  repelForce: [0, 1],
  linkForce: [0, 1],
  linkDistance: [20, 300],
  nodeSize: [1, 10],
  linkThickness: [0.5, 3],
}

function clamp(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return lo
  return Math.max(lo, Math.min(hi, v))
}

/** Clamp every force value into its iOS GraphForces range. */
export function clampForces(f: ForceConfig): ForceConfig {
  return {
    centerForce: clamp(f.centerForce, ...FORCE_BOUNDS.centerForce),
    repelForce: clamp(f.repelForce, ...FORCE_BOUNDS.repelForce),
    linkForce: clamp(f.linkForce, ...FORCE_BOUNDS.linkForce),
    linkDistance: clamp(f.linkDistance, ...FORCE_BOUNDS.linkDistance),
    nodeSize: clamp(f.nodeSize, ...FORCE_BOUNDS.nodeSize),
    linkThickness: clamp(f.linkThickness, ...FORCE_BOUNDS.linkThickness),
  }
}

/** A positioned simulation node (layout state, separate from the GraphNode datum). */
export interface SimNode {
  id: string
  x: number
  y: number
  vx: number
  vy: number
}

// ── deterministic seeding ────────────────────────────────────────────────────
// A tiny string hash → [0,1) PRNG so layout is reproducible from node ids alone
// (no Math.random → identical DOM every render, parity/snapshot safe).
function hash01(s: string): number {
  let h = 2166136261 >>> 0
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619) >>> 0
  }
  // xorshift mix for better spread, then normalize.
  h ^= h << 13
  h ^= h >>> 17
  h ^= h << 5
  return ((h >>> 0) % 100000) / 100000
}

/**
 * Seed nodes on a deterministic circle around the center (good convergence,
 * stable across runs). Returns one SimNode per GraphNode, in input order.
 */
export function initialLayout(nodes: GraphNode[], width: number, height: number): SimNode[] {
  const cx = width / 2
  const cy = height / 2
  const r = Math.max(10, Math.min(width, height) * 0.32)
  return nodes.map((n, i) => {
    const jitter = hash01(n.id)
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2 + jitter * 0.6
    const radius = r * (0.6 + jitter * 0.4)
    return {
      id: n.id,
      x: clamp(cx + Math.cos(angle) * radius, 0, width),
      y: clamp(cy + Math.sin(angle) * radius, 0, height),
      vx: 0,
      vy: 0,
    }
  })
}

const DAMPING = 0.82
const MAX_VELOCITY = 6
// Scale factors map the 0…1 force sliders onto pixel-meaningful accelerations.
const REPEL_SCALE = 1600
const CENTER_SCALE = 0.05
const LINK_SCALE = 0.08

/**
 * Advance the simulation one tick. PURE: returns a new SimNode[], never mutates
 * the input. Bounded velocity + viewport clamping keep nodes finite and on-screen
 * even for coincident or pathological inputs.
 */
export function stepSimulation(
  nodes: SimNode[],
  links: GraphLink[],
  rawForces: ForceConfig,
  width: number,
  height: number,
): SimNode[] {
  const f = clampForces(rawForces)
  const cx = width / 2
  const cy = height / 2

  // Work on a copy so the input is untouched.
  const next: SimNode[] = nodes.map((n) => ({ ...n }))
  const byId = new Map(next.map((n) => [n.id, n]))

  // Pairwise repulsion (O(n^2) — fine for the tens-of-nodes graphs here).
  for (let i = 0; i < next.length; i++) {
    for (let j = i + 1; j < next.length; j++) {
      const a = next[i]
      const b = next[j]
      let dx = a.x - b.x
      let dy = a.y - b.y
      let dist2 = dx * dx + dy * dy
      if (dist2 < 0.01) {
        // Coincident: nudge deterministically apart so force is finite.
        dx = (hash01(a.id + b.id) - 0.5) || 0.5
        dy = (hash01(b.id + a.id) - 0.5) || 0.5
        dist2 = dx * dx + dy * dy
      }
      const dist = Math.sqrt(dist2)
      const force = (f.repelForce * REPEL_SCALE) / dist2
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      a.vx += fx
      a.vy += fy
      b.vx -= fx
      b.vy -= fy
    }
  }

  // Link springs (Hooke toward rest length).
  for (const link of links) {
    const a = byId.get(link.source)
    const b = byId.get(link.target)
    if (!a || !b) continue
    let dx = b.x - a.x
    let dy = b.y - a.y
    let dist = Math.sqrt(dx * dx + dy * dy)
    if (dist < 0.001) {
      dx = 0.001
      dy = 0
      dist = 0.001
    }
    const displacement = dist - f.linkDistance
    const spring = displacement * f.linkForce * LINK_SCALE
    const fx = (dx / dist) * spring
    const fy = (dy / dist) * spring
    a.vx += fx
    a.vy += fy
    b.vx -= fx
    b.vy -= fy
  }

  // Centering + integration.
  for (const n of next) {
    n.vx += (cx - n.x) * f.centerForce * CENTER_SCALE
    n.vy += (cy - n.y) * f.centerForce * CENTER_SCALE

    n.vx *= DAMPING
    n.vy *= DAMPING
    n.vx = clamp(n.vx, -MAX_VELOCITY, MAX_VELOCITY)
    n.vy = clamp(n.vy, -MAX_VELOCITY, MAX_VELOCITY)

    n.x = clamp(n.x + n.vx, 0, width)
    n.y = clamp(n.y + n.vy, 0, height)
  }

  return next
}

/**
 * Run the simulation to a (near-)stable layout in one shot. Deterministic given
 * the same inputs — used for the static/initial render so the graph appears
 * already settled rather than visibly bouncing on mount.
 */
export function runSimulation(
  nodes: GraphNode[],
  links: GraphLink[],
  forces: ForceConfig,
  width: number,
  height: number,
  iterations = 120,
): SimNode[] {
  let sim = initialLayout(nodes, width, height)
  for (let i = 0; i < iterations; i++) {
    sim = stepSimulation(sim, links, forces, width, height)
  }
  return sim
}
