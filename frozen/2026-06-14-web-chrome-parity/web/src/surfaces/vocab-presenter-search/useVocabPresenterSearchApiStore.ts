import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardResponse } from '../../api/types'

/**
 * Vocab Presenter (search) 的 API store — shell=1 時取代 fixture。從 GET /api/vocab
 * 拉本單字本的卡片，於 client 端做搜尋 / 三態 chip 過濾 / 排序（鏡射 iOS
 * `KGVocabView` 的 sortAndFilter + classify + KGVocabSortOption）。
 *
 * 全部運算純在記憶體內（不打額外端點）：search 比對 word/translation，filter 比對
 * classify 出的 review state，sort 走 review-priority（預設）或字母序。
 *
 * 誠實邊界：notebookId 來源 = ShellNavContext.params.notebookId 優先、?notebook_id=
 * search fallback。parity 路徑（無 shell）不呼叫此 hook，DOM 與 capture 完全不變。
 */

export type VocabSearchStatus = 'loading' | 'ready' | 'error'

/** 三態複習分類（鏡射 iOS VocabularyReviewState）。 */
export type ReviewState = 'unlearned' | 'due' | 'reviewed'

/** 排序選項（鏡射 iOS KGVocabSortOption；預設 reviewPriority =「複習優先」）。 */
export type SortOption = 'reviewPriority' | 'alphabetical'

/** 一個搜尋列（鏡射 fixtures.VocabRowFixture）。 */
export interface SearchRow {
  word: string
  partOfSpeech: string
  translation: string
  detailLabel: string
  reviewState: ReviewState
}

/** 純函式：依 SRS 狀態分類複習態（reviewCount=0 → unlearned；到期 → due；否則 reviewed）。匯出供測試。 */
export function classify(card: CardResponse, now: Date = new Date()): ReviewState {
  if (card.reviewCount <= 0) return 'unlearned'
  if (!card.nextReviewAt) return 'due'
  return new Date(card.nextReviewAt) <= now ? 'due' : 'reviewed'
}

/** 純函式：CardResponse → SearchRow（含 detailLabel）。匯出供測試。 */
export function toSearchRow(card: CardResponse, now: Date = new Date()): SearchRow {
  const reviewState = classify(card, now)
  let detailLabel = `首輪 ${card.reviewIntervalHours}h`
  if (reviewState === 'due') detailLabel = '待複習'
  else if (reviewState === 'reviewed' && card.nextReviewAt) {
    detailLabel = new Date(card.nextReviewAt).toLocaleDateString('zh-TW', {
      month: 'short',
      day: 'numeric',
    })
  }
  return {
    word: card.content,
    partOfSpeech: card.pos ? `${card.pos}.` : '',
    translation: card.meaning,
    detailLabel,
    reviewState,
  }
}

/** review-priority 排序權重：due < unlearned < reviewed（待複習最優先）。 */
const PRIORITY: Record<ReviewState, number> = { due: 0, unlearned: 1, reviewed: 2 }

/**
 * 純函式：套 query（不分大小寫，比對 word/translation）+ filter（三態 chip，null=全部）
 * + sort（review-priority / 字母序）。匯出供測試。
 */
export function searchAndSort(
  rows: SearchRow[],
  query: string,
  filter: ReviewState | null,
  sort: SortOption,
): SearchRow[] {
  const q = query.trim().toLowerCase()
  const filtered = rows.filter((r) => {
    if (filter !== null && r.reviewState !== filter) return false
    if (q.length === 0) return true
    return r.word.toLowerCase().includes(q) || r.translation.toLowerCase().includes(q)
  })
  const sorted = [...filtered]
  if (sort === 'alphabetical') {
    sorted.sort((a, b) => (a.word < b.word ? -1 : a.word > b.word ? 1 : 0))
  } else {
    sorted.sort((a, b) => {
      const pri = PRIORITY[a.reviewState] - PRIORITY[b.reviewState]
      if (pri !== 0) return pri
      return a.word < b.word ? -1 : a.word > b.word ? 1 : 0
    })
  }
  return sorted
}

/** 純函式：三態 chip count（未過濾、不受 query 影響）。匯出供測試。 */
export function classifyCounts(rows: SearchRow[]): {
  unlearned: number
  due: number
  reviewed: number
} {
  return {
    unlearned: rows.filter((r) => r.reviewState === 'unlearned').length,
    due: rows.filter((r) => r.reviewState === 'due').length,
    reviewed: rows.filter((r) => r.reviewState === 'reviewed').length,
  }
}

export interface VocabPresenterSearchApiState {
  status: VocabSearchStatus
  query: string
  filter: ReviewState | null
  sort: SortOption
  /** 三態 chip count（全集合分類，不受 query / filter 影響）。 */
  counts: { unlearned: number; due: number; reviewed: number }
  /** query + filter + sort 套用後可見的列。 */
  rows: SearchRow[]
  setQuery: (q: string) => void
  /** 點 chip：同態再點 = 取消（toggle）。 */
  toggleFilter: (f: ReviewState) => void
  toggleSort: () => void
  retry: () => void
}

function useNotebookParam(): string | undefined {
  const nav = useShellNav()
  if (nav.params.notebookId) return nav.params.notebookId
  return new URLSearchParams(window.location.search).get('notebook_id') ?? undefined
}

export function useVocabPresenterSearchApiStore(): VocabPresenterSearchApiState {
  const api = useApi()
  const notebookId = useNotebookParam()
  const [status, setStatus] = useState<VocabSearchStatus>('loading')
  const [allRows, setAllRows] = useState<SearchRow[]>([])
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ReviewState | null>(null)
  const [sort, setSort] = useState<SortOption>('reviewPriority')

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const cards = await api.vocabulary.list(notebookId ? { notebookId } : {})
      const now = new Date()
      setAllRows(
        cards.filter((c) => !c.isArchived && !c.isDeleted).map((c) => toSearchRow(c, now)),
      )
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  const counts = useMemo(() => classifyCounts(allRows), [allRows])
  const rows = useMemo(
    () => searchAndSort(allRows, query, filter, sort),
    [allRows, query, filter, sort],
  )

  return {
    status,
    query,
    filter,
    sort,
    counts,
    rows,
    setQuery,
    toggleFilter: (f) => setFilter((cur) => (cur === f ? null : f)),
    toggleSort: () => setSort((cur) => (cur === 'reviewPriority' ? 'alphabetical' : 'reviewPriority')),
    retry: load,
  }
}
