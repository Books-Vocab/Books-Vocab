import { useMemo, useState } from 'react'
import type { RowReviewState, VocabFixture, VocabRowFixture } from './fixtures'

/**
 * Vocabulary 互動狀態 store — 薄 in-memory 層，由 fixture seed。parity 靜態渲染與
 * 互動共存的契約：初始狀態（query=''、activeFilter=null、expandedWord=null）下，
 * `visibleRows` === fixture.rows、無展開列 → DOM 與靜態 PNG 逐像素一致。互動只在
 * 使用者操作（輸入 / 點 chip / 點 row）後改變 derived 結果。
 *
 * 過度設計避免：不引入 reducer / context，單一 useState bag + useMemo derive 足矣。
 */

/** 三態 chip 過濾鍵；null = 未選（顯示全部 row，對齊靜態 unselected 態）。 */
export type VocabFilter = RowReviewState | null

export interface VocabInteractionState {
  /** 搜尋輸入字串。 */
  query: string
  /** 目前選中的 segment chip（null = 未選）。 */
  activeFilter: VocabFilter
  /** 展開中的 row（以 word 當 id；null = 全收合）。 */
  expandedWord: string | null
  /** 過濾後可見的 row（query + activeFilter 套用後）。 */
  visibleRows: VocabRowFixture[]
  /** 是否處於「有篩選條件但 0 命中」的空狀態（驅動 no-match empty card）。 */
  isNoMatch: boolean
  setQuery: (q: string) => void
  /** 點 chip：同態再點 = 取消選取（toggle）。 */
  toggleFilter: (f: RowReviewState) => void
  /** 點 row：同列再點 = 收合（toggle）。 */
  toggleExpanded: (word: string) => void
}

/** 純函式：套 query（不分大小寫，比對 word/translation）+ filter。匯出供測試。 */
export function filterRows(
  rows: VocabRowFixture[],
  query: string,
  activeFilter: VocabFilter,
): VocabRowFixture[] {
  const q = query.trim().toLowerCase()
  return rows.filter((r) => {
    if (activeFilter !== null && r.reviewState !== activeFilter) return false
    if (q.length === 0) return true
    return r.word.toLowerCase().includes(q) || r.translation.toLowerCase().includes(q)
  })
}

export function useVocabStore(fixture: VocabFixture): VocabInteractionState {
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState<VocabFilter>(null)
  const [expandedWord, setExpandedWord] = useState<string | null>(null)

  const visibleRows = useMemo(
    () => filterRows(fixture.rows, query, activeFilter),
    [fixture.rows, query, activeFilter],
  )

  // no-match 僅在「本來有 row、但篩選後歸零」時成立（zero-data empty 由 fixture.empty 處理）。
  const hasFilterCriteria = query.trim().length > 0 || activeFilter !== null
  const isNoMatch = fixture.rows.length > 0 && visibleRows.length === 0 && hasFilterCriteria

  return {
    query,
    activeFilter,
    expandedWord,
    visibleRows,
    isNoMatch,
    setQuery,
    toggleFilter: (f) => setActiveFilter((cur) => (cur === f ? null : f)),
    toggleExpanded: (word) => setExpandedWord((cur) => (cur === word ? null : word)),
  }
}
