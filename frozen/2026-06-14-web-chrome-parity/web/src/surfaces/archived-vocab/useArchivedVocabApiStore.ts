import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { CardResponse } from '../../api/types'
import type { ArchivedVocabRow } from './fixtures'

/**
 * Archived Vocab 的 API store — shell=1 時取代 fixture。從 GET /api/vocab 拉全部
 * 卡片、過出 isArchived 列（字母序，鏡射 iOS @Query sort:\.word），提供：
 *   - 單列還原（PATCH /api/vocab/{word}/archive {archived:false}）
 *   - 單列刪除（DELETE /api/vocab/{word}）
 *   - 多選批次還原 / 刪除（PATCH batch-archive / POST batch-delete）
 *
 * 誠實邊界：notebookId 來源 = ShellNavContext.params.notebookId 優先、?notebook_id=
 * search fallback。parity 路徑（無 shell）不呼叫此 hook，DOM 與 capture 完全不變。
 */

export type ArchivedVocabStatus = 'loading' | 'ready' | 'error'

/** 純函式：過出 archived 卡 → 字母序 ArchivedVocabRow 陣列。匯出供測試。 */
export function toArchivedRows(cards: CardResponse[]): ArchivedVocabRow[] {
  return cards
    .filter((c) => c.isArchived && !c.isDeleted)
    .map((c) => ({
      id: c.content,
      word: c.content,
      partOfSpeech: c.pos ? `${c.pos}.` : null,
      translation: c.meaning,
    }))
    .sort((a, b) => (a.word < b.word ? -1 : a.word > b.word ? 1 : 0))
}

/** 純函式：toggle 多選集合（同 word 再點 = 取消）。匯出供測試。 */
export function toggleSelection(selected: ReadonlySet<string>, word: string): Set<string> {
  const next = new Set(selected)
  if (next.has(word)) next.delete(word)
  else next.add(word)
  return next
}

export interface ArchivedVocabApiState {
  status: ArchivedVocabStatus
  rows: ArchivedVocabRow[]
  /** 多選集合（word）。空 = 非選取模式。 */
  selected: Set<string>
  toggleSelect: (word: string) => void
  clearSelection: () => void
  /** 單列還原（archived=false）。 */
  restore: (word: string) => void
  /** 單列刪除。 */
  remove: (word: string) => void
  /** 批次還原已選列。 */
  restoreSelected: () => void
  /** 批次刪除已選列。 */
  deleteSelected: () => void
  retry: () => void
}

function useNotebookParam(): string | undefined {
  const nav = useShellNav()
  if (nav.params.notebookId) return nav.params.notebookId
  return new URLSearchParams(window.location.search).get('notebook_id') ?? undefined
}

export function useArchivedVocabApiStore(): ArchivedVocabApiState {
  const api = useApi()
  const notebookId = useNotebookParam()
  const [status, setStatus] = useState<ArchivedVocabStatus>('loading')
  const [cards, setCards] = useState<CardResponse[]>([])
  const [selected, setSelected] = useState<Set<string>>(() => new Set())

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

  const rows = useMemo(() => toArchivedRows(cards), [cards])
  const opts = notebookId ? { notebookId } : {}

  // 樂觀地把一組 word 自當前列表移除（還原 / 刪除後都離開 archived 列表）。
  const dropLocally = useCallback((words: string[]) => {
    const drop = new Set(words)
    setCards((cur) =>
      cur.map((c) => (drop.has(c.content) ? { ...c, isArchived: false, isDeleted: true } : c)),
    )
    setSelected((cur) => {
      const next = new Set(cur)
      for (const w of words) next.delete(w)
      return next
    })
  }, [])

  const restore = useCallback(
    (word: string) => {
      dropLocally([word])
      api.vocabulary.archive(word, false, opts).catch(() => load())
    },
    [api, dropLocally, load, opts],
  )

  const remove = useCallback(
    (word: string) => {
      dropLocally([word])
      api.vocabulary.delete(word, opts).catch(() => load())
    },
    [api, dropLocally, load, opts],
  )

  const restoreSelected = useCallback(() => {
    const words = [...selected]
    if (words.length === 0) return
    dropLocally(words)
    api.vocabulary.batchArchive(words, false, opts).catch(() => load())
  }, [api, dropLocally, load, opts, selected])

  const deleteSelected = useCallback(() => {
    const words = [...selected]
    if (words.length === 0) return
    dropLocally(words)
    api.vocabulary.batchDelete(words, opts).catch(() => load())
  }, [api, dropLocally, load, opts, selected])

  return {
    status,
    rows,
    selected,
    toggleSelect: (word) => setSelected((cur) => toggleSelection(cur, word)),
    clearSelection: () => setSelected(new Set()),
    restore,
    remove,
    restoreSelected,
    deleteSelected,
    retry: load,
  }
}
