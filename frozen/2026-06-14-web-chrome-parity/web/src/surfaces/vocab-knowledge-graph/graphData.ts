// Knowledge-graph domain data for the web force-graph renderer.
//
// Mirrors the iOS presentation model `KnowledgeGraphNode` / `KnowledgeGraphEdge`
// (ios/.../Presentation/KnowledgeGraphPresentation.swift) and the review-state
// coloring of `ReviewGradient` (the same gradient the legend chip already shows).
//
// Data source contract (P7e, now LIVE):
//   The functional shell drives nodes/links from the backend:
//     - links  = `useApi().graph.list(notebookId)`     (GraphLinkResponse[] edges)
//     - nodes  = `useApi().vocabulary.list({notebookId})` (CardResponse[] for the
//                word + review-state coloring; graph.list only carries fromId/toId)
//   `toGraphFromApi` is the adapter that fuses both into a `GraphData`, mirroring
//   the iOS `KnowledgeGraphPresentation` rules (archived excluded; reviewCount==0
//   → gray/unlearned; otherwise gradient by the elapsed/interval review ratio;
//   edges kept only when both endpoints survive). The MOCK_GRAPH below is retained
//   ONLY as the byte-identical parity capture data / offline fallback — the live
//   shell path no longer reads it (see VocabKnowledgeGraphLive).

import type { CardResponse, GraphLinkResponse } from '../../api/types'
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

// ── live API adapter ─────────────────────────────────────────────────────────
// Fuses `graph.list` (edges) + `vocabulary.list` (cards) into a `GraphData`,
// mirroring iOS `KnowledgeGraphPresentation` (Presentation/KnowledgeGraphPresentation.swift).

/**
 * Review urgency ratio for a card, matching iOS `reviewRatio(for:now:)`:
 *   startDate = lastReviewedAt ?? updatedAt (web analog of iOS `dateAdded`)
 *   interval  = max(nextReviewAt - startDate, 60s)
 *   elapsed   = max(0, now - startDate)
 *   ratio     = max(elapsed / interval, 0)
 * Returns 0 when timestamps are missing/unparseable (safe band), never negative.
 */
export function cardReviewRatio(card: CardResponse, now: number = Date.now()): number {
  const start = parseTime(card.lastReviewedAt) ?? parseTime(card.updatedAt)
  const next = parseTime(card.nextReviewAt)
  if (start == null || next == null) return 0
  const interval = Math.max(next - start, 60_000) // ≥ 60s, mirrors iOS floor
  const elapsed = Math.max(0, now - start)
  return Math.max(elapsed / interval, 0)
}

function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

/**
 * Build live `GraphData` from the backend card list + graph links.
 *
 * Node rules (iOS `KnowledgeGraphPresentation.nodes`):
 *   - archived or deleted cards are excluded entirely.
 *   - reviewCount === 0 → learned:false, reviewRatio:null (gray/unlearned dot).
 *   - otherwise         → learned:true, reviewRatio = cardReviewRatio (gradient).
 * (Degree/isolated filtering stays in the renderer's `showIsolated` toggle, so the
 * full node set is emitted here — unlike iOS which pre-filters by degree.)
 *
 * Edge rules (iOS `KnowledgeGraphPresentation.edges`):
 *   - kept only when BOTH endpoints survive as nodes; undirected-dedupe so a pair
 *     linked twice renders once.
 */
export function toGraphFromApi(
  cards: CardResponse[],
  links: GraphLinkResponse[],
  now: number = Date.now(),
): GraphData {
  const nodes: GraphNode[] = []
  const ids = new Set<string>()
  for (const c of cards) {
    if (c.isArchived || c.isDeleted) continue
    const learned = c.reviewCount > 0
    nodes.push({
      id: c.id,
      word: c.content,
      reviewRatio: learned ? cardReviewRatio(c, now) : null,
      learned,
    })
    ids.add(c.id)
  }

  const seen = new Set<string>()
  const graphLinks: GraphLink[] = []
  for (const l of links) {
    if (!ids.has(l.fromId) || !ids.has(l.toId)) continue
    const key = [l.fromId, l.toId].sort().join('→')
    if (seen.has(key)) continue
    seen.add(key)
    graphLinks.push({ source: l.fromId, target: l.toId })
  }

  return { nodes, links: graphLinks }
}
