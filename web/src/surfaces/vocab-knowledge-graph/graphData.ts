// Knowledge-graph domain data for the web force-graph renderer.
//
// Mirrors the iOS presentation model `KnowledgeGraphNode` / `KnowledgeGraphEdge`
// (ios/.../Presentation/KnowledgeGraphPresentation.swift) and the review-state
// coloring of `ReviewGradient` (the same gradient the legend chip already shows).
//
// Data source contract (P7e):
//   The functional shell wants `useApi().graph.list(notebookId)` for nodes/links.
//   In this worktree the GraphClient / useApi() context (P1) is NOT yet present
//   (it lands on `main` via a parallel workflow; api/* + shell/* are FROZEN here
//   and must not be edited — that would conflict with the P1 merge). So the live
//   path stays offline against a local mock graph below; `toGraphFromCards` is the
//   adapter that will consume `graph.list` rows verbatim once the client exists.
//   See report: mock route `GET /api/graph` / GraphClient.list is genuinely missing.

import { LEGEND_COLORS, REVIEW_GRADIENT_BAR_STOPS } from './fixtures'

/** A single vocabulary node in the knowledge graph (iOS KnowledgeGraphNode). */
export interface GraphNode {
  id: string
  word: string
  /**
   * Review urgency ratio 0…~2.5 (safe → due → overdue), the same scalar the iOS
   * `ReviewGradient.color(for:)` consumes. `null` = unlearned / archived (grey).
   */
  reviewRatio: number | null
  /** false = unlearned / archived → rendered with the muted grey legend dot color. */
  learned: boolean
}

/** A directed-but-rendered-undirected edge between two nodes (iOS KnowledgeGraphEdge). */
export interface GraphLink {
  source: string
  target: string
}

export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
}

/**
 * Color a node by its review ratio, matching the legend gradient. Unlearned /
 * archived nodes use the muted grey dot color (legend "未學習 / 封存").
 *
 * The gradient bar in fixtures has 20 stops spanning ratio 0…3 (i/19*3). We pick
 * the nearest stop so node fills line up with the legend the user already sees.
 */
export function nodeColor(node: GraphNode): string {
  if (!node.learned || node.reviewRatio == null) {
    // legend unlearned dot = quaternary @ 50%; opaque grey approximation.
    return '#9b9a96' // token-allow: ReviewGradient unlearned/archived grey (matches legend dot)
  }
  const ratio = Math.max(0, Math.min(3, node.reviewRatio))
  const stops = REVIEW_GRADIENT_BAR_STOPS
  const idx = Math.round((ratio / 3) * (stops.length - 1))
  return stops[Math.max(0, Math.min(stops.length - 1, idx))]
}

/** Legend label colors re-exported for callers that want the named anchors. */
export { LEGEND_COLORS }

/**
 * Local mock graph — a small connected component plus a couple of weakly-linked
 * and isolated nodes, exercising every legend band (safe / due / overdue / unlearned).
 * Deterministic so the shell render is stable offline.
 */
export const MOCK_GRAPH: GraphData = {
  nodes: [
    { id: 'ephemeral', word: 'ephemeral', reviewRatio: 0.2, learned: true },
    { id: 'transient', word: 'transient', reviewRatio: 0.5, learned: true },
    { id: 'fleeting', word: 'fleeting', reviewRatio: 0.9, learned: true },
    { id: 'ubiquitous', word: 'ubiquitous', reviewRatio: 1.0, learned: true },
    { id: 'pervasive', word: 'pervasive', reviewRatio: 1.4, learned: true },
    { id: 'omnipresent', word: 'omnipresent', reviewRatio: 1.8, learned: true },
    { id: 'tenacious', word: 'tenacious', reviewRatio: 2.5, learned: true },
    { id: 'resolute', word: 'resolute', reviewRatio: 2.2, learned: true },
    { id: 'sanguine', word: 'sanguine', reviewRatio: null, learned: false },
    { id: 'pensive', word: 'pensive', reviewRatio: null, learned: false },
  ],
  links: [
    { source: 'ephemeral', target: 'transient' },
    { source: 'transient', target: 'fleeting' },
    { source: 'ephemeral', target: 'fleeting' },
    { source: 'ubiquitous', target: 'pervasive' },
    { source: 'pervasive', target: 'omnipresent' },
    { source: 'ubiquitous', target: 'omnipresent' },
    { source: 'tenacious', target: 'resolute' },
    { source: 'fleeting', target: 'pervasive' },
  ],
}

/** Empty graph (drives the kg-empty-state / no-links surface). */
export const EMPTY_GRAPH: GraphData = { nodes: [], links: [] }

/**
 * Adapter from a card list (the shape `graph.list` / `vocab.list` returns) into a
 * `GraphData`. Kept pure + tiny so it can be wired straight onto `useApi().graph.list`
 * once the P1 GraphClient lands, without touching this surface's renderer.
 */
export interface GraphCardLike {
  id: string
  word: string
  reviewRatio?: number | null
  learned?: boolean
  links?: string[]
}

export function toGraphFromCards(cards: GraphCardLike[]): GraphData {
  const ids = new Set(cards.map((c) => c.id))
  const nodes: GraphNode[] = cards.map((c) => ({
    id: c.id,
    word: c.word,
    reviewRatio: c.reviewRatio ?? null,
    learned: c.learned ?? c.reviewRatio != null,
  }))
  const seen = new Set<string>()
  const links: GraphLink[] = []
  for (const c of cards) {
    for (const target of c.links ?? []) {
      if (!ids.has(target)) continue
      const key = [c.id, target].sort().join('→')
      if (seen.has(key)) continue
      seen.add(key)
      links.push({ source: c.id, target })
    }
  }
  return { nodes, links }
}

/** Whether a graph has any links (drives the "尚無知識連結" no-links empty state). */
export function hasLinks(graph: GraphData): boolean {
  return graph.links.length > 0
}
