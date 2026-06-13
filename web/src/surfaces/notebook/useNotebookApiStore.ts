import { useState } from 'react'
import {
  useCreateNotebookMutation,
  useDeleteNotebookMutation,
  useNotebooksQuery,
  useUpdateNotebookMutation,
} from '../../data/notebook'
import type { NotebookResponse } from '../../api/types'
import type { NotebookFixtureCard } from './fixtures'
import type { NotebookSheet } from './store'

/**
 * API-backed notebook store — 當 shell=1 時取代 fixture-driven useNotebookStore。
 * 資料層遷移到 TanStack Query（useNotebooksQuery + 三個樂觀 mutation，見 data/notebook.ts）：
 * 本 store 只保留 sheet / menu 等純 UI 互動 state，列表與寫入/樂觀/rollback 全下沉到
 * query cache。非 ready 態（loading / error）由 VocabSceneShell 在外層包裹。
 */

export type NotebookApiStatus = 'loading' | 'ready' | 'error'

export interface NotebookApiState {
  status: NotebookApiStatus
  cards: NotebookFixtureCard[]
  sheet: NotebookSheet | null
  menuCardName: string | null
  showFilter: boolean
  openAdd: () => void
  openEditFor: (cardName: string) => void
  closeSheet: () => void
  openMenu: (cardName: string) => void
  closeMenu: () => void
  addNotebook: (name: string) => Promise<void>
  renameNotebook: (oldName: string, newName: string) => Promise<void>
  deleteNotebook: (cardName: string) => Promise<void>
  retry: () => void
}

/** 把 API NotebookResponse 轉成 presentation 用的 NotebookFixtureCard。 */
export function toFixtureCard(n: NotebookResponse, activeId: string | null): NotebookFixtureCard {
  return {
    id: n.id,
    name: n.name,
    color: n.color ?? '#AFC2D3',
    cardCount: n.cardCount,
    // 簡化：actionable = cardCount（未區分 due/unlearned，web 先走近似值）
    actionableCount: n.cardCount,
    reviewProgress: 0,
    isActive: n.id === activeId,
  }
}

export function useNotebookApiStore(): NotebookApiState {
  const listQuery = useNotebooksQuery()
  const createMutation = useCreateNotebookMutation()
  const updateMutation = useUpdateNotebookMutation()
  const deleteMutation = useDeleteNotebookMutation()

  const [sheet, setSheet] = useState<NotebookSheet | null>(null)
  const [menuCardName, setMenuCardName] = useState<string | null>(null)

  const raw = listQuery.data ?? []
  // 以第一個 notebook 當 active（簡化；後續可由 user config 或 URL 指定）
  const activeId = raw[0]?.id ?? null
  const cards = raw.map((n) => toFixtureCard(n, activeId))

  let status: NotebookApiStatus
  if (listQuery.data !== undefined) status = 'ready'
  else if (listQuery.isError && !listQuery.isFetching) status = 'error'
  else status = 'loading'

  const addNotebook = async (name: string) => {
    const trimmed = name.trim()
    if (trimmed.length === 0) return
    setSheet(null)
    try {
      await createMutation.mutateAsync({ name: trimmed })
    } catch {
      // 樂觀 rollback 已由 mutation onError 處理；此處吞錯避免 unhandled rejection。
    }
  }

  const renameNotebook = async (oldName: string, newName: string) => {
    const trimmed = newName.trim()
    if (trimmed.length === 0) return
    const target = raw.find((n) => n.name === oldName)
    if (!target) return
    setSheet(null)
    try {
      await updateMutation.mutateAsync({ id: target.id, req: { name: trimmed } })
    } catch {
      // rollback by mutation onError
    }
  }

  const deleteNotebook = async (cardName: string) => {
    const target = raw.find((n) => n.name === cardName)
    if (!target) return
    setMenuCardName(null)
    try {
      await deleteMutation.mutateAsync(target.id)
    } catch {
      // rollback by mutation onError
    }
  }

  return {
    status,
    cards,
    sheet,
    menuCardName,
    showFilter: cards.length >= 2,
    openAdd: () => setSheet({ kind: 'add' }),
    openEditFor: (cardName: string) => {
      setMenuCardName(null)
      setSheet({ kind: 'edit', cardName })
    },
    closeSheet: () => setSheet(null),
    openMenu: (cardName: string) => setMenuCardName(cardName),
    closeMenu: () => setMenuCardName(null),
    addNotebook,
    renameNotebook,
    deleteNotebook,
    retry: () => {
      void listQuery.refetch()
    },
  }
}
