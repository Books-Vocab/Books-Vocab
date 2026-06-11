import { useState } from 'react'
import type { NotebookFixture, NotebookFixtureCard } from './fixtures'

/**
 * Notebook 互動狀態 store — 薄 in-memory 層，由 fixture seed（對齊 vocabulary/store.ts
 * 範式）。parity 契約：初值 cards === fixture.cards、無浮層（sheet=null、menu=null），
 * 故 capture 首屏 DOM 與靜態 PNG 逐位元相同；互動只在使用者操作後改變 derived 結果。
 *
 * 誠實邊界：web 端無 SwiftData / CloudKit，新增/改名/刪除只動 in-memory 列表，
 * 不持久化、不同步後端（iOS NotebookListCoordinator 的 server PUT/getUserConfig
 * 在 web 為 no-op）。filter pill 顯示與否仍由 notebookCount >= 2 即時推導。
 */

/** 浮層狀態：新增 sheet / 編輯某卡 sheet。null = 無 sheet。 */
export type NotebookSheet =
  | { kind: 'add' }
  | { kind: 'edit'; cardName: string }

export interface NotebookInteractionState {
  /** 目前列表（初值 = fixture.cards；新增/改名/刪除後變動）。 */
  cards: NotebookFixtureCard[]
  /** 開啟中的 sheet（新增 / 編輯）；null = 無。 */
  sheet: NotebookSheet | null
  /** 開啟 more 選單的卡名；null = 無浮層。 */
  menuCardName: string | null
  /** notebookCount >= 2 時顯示篩選 pill（即時推導，對齊 iOS gate）。 */
  showFilter: boolean
  openAdd: () => void
  openEditFor: (cardName: string) => void
  closeSheet: () => void
  openMenu: (cardName: string) => void
  closeMenu: () => void
  /** 新增 notebook：以名稱建一張空卡，append 至列表並關 sheet。 */
  addNotebook: (name: string) => void
  /** 改名指定卡（以舊名定位），關 sheet。 */
  renameNotebook: (oldName: string, newName: string) => void
  /** 刪除指定卡，關 menu。 */
  deleteNotebook: (cardName: string) => void
}

/** NotebookPalette.defaultHex（海洋）— 新建 notebook 沿用 default 封面色。 */
const DEFAULT_COVER = '#AFC2D3'

/** 純函式：新建空卡（freshly-added、無詞、非 active），匯出供測試。 */
export function makeNotebookCard(name: string): NotebookFixtureCard {
  return { name, color: DEFAULT_COVER, cardCount: 0, actionableCount: 0, reviewProgress: 0, isActive: false }
}

export function useNotebookStore(fixture: NotebookFixture): NotebookInteractionState {
  const [cards, setCards] = useState<NotebookFixtureCard[]>(fixture.cards)
  const [sheet, setSheet] = useState<NotebookSheet | null>(null)
  const [menuCardName, setMenuCardName] = useState<string | null>(null)

  return {
    cards,
    sheet,
    menuCardName,
    showFilter: cards.length >= 2,
    openAdd: () => setSheet({ kind: 'add' }),
    openEditFor: (cardName) => {
      setMenuCardName(null)
      setSheet({ kind: 'edit', cardName })
    },
    closeSheet: () => setSheet(null),
    openMenu: (cardName) => setMenuCardName(cardName),
    closeMenu: () => setMenuCardName(null),
    addNotebook: (name) => {
      const trimmed = name.trim()
      if (trimmed.length === 0) return
      setCards((prev) => [...prev, makeNotebookCard(trimmed)])
      setSheet(null)
    },
    renameNotebook: (oldName, newName) => {
      const trimmed = newName.trim()
      if (trimmed.length === 0) return
      setCards((prev) => prev.map((c) => (c.name === oldName ? { ...c, name: trimmed } : c)))
      setSheet(null)
    },
    deleteNotebook: (cardName) => {
      setCards((prev) => prev.filter((c) => c.name !== cardName))
      setMenuCardName(null)
    },
  }
}
