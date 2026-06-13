import { describe, expect, it } from 'vitest'
import {
  DEFAULT_FORCES,
  clampForces,
  initialLayout,
  runSimulation,
  stepSimulation,
  type ForceConfig,
  type SimNode,
} from './forceGraph'
import type { GraphLink, GraphNode } from './graphData'

// ── fixture graph ────────────────────────────────────────────────────────────
const NODES: GraphNode[] = [
  { id: 'a', word: 'alpha', reviewRatio: 0, learned: true },
  { id: 'b', word: 'bravo', reviewRatio: 1, learned: true },
  { id: 'c', word: 'charlie', reviewRatio: 2.5, learned: true },
  { id: 'd', word: 'delta', reviewRatio: null, learned: false },
]
const LINKS: GraphLink[] = [
  { source: 'a', target: 'b' },
  { source: 'b', target: 'c' },
]

describe('clampForces', () => {
  it('keeps in-range values untouched', () => {
    expect(clampForces(DEFAULT_FORCES)).toEqual(DEFAULT_FORCES)
  })

  it('clamps out-of-range values to iOS GraphForces bounds', () => {
    const wild: ForceConfig = {
      centerForce: 9,
      repelForce: -3,
      linkForce: 2,
      linkDistance: 1000,
      nodeSize: 99,
      linkThickness: 0,
    }
    const c = clampForces(wild)
    expect(c.centerForce).toBe(1) // 0...1
    expect(c.repelForce).toBe(0) // 0...1
    expect(c.linkForce).toBe(1) // 0...1
    expect(c.linkDistance).toBe(300) // 20...300
    expect(c.nodeSize).toBe(10) // 1...10
    expect(c.linkThickness).toBe(0.5) // 0.5...3
  })
})

describe('initialLayout', () => {
  it('produces one positioned node per graph node, deterministically', () => {
    const a = initialLayout(NODES, 200, 200)
    const b = initialLayout(NODES, 200, 200)
    expect(a).toHaveLength(NODES.length)
    // deterministic seeding → identical between runs (parity-safe).
    expect(a.map((n) => [n.x, n.y])).toEqual(b.map((n) => [n.x, n.y]))
    // every node carries its source datum.
    expect(a.map((n) => n.id).sort()).toEqual(['a', 'b', 'c', 'd'])
    // positioned inside the viewport.
    for (const n of a) {
      expect(n.x).toBeGreaterThanOrEqual(0)
      expect(n.x).toBeLessThanOrEqual(200)
      expect(n.y).toBeGreaterThanOrEqual(0)
      expect(n.y).toBeLessThanOrEqual(200)
    }
  })

  it('returns an empty layout for an empty graph', () => {
    expect(initialLayout([], 200, 200)).toEqual([])
  })
})

describe('stepSimulation', () => {
  it('is a pure function: does not mutate its input nodes', () => {
    const nodes = initialLayout(NODES, 200, 200)
    const snapshot = nodes.map((n) => ({ ...n }))
    stepSimulation(nodes, LINKS, DEFAULT_FORCES, 200, 200)
    expect(nodes).toEqual(snapshot)
  })

  it('pulls linked nodes together when link force dominates', () => {
    // Two far-apart linked nodes, strong link + short distance, no repel.
    const far: SimNode[] = [
      { id: 'a', x: 10, y: 100, vx: 0, vy: 0 },
      { id: 'b', x: 190, y: 100, vx: 0, vy: 0 },
    ]
    const links: GraphLink[] = [{ source: 'a', target: 'b' }]
    const forces: ForceConfig = {
      ...DEFAULT_FORCES,
      repelForce: 0,
      centerForce: 0,
      linkForce: 1,
      linkDistance: 20,
    }
    const before = Math.abs(far[1].x - far[0].x)
    let nodes = far
    for (let i = 0; i < 30; i++) nodes = stepSimulation(nodes, links, forces, 200, 200)
    const after = Math.abs(nodes[1].x - nodes[0].x)
    expect(after).toBeLessThan(before)
  })

  it('pushes unlinked nodes apart when repel force dominates', () => {
    const close: SimNode[] = [
      { id: 'a', x: 99, y: 100, vx: 0, vy: 0 },
      { id: 'b', x: 101, y: 100, vx: 0, vy: 0 },
    ]
    const forces: ForceConfig = {
      ...DEFAULT_FORCES,
      repelForce: 1,
      centerForce: 0,
      linkForce: 0,
    }
    const before = Math.abs(close[1].x - close[0].x)
    let nodes = close
    for (let i = 0; i < 20; i++) nodes = stepSimulation(nodes, [], forces, 200, 200)
    const after = Math.abs(nodes[1].x - nodes[0].x)
    expect(after).toBeGreaterThan(before)
  })

  it('keeps nodes finite (no NaN/Infinity) even when coincident', () => {
    const coincident: SimNode[] = [
      { id: 'a', x: 100, y: 100, vx: 0, vy: 0 },
      { id: 'b', x: 100, y: 100, vx: 0, vy: 0 },
    ]
    let nodes = coincident
    for (let i = 0; i < 10; i++) nodes = stepSimulation(nodes, [], DEFAULT_FORCES, 200, 200)
    for (const n of nodes) {
      expect(Number.isFinite(n.x)).toBe(true)
      expect(Number.isFinite(n.y)).toBe(true)
    }
  })

  it('keeps nodes within the viewport bounds', () => {
    let nodes = initialLayout(NODES, 200, 200)
    for (let i = 0; i < 100; i++) nodes = stepSimulation(nodes, LINKS, DEFAULT_FORCES, 200, 200)
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0)
      expect(n.x).toBeLessThanOrEqual(200)
      expect(n.y).toBeGreaterThanOrEqual(0)
      expect(n.y).toBeLessThanOrEqual(200)
    }
  })
})

describe('runSimulation', () => {
  it('converges to a stable layout and is deterministic', () => {
    const a = runSimulation(NODES, LINKS, DEFAULT_FORCES, 200, 200, 120)
    const b = runSimulation(NODES, LINKS, DEFAULT_FORCES, 200, 200, 120)
    expect(a.map((n) => [n.id, n.x, n.y])).toEqual(b.map((n) => [n.id, n.x, n.y]))
    expect(a).toHaveLength(NODES.length)
  })
})
