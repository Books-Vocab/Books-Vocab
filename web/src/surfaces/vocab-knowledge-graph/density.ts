// Link-DENSITY metrics for the knowledge graph — pure, deterministic, dep-free.
//
// PHASE 2 feature: convey link density visually so a richly-linked vocabulary
// reads denser. Two scales of "density":
//   • per-node  — DEGREE (how many neighbours a word has). Drives node size + a
//                 "heat" scalar so hub words render larger and warmer.
//   • per-graph — EDGE DENSITY (realised edges / possible edges) plus max degree,
//                 surfaced as a small density-indicator chip + a band label.
//
// Everything here is a pure function of `GraphData`, so it is unit-testable and
// keeps the renderer (ForceGraphCanvas) free of analytics logic.

import type { GraphData } from './graphData'

/**
 * Undirected degree per node id: how many distinct links touch each node.
 * Nodes with no links map to 0. Links are counted per endpoint (a self-edge,
 * which the data model never produces, would count twice — acceptably rare).
 * The returned Map has an entry for EVERY node (so callers can read degree by
 * id directly); unknown ids return undefined via normal Map semantics.
 */
export function degreeById(graph: GraphData): Map<string, number> {
  const deg = new Map<string, number>()
  for (const n of graph.nodes) deg.set(n.id, 0)
  for (const l of graph.links) {
    if (deg.has(l.source)) deg.set(l.source, (deg.get(l.source) ?? 0) + 1)
    if (deg.has(l.target)) deg.set(l.target, (deg.get(l.target) ?? 0) + 1)
  }
  return deg
}

/**
 * Graph-level edge density for an undirected simple graph:
 *   density = 2E / (N(N-1))      (realised edges / possible edges, 0…1)
 * 0 for fewer than two nodes (no edge is possible). A complete graph → 1.
 */
export function edgeDensity(graph: GraphData): number {
  const n = graph.nodes.length
  if (n < 2) return 0
  const possible = (n * (n - 1)) / 2
  return graph.links.length / possible
}

/** Largest degree in the Map (0 if empty). */
function maxDegree(deg: Map<string, number>): number {
  let max = 0
  for (const d of deg.values()) if (d > max) max = d
  return max
}

/** Smallest degree in the Map (0 if empty). */
function minDegree(deg: Map<string, number>): number {
  if (deg.size === 0) return 0
  let min = Infinity
  for (const d of deg.values()) if (d < min) min = d
  return min === Infinity ? 0 : min
}

/**
 * Normalise a node's degree to a 0…1 "heat" within the graph's degree SPREAD
 * (min-max), so the least-linked node reads coolest and the hub reads hottest:
 *   heat = (degree - minDegree) / (maxDegree - minDegree)
 * Returns 0 when there is no spread (every node shares one degree / no links),
 * so a flat graph reads uniformly cool rather than uniformly hot.
 */
export function nodeHeat(degree: number, deg: Map<string, number>): number {
  const max = maxDegree(deg)
  const min = minDegree(deg)
  const span = max - min
  if (span <= 0) return 0
  return Math.max(0, Math.min(1, (degree - min) / span))
}

/**
 * Extra radius multiplier a node earns from its density heat, on top of the base
 * `nodeSize`. heat 0 → 1× (base), heat 1 → (1 + DENSITY_RADIUS_GAIN)×. A gentle
 * power curve so mid-degree nodes still grow visibly without the hub dwarfing the
 * rest. Keeps the existing slider-driven `nodeSize` as the floor.
 */
export const DENSITY_RADIUS_GAIN = 1.1 // hub ≈ 2.1× the base radius at full heat

export function nodeDensityScale(heat: number): number {
  const h = Math.max(0, Math.min(1, heat))
  // sqrt eases the low end up so degree-1 vs degree-0 is already distinguishable.
  return 1 + DENSITY_RADIUS_GAIN * Math.sqrt(h)
}

export type DensityBand = 'sparse' | 'moderate' | 'dense'

export interface GraphDensityStats {
  nodeCount: number
  edgeCount: number
  /** 0…1 edge density (2E / N(N-1)). */
  density: number
  /** Highest node degree in the graph. */
  maxDegree: number
  /** Coarse band for the indicator label/heat. */
  band: DensityBand
}

/** One-shot density summary for the indicator chip. */
export function graphDensityStats(graph: GraphData): GraphDensityStats {
  const deg = degreeById(graph)
  const density = edgeDensity(graph)
  return {
    nodeCount: graph.nodes.length,
    edgeCount: graph.links.length,
    density,
    maxDegree: maxDegree(deg),
    band: density >= 0.66 ? 'dense' : density >= 0.25 ? 'moderate' : 'sparse',
  }
}
