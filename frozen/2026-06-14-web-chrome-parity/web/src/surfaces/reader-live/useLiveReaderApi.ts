import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { useShellNav } from '../../shell/ShellNavContext'
import type { BookMetadataResponse, UserConfigResponse } from '../../api/types'
import type { TranslationPanelData } from '../reader/fixtures'
import { DEFAULT_SETTINGS, type LiveReaderSettings } from './liveSettings'
import { resolveReaderFormat, type ReaderEngine } from './readerFormat'
import {
  DEFAULT_THEME,
  type LiveTheme,
  collapseExplanation,
  configPatchFromSettings,
  errorPanel,
  loadingPanel,
  markSaved,
  normalizeWord,
  resolveBoundNotebookId,
  resolvedPanel,
  settingsFromConfig,
  withExplanation,
  withExplanationError,
} from './liveLoop'

const DEFAULT_NOTEBOOK_ID = 'default'

/**
 * Live Reader 的 API 迴圈 hook（Phase 3）— 只在 shell（AppShell 內，含 ApiProvider +
 * ShellNavProvider）被呼叫。非 shell spike（App.tsx → ReaderLiveScreen）不掛此 hook，
 * 零 API 呼叫，parity 路徑 DOM 不變。
 *
 * 職責：
 *   - 從 ShellNavContext.params.bookId 認本書，撈 metadata（書名 + 綁定單字本 + 進度）。
 *   - 取詞 → translate.quick → panel；展開 → translate.explain。
 *   - 自動存詞（resolve 後 vocab.add → bound notebook + pipeline.trigger）；trash 刪除。
 *   - 載入 / 回寫 reader 設定（user.config，折進 vocab_ui.reader）。
 *   - 暴露已存詞集合給 highlight 注入。
 */
export interface LiveReaderApi {
  /** 被點開的書 id（後端 BookMetadataResponse.id；位置同步 PUT 用）。 */
  bookId?: string
  /** 撈到的書名（覆蓋 EPUB metadata 書名）；未撈到為 undefined。 */
  bookTitle?: string
  /** 後端持久化的初始閱讀位置（epub.js locator/cfi）；無則 undefined（首章）。 */
  initialLocator?: string
  /** 持久化進度 0..1（PDF 頁碼恢復用；epub 路徑以 cfi 為主，此值僅輔助）。 */
  initialProgress?: number
  /**
   * 有效渲染引擎：nav param `format` 優先，落回 book metadata format（resolveReaderFormat）。
   * 'pdf' → pdfjs-dist，其餘 → epub.js。
   */
  engine: ReaderEngine
  /** 後端持久化的 reader 設定（首載前為 DEFAULT_SETTINGS）。 */
  settings: LiveReaderSettings
  theme: LiveTheme
  /** 翻譯面板 data（null = 無面板）。 */
  panel: TranslationPanelData | null
  /** 已存詞正規化集合（供 highlight 標記）。 */
  savedWords: Set<string>
  /** 取詞 → 翻譯 → 自動存詞（綁定單字本）。 */
  selectWord: (word: string, context: string) => void
  /** footer chevron：展開 / 折疊語境解釋（懶載 explain）。 */
  toggleExpand: () => void
  /** footer trash：刪除已加入的當前詞。 */
  deleteCurrent: () => void
  /** footer xmark / scrim：關閉面板。 */
  closePanel: () => void
  /** 更新並持久化 reader 設定。 */
  updateSettings: (next: LiveReaderSettings) => void
  updateTheme: (next: LiveTheme) => void
  /** 引擎側 LWW 位置同步：PUT /api/library/books/{id}/position。 */
  putPosition: (id: string, loc: { cfi: string | null; pct: number }) => void
}

export function useLiveReaderApi(): LiveReaderApi {
  const api = useApi()
  const nav = useShellNav()
  const bookId = nav.params.bookId
  const navFormat = nav.params.format

  const [book, setBook] = useState<BookMetadataResponse | null>(null)
  const [config, setConfig] = useState<UserConfigResponse | null>(null)
  const [panel, setPanel] = useState<TranslationPanelData | null>(null)
  const [savedWords, setSavedWords] = useState<Set<string>>(() => new Set())

  // 當前選詞的活躍上下文（展開 explain / 存詞 / 刪除都對它操作）。
  const activeRef = useRef<{ word: string; context: string } | null>(null)
  // 取詞競態守衛：只有最後一次取詞的 resolve 能改 panel（避免快點多詞錯位）。
  const reqSeqRef = useRef(0)

  const { settings, theme } = useMemo(() => settingsFromConfig(config), [config])
  // 設定可即時改（樂觀），故以 local override 疊在後端載入值之上。
  const [localSettings, setLocalSettings] = useState<LiveReaderSettings | null>(null)
  const [localTheme, setLocalTheme] = useState<LiveTheme | null>(null)
  const effectiveSettings = localSettings ?? settings ?? DEFAULT_SETTINGS
  const effectiveTheme = localTheme ?? theme ?? DEFAULT_THEME

  const boundNotebookId = resolveBoundNotebookId(book?.notebook_id, DEFAULT_NOTEBOOK_ID)
  // 引擎選擇：nav param 優先（深層導航旗標），落回 book metadata format。
  const engine = resolveReaderFormat(navFormat, book?.format)

  // 撈本書 metadata（書名 + 綁定單字本 + 進度）。撈不到不致命。
  useEffect(() => {
    if (!bookId) return
    let cancelled = false
    api.library
      .list()
      .then((books) => {
        if (cancelled) return
        // 殼層以 book.title 為實體鍵（見 AppShell），故先比對 id 再比對 title。
        setBook(books.find((b) => b.id === bookId || b.title === bookId) ?? null)
      })
      .catch(() => {
        /* 撈書失敗不阻斷閱讀 */
      })
    return () => {
      cancelled = true
    }
  }, [api, bookId])

  // 載入 reader 設定（user config）。
  useEffect(() => {
    let cancelled = false
    api.user
      .config()
      .then((c) => {
        if (!cancelled) setConfig(c)
      })
      .catch(() => {
        /* 設定載入失敗 → 沿用預設 */
      })
    return () => {
      cancelled = true
    }
  }, [api])

  // 取詞 → quick translate → 自動存詞（綁定單字本）。
  const selectWord = useCallback(
    (rawWord: string, context: string) => {
      const word = rawWord
      activeRef.current = { word, context }
      const seq = ++reqSeqRef.current
      setPanel(loadingPanel(word))
      api.translate
        .quick({ word, context })
        .then((res) => {
          if (reqSeqRef.current !== seq) return // 過期請求，丟棄
          const norm = normalizeWord(word)
          const alreadySaved = savedWords.has(norm)
          setPanel(resolvedPanel(word, res, { isSaved: alreadySaved }))
          if (alreadySaved) return
          // 自動存詞（iOS reader：取詞即加入綁定單字本）。
          api.vocabulary
            .add(
              [{ word, translation: res.t, context, root_form: res.r ?? null, source: 'reader' }],
              { notebookId: boundNotebookId },
            )
            .then(() => {
              if (reqSeqRef.current !== seq) return
              setSavedWords((prev) => new Set(prev).add(norm))
              setPanel((p) => (p && p.word === word ? markSaved(p) : p))
              // enrich/embed/judge pipeline（async，失敗不阻斷）。
              api.pipeline.trigger(boundNotebookId).catch(() => {})
            })
            .catch(() => {
              /* 存詞失敗：保留譯文面板，不標已加入（使用者可重點） */
            })
        })
        .catch(() => {
          if (reqSeqRef.current !== seq) return
          setPanel(errorPanel(word, '翻譯暫時失敗，請稍後再試。'))
        })
    },
    [api, boundNotebookId, savedWords],
  )

  // 展開 / 折疊語境解釋（懶載 explain）。
  const toggleExpand = useCallback(() => {
    const active = activeRef.current
    setPanel((p) => {
      if (!p) return p
      if (p.isExpanded) return collapseExplanation(p)
      // 展開：若已有 explanation 直接展開，否則拉 explain。
      if (p.explanation) return { ...p, isExpanded: true }
      if (active) {
        api.translate
          .explain({ word: active.word, context: active.context })
          .then((res) => setPanel((cur) => (cur && cur.word === active.word ? withExplanation(cur, res) : cur)))
          .catch(() =>
            setPanel((cur) =>
              cur && cur.word === active.word
                ? withExplanationError(cur, '語境解釋暫時無法載入。')
                : cur,
            ),
          )
      }
      // 立即進入展開（顯示解釋段 loading-less placeholder；resolve 後填入）。
      return { ...p, isExpanded: true }
    })
  }, [api])

  // 刪除當前已加入詞。
  const deleteCurrent = useCallback(() => {
    const active = activeRef.current
    if (!active) {
      setPanel(null)
      return
    }
    const word = active.word
    const norm = normalizeWord(word)
    api.vocabulary.delete(word, { notebookId: boundNotebookId }).catch(() => {})
    setSavedWords((prev) => {
      const next = new Set(prev)
      next.delete(norm)
      return next
    })
    setPanel(null)
    activeRef.current = null
  }, [api, boundNotebookId])

  const closePanel = useCallback(() => {
    setPanel(null)
    activeRef.current = null
    reqSeqRef.current++ // 作廢任何在途請求
  }, [])

  // reader 設定持久化（樂觀更新 + PUT user config）。
  const persistSettings = useCallback(
    (nextSettings: LiveReaderSettings, nextTheme: LiveTheme) => {
      const patch = configPatchFromSettings(nextSettings, nextTheme, config?.vocab_ui)
      api.user
        .updateConfig(patch)
        .then((c) => setConfig(c))
        .catch(() => {
          /* 寫入失敗：保留樂觀本地值，下次改動再試 */
        })
    },
    [api, config],
  )

  const updateSettings = useCallback(
    (next: LiveReaderSettings) => {
      setLocalSettings(next)
      persistSettings(next, effectiveTheme)
    },
    [persistSettings, effectiveTheme],
  )

  const updateTheme = useCallback(
    (next: LiveTheme) => {
      setLocalTheme(next)
      persistSettings(effectiveSettings, next)
    },
    [persistSettings, effectiveSettings],
  )

  // 引擎側 LWW 位置同步（PUT position）。失敗不阻斷；下次 relocate 再試。
  const putPosition = useCallback(
    (id: string, loc: { cfi: string | null; pct: number }) => {
      api.library
        .putPosition(id, {
          locator: loc.cfi,
          progression: loc.pct,
          updated_at: new Date().toISOString(),
        })
        .catch(() => {})
    },
    [api],
  )

  return {
    bookId: book?.id ?? undefined,
    bookTitle: book?.title ?? undefined,
    initialLocator: book?.locator ?? undefined,
    initialProgress: book?.progression ?? undefined,
    engine,
    settings: effectiveSettings,
    theme: effectiveTheme,
    panel,
    savedWords,
    selectWord,
    toggleExpand,
    deleteCurrent,
    closePanel,
    updateSettings,
    updateTheme,
    putPosition,
  }
}
