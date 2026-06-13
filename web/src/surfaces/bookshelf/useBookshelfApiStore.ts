import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { BookMetadataResponse } from '../../api/types'
import type { BookFixture, BookFormat } from './fixtures'

/**
 * API-backed bookshelf store — 當 shell=1 時取代 fixture-driven useBookshelfStore。
 * 從後端 GET /api/library/books 拉取真實書目；匯入走瀏覽器檔案 picker：對 .epub
 * 用 epubjs 真解析 OPF metadata（title/author/language），其餘格式落檔名 stem，
 * POST /api/library/books **不上傳原始 bytes**（後端只存 metadata，raw 檔留在客戶端）。
 * 改名 / 綁定單字本做樂觀更新 + rollback；刪除走後端 soft-delete（DELETE）後本地移除。
 * 非 ready 態（loading / error）由 VocabSceneShell 在外層包裹。
 *
 * 誠實邊界：web 端只在匯入瞬間用 epubjs 讀 metadata（不持久化 raw bytes），真正開書
 * 閱讀的 spike 走 ?surface=reader-live。**點書開 reader 由 AppShell 的滿版書格熱區
 * （`.shell-hot-bookgrid`，frozen）統一承接**（open-book → reader，帶 bookId），故本
 * store 不持有 per-book open 導航。
 */

export type BookshelfApiStatus = 'loading' | 'ready' | 'error'

/** 單字本綁定選項（picker 用最小欄位，取自 NotebookResponse）。 */
export interface NotebookOption {
  id: string
  name: string
}

export interface BookshelfApiState {
  status: BookshelfApiStatus
  books: BookFixture[]
  importing: boolean
  menuTitle: string | null
  renamingTitle: string | null
  /** 開啟綁定 picker 的書名；null = 無 picker。 */
  bindingTitle: string | null
  /** 可綁定的單字本清單（picker 用）。 */
  notebooks: NotebookOption[]
  /** 指定書名目前綁定的 notebook_id（picker 反白用），未綁 = null。 */
  boundNotebookId: (title: string) => string | null
  openImport: () => void
  closeImport: () => void
  openMenu: (title: string) => void
  closeMenu: () => void
  openRenameFor: (title: string) => void
  closeRename: () => void
  openBindFor: (title: string) => void
  closeBind: () => void
  renameBook: (oldTitle: string, newTitle: string) => Promise<void>
  deleteBook: (title: string) => Promise<void>
  /** 綁定 / 解綁（notebookId=null）指定書到單字本，PATCH notebook_id。 */
  bindNotebook: (title: string, notebookId: string | null) => Promise<void>
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

/** 匯入時推導出的最小 metadata（POST body 之前的純資料）。 */
export interface ParsedBookMetadata {
  title: string
  author: string | null
  language: string | null
  format: BookFormat
}

/**
 * 把 epubjs 解析出的 OPF metadata（部分欄位）+ 檔名合併成可入庫的最小 metadata。
 * 純函式：OPF title 空白 → 落檔名 stem；creator/language 空白 → null。format 恆 epub
 * （僅 .epub 走此路）。抽出以便不依賴瀏覽器/epubjs 即可單測。
 */
export function metadataFromEpub(
  meta: Partial<{ title: string; creator: string; language: string }>,
  filename: string,
): ParsedBookMetadata {
  const opfTitle = (meta.title ?? '').trim()
  const author = (meta.creator ?? '').trim()
  const language = (meta.language ?? '').trim()
  return {
    title: opfTitle || titleFromName(filename),
    author: author || null,
    language: language || null,
    format: 'epub',
  }
}

/** 非 .epub 檔的最小 metadata（僅檔名 + 副檔名格式，無內容解析）。 */
export function metadataFromFilename(file: File): ParsedBookMetadata {
  return {
    title: titleFromName(file.name),
    author: null,
    language: null,
    format: formatFromName(file.name),
  }
}

/**
 * 用 epubjs 從 .epub 檔讀 OPF metadata（瀏覽器端，僅讀 metadata 不渲染）。解析失敗
 * （損毀 / 非真 EPUB）→ 落檔名 stem。讀完即 destroy 釋放資源。
 */
/** epubjs Book 的最小子集（僅 metadata 讀取 + teardown，不渲染）。 */
interface EpubMetadataBook {
  loaded: { metadata: Promise<unknown> }
  destroy: () => void
}

export async function parseEpubMetadata(file: File): Promise<ParsedBookMetadata> {
  let book: EpubMetadataBook | null = null
  try {
    const ePub = (await import('epubjs')).default as unknown as (
      input: ArrayBuffer,
    ) => EpubMetadataBook
    const buffer = await file.arrayBuffer()
    book = ePub(buffer)
    const meta = (await book.loaded.metadata) as Partial<{
      title: string
      creator: string
      language: string
    }>
    return metadataFromEpub(meta ?? {}, file.name)
  } catch {
    return metadataFromFilename(file)
  } finally {
    try {
      book?.destroy()
    } catch {
      /* epubjs teardown best-effort */
    }
  }
}

/** 依檔案推導入庫 metadata：.epub 走 epubjs 真解析，其餘走檔名。 */
export async function metadataForFile(file: File): Promise<ParsedBookMetadata> {
  return formatFromName(file.name) === 'epub'
    ? parseEpubMetadata(file)
    : metadataFromFilename(file)
}

/** 以書名在 raw 清單定位「未刪除」書（title 由 fixture/iOS 端保證唯一）。 */
export function findBookByTitle(
  raw: BookMetadataResponse[],
  title: string,
): BookMetadataResponse | undefined {
  return raw.find((b) => b.title === title && !b.is_deleted)
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
  const [notebooks, setNotebooks] = useState<NotebookOption[]>([])
  const [importing, setImporting] = useState(false)
  const [menuTitle, setMenuTitle] = useState<string | null>(null)
  const [renamingTitle, setRenamingTitle] = useState<string | null>(null)
  const [bindingTitle, setBindingTitle] = useState<string | null>(null)

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
      // 單字本清單供綁定 picker；失敗不擋書架載入（綁定僅是次要功能）。
      try {
        const nbs = await api.notebook.list()
        setNotebooks(
          nbs
            .filter((n) => !n.isDeleted)
            .map((n) => ({ id: n.id, name: n.name })),
        )
      } catch {
        setNotebooks([])
      }
    } catch {
      setStatus('error')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  const importFile = useCallback(
    async (file: File) => {
      // .epub → epubjs 真解析 OPF metadata；其餘格式落檔名 stem。
      const meta = await metadataForFile(file)
      const { title, author, language, format } = meta
      // client_book_id 用格式 + size + 書名推導穩定 id（後端以此做冪等去重）。
      const clientBookId = `web-${format}-${file.size}-${title.toLowerCase().replace(/\s+/g, '-')}`
      const nowIso = new Date().toISOString()
      const optimistic: BookMetadataResponse = {
        id: `optimistic-${Date.now()}`,
        client_book_id: clientBookId,
        title,
        author,
        language,
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
          author,
          language,
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
      const target = findBookByTitle(raw, oldTitle)
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
      const target = findBookByTitle(raw, title)
      if (!target) return
      // 後端 soft-delete（DELETE /api/library/books/{id}）後本地移除；失敗 → rollback。
      const snapshot = raw
      setMenuTitle(null)
      // 樂觀移除；DELETE /api/library/books/{id} 失敗則回復該書。
      setRaw((prev) => prev.filter((b) => b.id !== target.id))
      try {
        await api.library.delete(target.id)
      } catch {
        setRaw(snapshot)
      }
    },
    [api, raw],
  )

  const bindNotebook = useCallback(
    async (title: string, notebookId: string | null) => {
      const target = findBookByTitle(raw, title)
      if (!target) return
      const prevNotebookId = target.notebook_id
      setRaw((prev) =>
        prev.map((b) => (b.id === target.id ? { ...b, notebook_id: notebookId } : b)),
      )
      setBindingTitle(null)
      try {
        // PATCH notebook_id（null = 解綁）。
        await api.library.update(target.id, { notebook_id: notebookId })
      } catch {
        setRaw((prev) =>
          prev.map((b) => (b.id === target.id ? { ...b, notebook_id: prevNotebookId } : b)),
        )
      }
    },
    [api, raw],
  )

  const boundNotebookId = useCallback(
    (title: string) => findBookByTitle(raw, title)?.notebook_id ?? null,
    [raw],
  )

  return {
    status,
    books,
    importing,
    menuTitle,
    renamingTitle,
    bindingTitle,
    notebooks,
    boundNotebookId,
    openImport: () => setImporting(true),
    closeImport: () => setImporting(false),
    openMenu: (title) => setMenuTitle(title),
    closeMenu: () => setMenuTitle(null),
    openRenameFor: (title) => {
      setMenuTitle(null)
      setRenamingTitle(title)
    },
    closeRename: () => setRenamingTitle(null),
    openBindFor: (title) => {
      setMenuTitle(null)
      setBindingTitle(title)
    },
    closeBind: () => setBindingTitle(null),
    renameBook,
    deleteBook,
    bindNotebook,
    importFile,
    retry: load,
  }
}
