import { useMemo, useState } from 'react'
import type { NotebookResponse } from '../../api/types'
import {
  useCreateNotebookMutation,
  useDeleteNotebookMutation,
  useNotebooksQuery,
  useUpdateNotebookMutation,
} from '../../data'
import type { NotebookFixtureCard } from './fixtures'
import type { NotebookSheet } from './store'

/**
 * API-backed notebook store — 當 shell=1 時取代 fixture-driven useNotebookStore。
 * 資料引擎已遷移到 P2 資料層（data/notebook.ts）：useNotebooksQuery 讀列表，
 * add/rename/delete 走樂觀 mutation hooks（onMutate setQueryData / onError rollback /
 * onSettled invalidate，邏輯在 hook 內，跨 surface cache 一致）。本 store 只保留
 * UI 狀態（sheet / menu）與 name→id 解析，並把公開介面 NotebookApiState 維持不變。
 * 非 ready 態（loading / error）由 VocabSceneShell 在外層包裹。
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
  const createMut = useCreateNotebookMutation()
  const updateMut = useUpdateNotebookMutation()
  const deleteMut = useDeleteNotebookMutation()
  const [sheet, setSheet] = useState<NotebookSheet | null>(null)
  const [menuCardName, setMenuCardName] = useState<string | null>(null)

  const raw = useMemo<NotebookResponse[]>(() => listQuery.data ?? [], [listQuery.data])
  // 以第一個 notebook 當 active（簡化；後續可由 user config 或 URL 指定）
  const activeId = raw[0]?.id ?? null
  const cards = useMemo(() => raw.map((n) => toFixtureCard(n, activeId)), [raw, activeId])

  // status 映射（同 vocab 遷移）：有資料→ready（背景 refetch 不退 loading）、
  // settle 的 error→error、初次/retry-refetch→loading。
  let status: NotebookApiStatus
  if (listQuery.data !== undefined) status = 'ready'
  else if (listQuery.isError && !listQuery.isFetching) status = 'error'
  else status = 'loading'

  // 寫入：name→id 解析留在 surface（介面是 name-based），實際樂觀更新 + rollback +
  // invalidate 由 mutation hook 內部處理；此處只關 UI 狀態。mutateAsync 失敗會 reject，
  // catch 吞掉（rollback 已在 hook 的 onError 完成，呼叫端無需再處理）。
  const addNotebook = async (name: string) => {
    const trimmed = name.trim()
    if (trimmed.length === 0) return
    setSheet(null)
    try {
      await createMut.mutateAsync({ name: trimmed })
    } catch {
      /* rollback 已由 hook onError 處理 */
    }
  }

  const renameNotebook = async (oldName: string, newName: string) => {
    const trimmed = newName.trim()
    if (trimmed.length === 0) return
    const target = raw.find((n) => n.name === oldName)
    if (!target) return
    setSheet(null)
    try {
      await updateMut.mutateAsync({ id: target.id, req: { name: trimmed } })
    } catch {
      /* rollback 已由 hook onError 處理 */
    }
  }

  const deleteNotebook = async (cardName: string) => {
    const target = raw.find((n) => n.name === cardName)
    if (!target) return
    setMenuCardName(null)
    try {
      await deleteMut.mutateAsync(target.id)
    } catch {
      /* rollback 已由 hook onError 處理 */
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
