import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { BookMetadataResponse } from '../../api/types'
import type { BookFixture, BookFormat } from './fixtures'

/**
 * API-backed bookshelf store — 當 shell=1 時取代 fixture-driven useBookshelfStore。
 * 從後端 GET /api/library/books 拉取真實書目；匯入走瀏覽器檔案 picker，僅解析
 * 最小 metadata（title=檔名、format=副檔名），POST /api/library/books **不上傳原始
 * bytes**（後端只存 metadata，raw 檔留在客戶端）。改名做樂觀更新 + rollback。
 * 非 ready 態（loading / error）由 VocabSceneShell 在外層包裹。
 *
 * 誠實邊界：web 不持有 EPUB/PDF 解析器，import 只把 metadata 推上後端做跨裝置同步；
 * 真正開書閱讀的 spike 走 ?surface=reader-live。刪除為「本地端移除」——Phase 4 後端
 * 尚無 DELETE / is_deleted PATCH 端點，故刪除不落地後端（見 deleteBook 的 debt 註解）。
 */

export type BookshelfApiStatus = 'loading' | 'ready' | 'error'

export interface BookshelfApiState {
  status: BookshelfApiStatus
  books: BookFixture[]
  importing: boolean
  menuTitle: string | null
  renamingTitle: string | null
  openImport: () => void
  closeImport: () => void
  openMenu: (title: string) => void
  closeMenu: () => void
  openRenameFor: (title: string) => void
  closeRename: () => void
  renameBook: (oldTitle: string, newTitle: string) => Promise<void>
  deleteBook: (title: string) => Promise<void>
  /** 由瀏覽器檔案 picker 觸發：解析最小 metadata 並 POST（不傳 raw bytes）。 */
  importFile: (file: File) => Promise<void>
  retry: () => void
}

const KNOWN_FORMATS: BookFormat[] = ['epub', 'pdf', 'txt', 'md']

/** 副檔名 → BookFormat（未知格式落 'epub' 作為視覺占位）。 */
export function formatFromName(name: string): BookFormat {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : ''
  return (KNOWN_FORMATS as string[]).includes(ext) ? (ext as BookFormat) : 'epub'
}

/** 去副檔名取書名（fallback 用整檔名）。 */
export function titleFromName(name: string): string {
  const base = name.includes('.') ? name.slice(0, name.lastIndexOf('.')) : name
  return base.trim() || name
}

/** 把 API BookMetadataResponse 轉成 presentation 用的 BookFixture。 */
export function toBookFixture(b: BookMetadataResponse): BookFixture {
  const fmt = (b.format ?? '').toLowerCase()
  return {
    title: b.title,
    author: b.author ?? '',
    format: (KNOWN_FORMATS as string[]).includes(fmt) ? (fmt as BookFormat) : 'epub',
    // 後端 metadata 無預固化相對日期；web API 路徑不做日期顯示（留空避免非決定性運算）。
    dateLabel: '',
    progression: b.progression ?? 0,
    needsICloudDownload: false,
  }
}

export function useBookshelfApiStore(): BookshelfApiState {
  const api = useApi()
  const [status, setStatus] = useState<BookshelfApiStatus>('loading')
  const [raw, setRaw] = useState<BookMetadataResponse[]>([])
  const [importing, setImporting] = useState(false)
  const [menuTitle, setMenuTitle] = useState<string | null>(null)
  const [renamingTitle, setRenamingTitle] = useState<string | null>(null)

  const books = useMemo(
    () => raw.filter((b) => !b.is_deleted).map(toBookFixture),
    [raw],
  )

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const list = await api.library.list()
      setRaw(list)
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  const importFile = useCallback(
    async (file: File) => {
      const title = titleFromName(file.name)
      const format = formatFromName(file.name)
      // client_book_id 用檔名 + size 推導穩定 id（後端以此做冪等去重）。
      const clientBookId = `web-${format}-${file.size}-${title.toLowerCase().replace(/\s+/g, '-')}`
      const nowIso = new Date().toISOString()
      const optimistic: BookMetadataResponse = {
        id: `optimistic-${Date.now()}`,
        client_book_id: clientBookId,
        title,
        author: null,
        language: null,
        format,
        notebook_id: null,
        is_deleted: false,
        updated_at: nowIso,
        locator: null,
        progression: 0,
        position_updated_at: null,
      }
      setRaw((prev) => [optimistic, ...prev])
      setImporting(false)
      try {
        // NOTE: metadata only — raw bytes 永不上傳（後端 schema 無 file 欄位）。
        const created = await api.library.create({
          client_book_id: clientBookId,
          title,
          format,
        })
        setRaw((prev) => prev.map((b) => (b.id === optimistic.id ? created : b)))
      } catch {
        setRaw((prev) => prev.filter((b) => b.id !== optimistic.id))
      }
    },
    [api],
  )

  const renameBook = useCallback(
    async (oldTitle: string, newTitle: string) => {
      const trimmed = newTitle.trim()
      if (trimmed.length === 0) return
      const target = raw.find((b) => b.title === oldTitle && !b.is_deleted)
      if (!target) return
      const prevTitle = target.title
      setRaw((prev) => prev.map((b) => (b.id === target.id ? { ...b, title: trimmed } : b)))
      setRenamingTitle(null)
      try {
        await api.library.update(target.id, { title: trimmed })
      } catch {
        setRaw((prev) => prev.map((b) => (b.id === target.id ? { ...b, title: prevTitle } : b)))
      }
    },
    [api, raw],
  )

  const deleteBook = useCallback(
    async (title: string) => {
      const target = raw.find((b) => b.title === title && !b.is_deleted)
      if (!target) return
      // INTEGRATION DEBT (Phase 4): backend exposes no DELETE / is_deleted PATCH,
      // so deletion is local-only here (matches the fixture store's removal). When
      // the backend adds soft-delete, wire the server call + rollback like rename.
      setMenuTitle(null)
      setRaw((prev) => prev.filter((b) => b.id !== target.id))
    },
    [raw],
  )

  return {
    status,
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
    renameBook,
    deleteBook,
    importFile,
    retry: load,
  }
}
