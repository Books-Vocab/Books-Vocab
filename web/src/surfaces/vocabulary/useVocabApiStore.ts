import { useMemo, useState } from 'react'
import type { CardResponse } from '../../api/types'
import { useVocabCardsQuery } from '../../data/vocab'
import type { RowReviewState, VocabRowFixture } from './fixtures'
import type { VocabFilter, VocabInteractionState } from './store'
import { filterRows } from './store'

/**
 * API-backed vocabulary store — 當 shell=1 時取代 fixture-driven useVocabStore。
 * 資料引擎已遷移到 P2 資料層的 useVocabCardsQuery（TanStack Query）：取得 GET
 * /api/vocab?notebook_id=xxx 的真實卡片並映射到既有 VocabRowFixture 形狀（JSX 零變動），
 * 換得跨 surface cache / dedup、正確 retry 策略與 staleTime。搜尋/過濾/展開仍是本地
 * UI 狀態（與資料無關，留在本 hook）。非 ready 態由 VocabSceneShell 包裹。
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
  const cardsQuery = useVocabCardsQuery(notebookId)
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState<VocabFilter>(null)
  const [expandedWord, setExpandedWord] = useState<string | null>(null)

  const rows = useMemo<VocabRowFixture[]>(
    () => (cardsQuery.data ?? []).map(toVocabRow),
    [cardsQuery.data],
  )

  // status 映射：有資料 → ready（背景 refetch 不退回 loading）；已 settle 的錯誤 →
  // error；其餘（初次 pending、或從 error 觸發 retry 而正在 refetch）→ loading。
  // 後者忠實重現原 retry()「先 loading 再 ready/error」的行為。
  let status: VocabApiStatus
  if (cardsQuery.data !== undefined) status = 'ready'
  else if (cardsQuery.isError && !cardsQuery.isFetching) status = 'error'
  else status = 'loading'

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
    retry: () => {
      void cardsQuery.refetch()
    },
  }
}
