import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardResponse } from '../../api/types'

/**
 * Vocab · Add Link 的 API store — shell=1 時取代 fixture。從 GET /api/vocab 拉本
 * 單字本的卡片作候選池，依查詢過濾（排除來源卡自身），點候選 → POST /api/graph/links
 * 建立來源卡 → 候選卡的手動連結（quota-gated LLM judge，mock 立即回）。
 *
 * 誠實邊界：source word / notebookId 來源 = ShellNavContext.params 優先、
 * window.location.search fallback。parity 路徑（無 shell）不呼叫此 hook。
 */

export type AddLinkStatus = 'loading' | 'ready' | 'error'
export type LinkCreateState = 'idle' | 'creating' | 'created' | 'error'

/** 候選列（其他卡）。 */
export interface CandidateRow {
  id: string
  word: string
  translation: string
}

/**
 * 純函式：依查詢過濾候選卡（排除來源卡自身、不分大小寫比對 word/meaning）。
 * query 為空 → 回空陣列（鏡射 iOS AddLinkSheet：空查詢顯示空態，不列全部）。
 * 匯出供測試。
 */
export function filterCandidates(
  cards: CardResponse[],
  sourceWord: string | null,
  query: string,
): CandidateRow[] {
  const q = query.trim().toLowerCase()
  if (q.length === 0) return []
  return cards
    .filter((c) => !c.isArchived && !c.isDeleted)
    .filter((c) => c.content !== sourceWord)
    .filter((c) => c.content.toLowerCase().includes(q) || c.meaning.toLowerCase().includes(q))
    .map((c) => ({ id: c.id, word: c.content, translation: c.meaning }))
}

export interface VocabAddLinkApiState {
  status: AddLinkStatus
  createState: LinkCreateState
  sourceWord: string | null
  query: string
  candidates: CandidateRow[]
  setQuery: (q: string) => void
  /** 建立來源卡 → 候選卡的連結。 */
  createLink: (candidateId: string) => void
  retry: () => void
}

export function useVocabAddLinkApiStore(): VocabAddLinkApiState {
  const api = useApi()
  const nav = useShellNav()
  const search = new URLSearchParams(window.location.search)
  const sourceWord = nav.params.word ?? search.get('word')
  const notebookId = nav.params.notebookId ?? search.get('notebook_id') ?? undefined

  const [status, setStatus] = useState<AddLinkStatus>('loading')
  const [cards, setCards] = useState<CardResponse[]>([])
  const [query, setQuery] = useState('')
  const [createState, setCreateState] = useState<LinkCreateState>('idle')

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const all = await api.vocabulary.list(notebookId ? { notebookId } : {})
      setCards(all)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  const candidates = useMemo(
    () => filterCandidates(cards, sourceWord, query),
    [cards, sourceWord, query],
  )

  const createLink = useCallback(
    (candidateId: string) => {
      const sourceCard = cards.find((c) => c.content === sourceWord)
      if (!sourceCard) {
        setCreateState('error')
        return
      }
      setCreateState('creating')
      api.graph
        .create({ from_id: sourceCard.id, to_id: candidateId }, notebookId ? { notebookId } : {})
        .then(() => setCreateState('created'))
        .catch(() => setCreateState('error'))
    },
    [api, cards, notebookId, sourceWord],
  )

  return {
    status,
    createState,
    sourceWord: sourceWord ?? null,
    query,
    candidates,
    setQuery: (q) => {
      setQuery(q)
      setCreateState('idle')
    },
    createLink,
    retry: load,
  }
}
