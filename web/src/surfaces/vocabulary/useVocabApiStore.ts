import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { CardResponse } from '../../api/types'
import type { RowReviewState, VocabRowFixture } from './fixtures'
import type { VocabFilter, VocabInteractionState } from './store'
import { filterRows } from './store'

/**
 * API-backed vocabulary store — 當 shell=1 時取代 fixture-driven useVocabStore。
 * 從後端 GET /api/vocab?notebook_id=xxx 拉取真實卡片，映射到既有 VocabRowFixture
 * 形狀，使 JSX 變動最小。搜尋/過濾仍本地處理。非 ready 態由 VocabSceneShell 包裹。
 */

export type VocabApiStatus = 'loading' | 'ready' | 'error'

export interface VocabApiState extends VocabInteractionState {
  status: VocabApiStatus
  retry: () => void
}

/** 把 CardResponse 映射到既有 VocabRowFixture 形狀（最小 JSX 變動）。 */
export function toVocabRow(card: CardResponse): VocabRowFixture {
  // reviewState 由 SRS 狀態推導：nextReviewAt 為 null / 已過期 → due；reviewCount=0 → unlearned
  let reviewState: RowReviewState = 'unlearned'
  if (card.reviewCount > 0) {
    const due = card.nextReviewAt ? new Date(card.nextReviewAt) <= new Date() : true
    reviewState = due ? 'due' : 'reviewed'
  }
  // detail：unlearned 顯示首輪間隔；due 顯示「待複習」；reviewed 顯示下次複習時間
  let detail = '首輪 12h'
  if (reviewState === 'due') detail = '待複習'
  else if (reviewState === 'reviewed' && card.nextReviewAt) {
    detail = new Date(card.nextReviewAt).toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
  }

  return {
    word: card.content,
    partOfSpeech: card.pos ? `${card.pos}.` : '',
    translation: card.meaning,
    detail,
    reviewState,
    expansion: {
      explanation: card.note ?? '（尚無詳細釋義）',
      example: card.examples[0] ?? '',
    },
  }
}

export function useVocabApiStore(notebookId: string | null): VocabApiState {
  const api = useApi()
  const [status, setStatus] = useState<VocabApiStatus>('loading')
  const [rows, setRows] = useState<VocabRowFixture[]>([])
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState<VocabFilter>(null)
  const [expandedWord, setExpandedWord] = useState<string | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const cards = await api.vocabulary.list(notebookId ? { notebookId } : {})
      setRows(cards.map(toVocabRow))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  const visibleRows = useMemo(
    () => filterRows(rows, query, activeFilter),
    [rows, query, activeFilter],
  )

  const hasFilterCriteria = query.trim().length > 0 || activeFilter !== null
  const isNoMatch = rows.length > 0 && visibleRows.length === 0 && hasFilterCriteria

  return {
    status,
    query,
    activeFilter,
    expandedWord,
    visibleRows,
    isNoMatch,
    setQuery,
    toggleFilter: (f: RowReviewState) => setActiveFilter((cur) => (cur === f ? null : f)),
    toggleExpanded: (word: string) => setExpandedWord((cur) => (cur === word ? null : word)),
    retry: load,
  }
}
