// Knowledge-graph live data store — shell=1 only. Fetches the real graph from the
// backend and projects it into the `GraphData` the force renderer consumes.
//
// Sources (mirrors iOS `KnowledgeGraphPresenter` load):
//   - links = useApi().graph.list(notebookId)        (edges)
//   - cards = useApi().vocabulary.list({notebookId})  (nodes + review-state color)
// notebookId source = ShellNavContext.params.notebookId → ?notebook_id= search →
// first notebook from api.notebook.list() (the default). The parity capture path
// (no shell) never mounts this hook, so the byte-identical snapshot DOM is unchanged.

import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { ApiClient } from '../../api'
import { EMPTY_GRAPH, toGraphFromApi, type GraphData } from './graphData'

export type KnowledgeGraphStatus = 'loading' | 'ready' | 'error'

export interface KnowledgeGraphApiState {
  status: KnowledgeGraphStatus
  graph: GraphData
  retry: () => void
}

/**
 * Pure async loader — resolves the effective notebookId then fuses
 * graph.list + vocabulary.list into a GraphData. Exported for tests so the
 * load → ready/empty/error transitions can be exercised against a mock client
 * without a DOM (the codebase has no React renderer in tests).
 *
 * @throws whatever the underlying client throws (network / API error) — the hook
 *         catches it and flips to `error`.
 */
export async function loadGraphData(
  api: ApiClient,
  notebookId?: string,
  now: number = Date.now(),
): Promise<GraphData> {
  const effective = notebookId ?? (await firstNotebookId(api))
  const opts = effective ? { notebookId: effective } : {}
  const [cards, links] = await Promise.all([
    api.vocabulary.list(opts),
    api.graph.list(effective),
  ])
  return toGraphFromApi(cards, links, now)
}

/** Resolve the default notebook id (first listed) when none is carried by nav. */
async function firstNotebookId(api: ApiClient): Promise<string | undefined> {
  const notebooks = await api.notebook.list()
  const live = notebooks.filter((n) => !n.isDeleted)
  return (live.find((n) => n.isDefault) ?? live[0])?.id
}

function useNotebookParam(): string | undefined {
  const nav = useShellNav()
  if (nav.params.notebookId) return nav.params.notebookId
  return new URLSearchParams(window.location.search).get('notebook_id') ?? undefined
}

export function useKnowledgeGraphApiStore(): KnowledgeGraphApiState {
  const api = useApi()
  const notebookId = useNotebookParam()
  const [status, setStatus] = useState<KnowledgeGraphStatus>('loading')
  const [graph, setGraph] = useState<GraphData>(EMPTY_GRAPH)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const next = await loadGraphData(api, notebookId)
      setGraph(next)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  return { status, graph, retry: load }
}
