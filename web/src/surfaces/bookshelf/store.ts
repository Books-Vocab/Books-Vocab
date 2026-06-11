import { useState } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { bookshelfFixture } from './fixtures'
import type { BookFixture } from './fixtures'

/**
 * Bookshelf 互動狀態 store — 薄 in-memory 層，由 fixture seed（對齊
 * vocabulary/notebook store 範式）。parity 契約：初值 books === fixture(scenario)、
 * 無浮層（importing=false、menuTitle=null）→ capture 首屏與靜態版逐位元相同。
 *
 * 誠實邊界：web 無 SwiftData / CloudKit / 檔案系統。匯入 sheet 僅視覺 stub（檔案
 * picker 不真解析、不入庫）；改名/刪除只動 in-memory 列表，不持久化、不反向傳播
 * CloudKit（iOS BookshelfCoordinator 的 import/delete + manifest write-through 在
 * web 為 no-op）。刪光列表 → 自然落入 empty 視覺（books.length === 0）。
 */

/** 書以 title 當 in-memory id（fixture 內 title 唯一）。 */
export interface BookshelfInteractionState {
  /** 目前書列表（初值 = fixture(scenario)；改名/刪除後變動）。 */
  books: BookFixture[]
  /** 匯入 sheet 是否開啟（stub，無真解析）。 */
  importing: boolean
  /** 開啟 more 選單的書名；null = 無浮層。 */
  menuTitle: string | null
  /** 改名 sheet 鎖定的書名；null = 無 sheet。 */
  renamingTitle: string | null
  openImport: () => void
  closeImport: () => void
  openMenu: (title: string) => void
  closeMenu: () => void
  openRenameFor: (title: string) => void
  closeRename: () => void
  /** 改名指定書（以舊名定位），關 sheet。 */
  renameBook: (oldTitle: string, newTitle: string) => void
  /** 刪除指定書，關 menu。 */
  deleteBook: (title: string) => void
}

export function useBookshelfStore(scenario: ScenarioId<'bookshelf'>): BookshelfInteractionState {
  const [books, setBooks] = useState<BookFixture[]>(() => bookshelfFixture(scenario))
  const [importing, setImporting] = useState(false)
  const [menuTitle, setMenuTitle] = useState<string | null>(null)
  const [renamingTitle, setRenamingTitle] = useState<string | null>(null)

  return {
    books,
    importing,
    menuTitle,
    renamingTitle,
    openImport: () => setImporting(true),
    closeImport: () => setImporting(false),
    openMenu: (title) => setMenuTitle(title),
    closeMenu: () => setMenuTitle(null),
    openRenameFor: (title) => {
      setMenuTitle(null)
      setRenamingTitle(title)
    },
    closeRename: () => setRenamingTitle(null),
    renameBook: (oldTitle, newTitle) => {
      const trimmed = newTitle.trim()
      if (trimmed.length === 0) return
      setBooks((prev) => prev.map((b) => (b.title === oldTitle ? { ...b, title: trimmed } : b)))
      setRenamingTitle(null)
    },
    deleteBook: (title) => {
      setBooks((prev) => prev.filter((b) => b.title !== title))
      setMenuTitle(null)
    },
  }
}
