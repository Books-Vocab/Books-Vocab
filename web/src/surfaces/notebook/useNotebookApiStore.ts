import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { NotebookResponse } from '../../api/types'
import type { NotebookFixtureCard } from './fixtures'
import type { NotebookSheet } from './store'

/**
 * API-backed notebook store — 當 shell=1 時取代 fixture-driven useNotebookStore。
 * 從後端 GET /api/notebooks 拉取真實列表，add/rename/delete 做樂觀更新 + rollback。
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
  const api = useApi()
  const [status, setStatus] = useState<NotebookApiStatus>('loading')
  const [raw, setRaw] = useState<NotebookResponse[]>([])
  const [sheet, setSheet] = useState<NotebookSheet | null>(null)
  const [menuCardName, setMenuCardName] = useState<string | null>(null)
  // 以第一個 notebook 當 active（簡化；後續可由 user config 或 URL 指定）
  const activeId = useMemo(() => raw[0]?.id ?? null, [raw])

  const cards = useMemo(() => raw.map((n) => toFixtureCard(n, activeId)), [raw, activeId])

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const list = await api.notebook.list()
      setRaw(list)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  const addNotebook = useCallback(
    async (name: string) => {
      const trimmed = name.trim()
      if (trimmed.length === 0) return
      const optimistic: NotebookResponse = {
        id: `optimistic-${Date.now()}`,
        name: trimmed,
        color: '#AFC2D3',
        coverPattern: null,
        sortOrder: 999,
        isDefault: false,
        isDeleted: false,
        cardCount: 0,
        updatedAt: null,
      }
      setRaw((prev) => [...prev, optimistic])
      setSheet(null)
      try {
        const created = await api.notebook.create({ name: trimmed })
        setRaw((prev) => prev.map((n) => (n.id === optimistic.id ? created : n)))
      } catch {
        // rollback：移除樂觀插入
        setRaw((prev) => prev.filter((n) => n.id !== optimistic.id))
      }
    },
    [api],
  )

  const renameNotebook = useCallback(
    async (oldName: string, newName: string) => {
      const trimmed = newName.trim()
      if (trimmed.length === 0) return
      const target = raw.find((n) => n.name === oldName)
      if (!target) return
      const prevName = target.name
      // optimistic
      setRaw((prev) => prev.map((n) => (n.id === target.id ? { ...n, name: trimmed } : n)))
      setSheet(null)
      try {
        await api.notebook.update(target.id, { name: trimmed })
      } catch {
        // rollback
        setRaw((prev) => prev.map((n) => (n.id === target.id ? { ...n, name: prevName } : n)))
      }
    },
    [api, raw],
  )

  const deleteNotebook = useCallback(
    async (cardName: string) => {
      const target = raw.find((n) => n.name === cardName)
      if (!target) return
      const removed = target
      // optimistic
      setRaw((prev) => prev.filter((n) => n.id !== target.id))
      setMenuCardName(null)
      try {
        await api.notebook.delete(target.id)
      } catch {
        // rollback：插回原位（sortOrder 維持）
        setRaw((prev) => {
          const next = [...prev]
          const idx = next.findIndex((n) => n.sortOrder > removed.sortOrder)
          if (idx >= 0) next.splice(idx, 0, removed)
          else next.push(removed)
          return next
        })
      }
    },
    [api, raw],
  )

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
    retry: load,
  }
}
