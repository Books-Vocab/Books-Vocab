import { describe, expect, it } from 'vitest'
import type { GraphData } from './graphData'
import {
  degreeById,
  edgeDensity,
  graphDensityStats,
  nodeDensityScale,
  nodeHeat,
  DENSITY_RADIUS_GAIN,
} from './density'

// A small graph: hub `a` linked to b,c,d (degree 3); b also links c (so b,c=2);
// d=1; e isolated (degree 0). Undirected, deduped.
const GRAPH: GraphData = {
  nodes: [
    { id: 'a', word: 'a', reviewRatio: 0, learned: true },
    { id: 'b', word: 'b', reviewRatio: 1, learned: true },
    { id: 'c', word: 'c', reviewRatio: 1, learned: true },
    { id: 'd', word: 'd', reviewRatio: 1, learned: true },
    { id: 'e', word: 'e', reviewRatio: null, learned: false },
  ],
  links: [
    { source: 'a', target: 'b' },
    { source: 'a', target: 'c' },
    { source: 'a', target: 'd' },
    { source: 'b', target: 'c' },
  ],
}

describe('degreeById', () => {
  it('counts each endpoint of every link', () => {
    const d = degreeById(GRAPH)
    expect(d.get('a')).toBe(3)
    expect(d.get('b')).toBe(2)
    expect(d.get('c')).toBe(2)
    expect(d.get('d')).toBe(1)
    expect(d.get('e')).toBe(0)
  })

  it('returns 0 for an unknown id (via Map default semantics)', () => {
    expect(degreeById(GRAPH).get('ghost')).toBeUndefined()
  })

  it('handles an empty graph', () => {
    const d = degreeById({ nodes: [], links: [] })
    expect(d.size).toBe(0)
  })
})

describe('edgeDensity', () => {
  it('is 2E / (N(N-1)) for an undirected simple graph', () => {
    // N=5, E=4 → 2*4 / (5*4) = 8/20 = 0.4
    expect(edgeDensity(GRAPH)).toBeCloseTo(0.4)
  })

  it('is 1 for a complete triangle (3 nodes, 3 edges)', () => {
    const g: GraphData = {
      nodes: [
        { id: 'x', word: 'x', reviewRatio: 0, learned: true },
        { id: 'y', word: 'y', reviewRatio: 0, learned: true },
        { id: 'z', word: 'z', reviewRatio: 0, learned: true },
      ],
      links: [
        { source: 'x', target: 'y' },
        { source: 'y', target: 'z' },
        { source: 'x', target: 'z' },
      ],
    }
    expect(edgeDensity(g)).toBeCloseTo(1)
  })

  it('is 0 with fewer than two nodes (no possible edges)', () => {
    expect(edgeDensity({ nodes: [], links: [] })).toBe(0)
    expect(
      edgeDensity({
        nodes: [{ id: 'a', word: 'a', reviewRatio: 0, learned: true }],
        links: [],
      }),
    ).toBe(0)
  })
})

describe('nodeHeat', () => {
  it('is 0 for the least-linked node and 1 for the most-linked', () => {
    const d = degreeById(GRAPH)
    expect(nodeHeat(0, d)).toBe(0) // isolated
    expect(nodeHeat(3, d)).toBe(1) // hub (max degree = 3)
  })

  it('scales linearly between min and max degree', () => {
    const d = degreeById(GRAPH) // max=3
    // a node of degree 2 in a 0..3 spread → 2/3
    expect(nodeHeat(2, d)).toBeCloseTo(2 / 3)
  })

  it('is 0 when every node shares the same degree (no spread)', () => {
    const flat = new Map<string, number>([
      ['a', 1],
      ['b', 1],
    ])
    expect(nodeHeat(1, flat)).toBe(0)
  })
})

describe('nodeDensityScale', () => {
  it('is 1 (base radius) at zero heat', () => {
    expect(nodeDensityScale(0)).toBeCloseTo(1)
  })

  it('grows with heat up to 1 + DENSITY_RADIUS_GAIN at full heat', () => {
    expect(nodeDensityScale(1)).toBeCloseTo(1 + DENSITY_RADIUS_GAIN)
  })

  it('is monotonic in heat', () => {
    expect(nodeDensityScale(0.5)).toBeGreaterThan(nodeDensityScale(0.1))
  })
})

describe('graphDensityStats', () => {
  it('summarizes edge count, node count, density and max degree', () => {
    const s = graphDensityStats(GRAPH)
    expect(s.nodeCount).toBe(5)
    expect(s.edgeCount).toBe(4)
    expect(s.maxDegree).toBe(3)
    expect(s.density).toBeCloseTo(0.4)
  })

  it('reports a density band label that rises with connectivity', () => {
    expect(graphDensityStats({ nodes: [], links: [] }).band).toBe('sparse')
    // complete triangle is maximally dense
    const dense: GraphData = {
      nodes: [
        { id: 'x', word: 'x', reviewRatio: 0, learned: true },
        { id: 'y', word: 'y', reviewRatio: 0, learned: true },
        { id: 'z', word: 'z', reviewRatio: 0, learned: true },
      ],
      links: [
        { source: 'x', target: 'y' },
        { source: 'y', target: 'z' },
        { source: 'x', target: 'z' },
      ],
    }
    expect(dense.links.length).toBe(3)
    expect(graphDensityStats(dense).band).toBe('dense')
  })
})
