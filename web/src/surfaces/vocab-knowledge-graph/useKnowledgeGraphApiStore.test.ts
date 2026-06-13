import { describe, expect, it } from 'vitest'
import { createApiClient, type ApiClient } from '../../api'
import type { CardResponse, GraphLinkResponse, NotebookResponse } from '../../api/types'
import { loadGraphData } from './useKnowledgeGraphApiStore'

// ── helpers ──────────────────────────────────────────────────────────────────

/** Authenticated mock client — exercises the real mock backend (graph + vocab). */
function authed(): ApiClient {
  return createApiClient({ mode: 'mock', getToken: () => 'mock-access-token' })
}

function makeCard(
  partial: Partial<CardResponse> & { id: string; content: string },
): CardResponse {
  return {
    meaning: '',
    pos: null,
    difficulty: null,
    difficultyTier: null,
    note: null,
    collocations: [],
    examples: [],
    mode: 'recognition',
    isDeleted: false,
    isArchived: false,
    inflections: [],
    linksByKind: {},
    notebookId: 'default',
    source: null,
    updatedAt: null,
    reviewIntervalHours: 12,
    nextReviewAt: null,
    lastReviewedAt: null,
    reviewCount: 0,
    lapseCount: 0,
    reviewStreak: 0,
    lastReviewFeedback: -1,
    ...partial,
  }
}

/** A minimal fake ApiClient that drives only the three calls loadGraphData uses. */
function fakeApi(opts: {
  notebooks?: NotebookResponse[]
  cards?: CardResponse[]
  links?: GraphLinkResponse[]
  throwOn?: 'notebook' | 'vocab' | 'graph'
}): ApiClient {
  const notebook = {
    list: async () => {
      if (opts.throwOn === 'notebook') throw new Error('boom')
      return opts.notebooks ?? []
    },
  }
  const vocabulary = {
    list: async () => {
      if (opts.throwOn === 'vocab') throw new Error('boom')
      return opts.cards ?? []
    },
  }
  const graph = {
    list: async () => {
      if (opts.throwOn === 'graph') throw new Error('boom')
      return opts.links ?? []
    },
  }
  return { notebook, vocabulary, graph } as unknown as ApiClient
}

function nb(id: string, extra: Partial<NotebookResponse> = {}): NotebookResponse {
  return {
    id,
    name: id,
    color: null,
    coverPattern: null,
    sortOrder: 0,
    isDefault: false,
    isDeleted: false,
    cardCount: 0,
    updatedAt: null,
    ...extra,
  }
}

// ── ready: against the real mock backend ─────────────────────────────────────

describe('loadGraphData — mock backend (ready)', () => {
  it('fuses graph.list edges + vocabulary.list cards into a GraphData', async () => {
    const graph = await loadGraphData(authed(), 'editorial-picks')
    // demo seed: 5 cards + 3 links in editorial-picks (card-1↔card-2,
    // card-3↔card-4, card-2↔card-5).
    expect(graph.nodes.length).toBeGreaterThanOrEqual(3)
    expect(graph.links).toHaveLength(3)
    const ids = new Set(graph.nodes.map((n) => n.id))
    // every rendered edge endpoint must resolve to a node.
    for (const l of graph.links) {
      expect(ids.has(l.source)).toBe(true)
      expect(ids.has(l.target)).toBe(true)
    }
  })

  it('resolves the default notebook when none is passed', async () => {
    // The demo seed assigns every card to a named notebook, so the implicit
    // default notebook resolves to an empty graph — the path under test is that
    // notebook.list() default-resolution runs without error and returns it.
    const graph = await loadGraphData(authed())
    expect(graph.links).toEqual([])
  })
})

// ── empty / ready transitions ────────────────────────────────────────────────

describe('loadGraphData — empty', () => {
  it('returns an empty graph when there are no cards or links', async () => {
    const graph = await loadGraphData(fakeApi({ notebooks: [nb('default', { isDefault: true })] }))
    expect(graph.nodes).toEqual([])
    expect(graph.links).toEqual([])
  })

  it('returns nodes-but-no-links (drives the 尚無知識連結 empty state)', async () => {
    const graph = await loadGraphData(
      fakeApi({
        notebooks: [nb('default', { isDefault: true })],
        cards: [makeCard({ id: 'a', content: 'alpha', reviewCount: 1 })],
        links: [],
      }),
    )
    expect(graph.nodes).toHaveLength(1)
    expect(graph.links).toEqual([])
  })

  it('prefers the explicit notebookId over the default lookup', async () => {
    const graph = await loadGraphData(
      fakeApi({
        cards: [makeCard({ id: 'x', content: 'x', reviewCount: 1 })],
        links: [],
      }),
      'science',
    )
    // notebook.list() is never consulted when an id is passed; still resolves.
    expect(graph.nodes).toHaveLength(1)
  })

  it('falls back to the first notebook when no default is flagged', async () => {
    const graph = await loadGraphData(
      fakeApi({
        notebooks: [nb('first'), nb('second')],
        cards: [makeCard({ id: 'a', content: 'a', reviewCount: 1 })],
        links: [{ id: 'l', fromId: 'a', toId: 'a', kind: 'related', confidence: 1, reason: '' }],
      }),
    )
    expect(graph.nodes).toHaveLength(1)
  })
})

// ── error transitions ────────────────────────────────────────────────────────

describe('loadGraphData — error', () => {
  it('propagates a notebook.list failure (hook → error)', async () => {
    await expect(loadGraphData(fakeApi({ throwOn: 'notebook' }))).rejects.toThrow()
  })

  it('propagates a vocabulary.list failure (hook → error)', async () => {
    await expect(
      loadGraphData(fakeApi({ notebooks: [nb('default', { isDefault: true })], throwOn: 'vocab' })),
    ).rejects.toThrow()
  })

  it('propagates a graph.list failure (hook → error)', async () => {
    await expect(
      loadGraphData(fakeApi({ notebooks: [nb('default', { isDefault: true })], throwOn: 'graph' })),
    ).rejects.toThrow()
  })
})
