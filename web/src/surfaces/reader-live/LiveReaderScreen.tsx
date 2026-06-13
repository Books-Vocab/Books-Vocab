import { useCallback, useEffect, useRef, useState } from 'react'
import { TranslationPanel } from '../reader/TranslationPanel'
import {
  BookClosedIcon,
  ChevronLeftIcon,
  ListBulletIcon,
  TextformatSizeIcon,
} from '../reader/icons'
import '../reader/reader.css'
import './live-reader.css'
import { useLiveReaderApi } from './useLiveReaderApi'
import { highlightCss, highlightWordSet, type LiveTheme } from './liveLoop'
import {
  DEFAULT_SETTINGS,
  bodyCss,
  canDecrease,
  canIncrease,
  decreaseFontSize,
  fontSizeText,
  increaseFontSize,
  FONT_LABEL,
  type LiveFont,
  type LiveReaderSettings,
} from './liveSettings'

/**
 * Live Reader — web Reader 生產化（Phase 1 chrome → Phase 3 真迴圈）。
 *
 * epub.js 真渲染引擎嵌進像素級 parity reader chrome：expanded header（書庫 +
 * 居中書名 + TOC/設定鈕）、compact 進度膠囊、bottom-overlay 翻譯面板掛點，全部沿
 * 用 `reader.css` 的既有視覺語彙。
 *
 *   選詞 → 真實 `/api/translate/quick`（→ parity `TranslationPanel`），自動加入本書
 *          綁定單字本（`/api/vocab`，source:'reader'）+ 觸發 pipeline；展開語境走
 *          `/api/translate/explain`；trash 刪除。
 *   highlight → 已加入詞於內文以 <mark> 標記（iOS `__markVocabWord` 的 web 對應）。
 *   TOC  → epub.js navigation 章節清單 + `rendition.display(href)` 真跳轉。
 *   設定 → 字級 + serif/sans + 紙色主題；即時作用 epub.js 並 PUT user config 持久化。
 *   進度 → relocate debounce 1200ms + visibilitychange + beforeunload flush PUT position。
 *
 * 隔離：epub.js dynamic import，僅此路徑載入，不進 parity bundle；既有 parity
 * surface（?surface=reader 等）DOM 與渲染零改動。此元件只在 shell（AppShell 內，
 * 含 ApiProvider + ShellNavProvider）掛載，故 useLiveReaderApi 的 useApi 安全。
 * 非 shell 的純引擎 spike 走 App.tsx 的 ReaderLiveScreen（零 API），互不影響。
 */

const EPUB_URL = '/spike/childrens-literature.epub'
const POSITION_DEBOUNCE_MS = 1200

type TocItem = { label: string; href: string }
type Panel = 'none' | 'toc' | 'settings'

// --- iOS buildWordRangeFromPoint 的 web 移植（spike 已驗，沿用） ---
function findContextContainer(el: Element | null): Element | null {
  while (el) {
    const tag = (el.tagName || '').toUpperCase()
    if (['P', 'LI', 'BLOCKQUOTE', 'TD', 'DIV', 'SECTION', 'BODY'].indexOf(tag) >= 0) return el
    el = el.parentElement
  }
  return null
}
function extractContext(startEl: Element | null, word: string): string {
  const c = findContextContainer(startEl)
  const full = (c ? c.textContent : startEl ? startEl.textContent : word ?? '')?.trim() || ''
  if (full.length <= 300) return full
  let p = full.toLowerCase().indexOf(word.toLowerCase())
  if (p < 0) p = Math.floor(full.length / 2)
  return full.substring(Math.max(0, p - 150), Math.min(full.length, p + word.length + 150)).trim()
}
function wordFromPoint(doc: Document, x: number, y: number) {
  const range = doc.caretRangeFromPoint ? doc.caretRangeFromPoint(x, y) : null
  if (!range || range.startContainer.nodeType !== Node.TEXT_NODE) return null
  const text = range.startContainer.textContent || ''
  const off = range.startOffset
  let s = off
  let e = off
  while (s > 0 && /[a-zA-Z'-]/.test(text[s - 1])) s--
  while (e < text.length && /[a-zA-Z'-]/.test(text[e])) e++
  const word = text.slice(s, e).replace(/^['-]+|['-]+$/g, '')
  if (word.length < 2) return null
  const wr = doc.createRange()
  wr.setStart(range.startContainer, s)
  wr.setEnd(range.startContainer, e)
  return { word, rect: wr.getBoundingClientRect(), el: (range.startContainer as Text).parentElement }
}

/**
 * 在 section document 內把命中已存詞的純文字節點以 <mark class="kg-vocab-hl"> 包裹
 * （iOS `__markVocabWords` 的 web 對應）。CSS 由 themes.registerCss 注入。
 * 只處理可見文字節點，跳過 script/style/已標記節點，避免破壞既有 highlight。
 */
function markSavedWords(doc: Document, words: Set<string>): void {
  if (words.size === 0) return
  const body = doc.body
  if (!body) return
  const walker = doc.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = (node as Text).parentElement
      if (!parent) return NodeFilter.FILTER_REJECT
      const tag = parent.tagName.toUpperCase()
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'MARK' || tag === 'A') {
        return NodeFilter.FILTER_REJECT
      }
      if (parent.closest('mark.kg-vocab-hl')) return NodeFilter.FILTER_REJECT
      return /[a-zA-Z]/.test(node.textContent || '') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
    },
  })
  const targets: Text[] = []
  let n = walker.nextNode()
  while (n) {
    targets.push(n as Text)
    n = walker.nextNode()
  }
  // 命中 regex：詞邊界 + 任一已存詞（小寫比對）。
  const escaped = [...words].map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (escaped.length === 0) return
  const re = new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi')
  for (const textNode of targets) {
    const text = textNode.textContent || ''
    re.lastIndex = 0
    if (!re.test(text)) continue
    re.lastIndex = 0
    const frag = doc.createDocumentFragment()
    let last = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text)) !== null) {
      const lower = m[1].toLowerCase()
      if (!words.has(lower)) continue
      if (m.index > last) frag.appendChild(doc.createTextNode(text.slice(last, m.index)))
      const mark = doc.createElement('mark')
      mark.className = 'kg-vocab-hl'
      mark.textContent = m[1]
      frag.appendChild(mark)
      last = m.index + m[1].length
    }
    if (last === 0) continue // 無實際命中（regex 命中但非 saved set）
    if (last < text.length) frag.appendChild(doc.createTextNode(text.slice(last)))
    textNode.parentNode?.replaceChild(frag, textNode)
  }
}

export function LiveReaderScreen({ onBack }: { onBack?: () => void } = {}) {
  const live = useLiveReaderApi()
  const hostRef = useRef<HTMLDivElement | null>(null)
  const renditionRef = useRef<any>(null)
  const bookRef = useRef<any>(null)
  const settingsRef = useRef<LiveReaderSettings>(DEFAULT_SETTINGS)
  const themeRef = useRef<LiveTheme>('paper')
  // 每個 section 渲染時讀最新已存詞集合（ref 避免重建 hook）。
  const savedWordsRef = useRef<Set<string>>(new Set())

  const [toc, setToc] = useState<TocItem[]>([])
  const [progress, setProgress] = useState(0)
  const [bookTitle, setBookTitle] = useState('')
  const [panel, setPanel] = useState<Panel>('none')
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  // ── 位置同步（debounce + visibilitychange + beforeunload flush）─────────────
  const posTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const latestPos = useRef<{ cfi: string | null; pct: number } | null>(null)
  const liveRef = useRef(live)
  liveRef.current = live

  const flushPosition = useCallback(() => {
    const loc = latestPos.current
    const id = bookRef.current?.__kgBookId as string | undefined
    if (!loc) return
    if (posTimer.current) {
      clearTimeout(posTimer.current)
      posTimer.current = null
    }
    if (!id) return
    // 直接走 transport（hook 不暴露 putPosition；位置同步是引擎側 LWW）。
    liveRef.current.putPosition?.(id, loc)
  }, [])

  // settings/theme → epub.js registerCss（即時生效）+ 同步 ref（供 boot/section 用）。
  const applyTheme = useCallback((s: LiveReaderSettings, theme: LiveTheme) => {
    settingsRef.current = s
    themeRef.current = theme
    const r = renditionRef.current
    if (!r) return
    // body CSS（字級/字體）+ highlight CSS（已存詞 mark）+ 紙色主題，同名重註冊覆寫。
    r.themes.registerCss('kg', `${bodyCss(s, location.origin)}\n${themeBodyCss(theme)}\n${highlightCss()}`)
    r.themes.select('kg')
  }, [])

  // 後端載入 / 樂觀更新的設定變動 → 重套 epub.js 主題。
  useEffect(() => {
    applyTheme(live.settings, live.theme)
  }, [applyTheme, live.settings, live.theme])

  // 已存詞集合變動 → 更新 ref；對「已渲染」section 重新標記命中詞。
  useEffect(() => {
    savedWordsRef.current = highlightWordSet(live.savedWords)
    const r = renditionRef.current
    if (!r) return
    try {
      const contents = r.getContents?.() ?? []
      for (const c of contents) {
        if (c?.document) markSavedWords(c.document, savedWordsRef.current)
      }
    } catch {
      /* teardown race */
    }
  }, [live.savedWords])

  useEffect(() => {
    let destroyed = false
    let book: any = null

    async function boot() {
      try {
        const ePub = (await import('epubjs')).default
        if (destroyed || !hostRef.current) return
        book = ePub(EPUB_URL)
        bookRef.current = book
        const rendition = book.renderTo(hostRef.current, {
          width: '100%',
          height: '100%',
          flow: 'paginated',
          spread: 'none',
        })
        renditionRef.current = rendition

        applyTheme(settingsRef.current, themeRef.current)

        // 選詞監聽 + 已存詞標記：每個 section 渲染後綁定。
        rendition.hooks.content.register((contents: any) => {
          try {
            const doc: Document = contents.document
            // 首次渲染即標記已存詞（highlight）。
            markSavedWords(doc, savedWordsRef.current)
            doc.addEventListener(
              'click',
              (e: MouseEvent) => {
                if ((e.target as Element)?.closest?.('a')) return
                const d = wordFromPoint(doc, e.clientX, e.clientY)
                if (!d) return
                const dx = Math.max(d.rect.left - e.clientX, 0, e.clientX - d.rect.right)
                const dy = Math.max(d.rect.top - e.clientY, 0, e.clientY - d.rect.bottom)
                if (Math.sqrt(dx * dx + dy * dy) > 12) return
                const word = d.word
                const ctx = extractContext(d.el, word)
                liveRef.current.selectWord(word, ctx)
              },
              true,
            )
          } catch {
            /* teardown race */
          }
        })

        rendition.on('relocated', (loc: any) => {
          let pct = 0
          if (book.locations && book.locations.length()) {
            pct = book.locations.percentageFromCfi(loc.start.cfi) || 0
            setProgress(pct)
          }
          // 位置同步：debounce 1200ms（高頻 relocate 合併，只 PUT 最後一次 LWW）。
          latestPos.current = { cfi: loc.start?.cfi ?? null, pct }
          if (posTimer.current) clearTimeout(posTimer.current)
          posTimer.current = setTimeout(flushPosition, POSITION_DEBOUNCE_MS)
        })

        await book.ready
        if (destroyed) return
        // book id 經 ref 暴露給 flushPosition（hook 撈到後寫回）。
        book.__kgBookId = liveRef.current.bookId
        setBookTitle((book.packaging?.metadata?.title as string) || 'EPUB')
        const nav = await book.loaded.navigation
        setToc((nav.toc || []).map((t: any) => ({ label: (t.label || '').trim(), href: t.href })))
        // 從後端進度恢復閱讀位置（撈到 locator 才跳，否則首章）。
        const restoreTo = liveRef.current.initialLocator
        await rendition.display(restoreTo || undefined)
        setReady(true)
        book.locations.generate(1600).catch(() => {})
      } catch (e: any) {
        if (!destroyed) setError(String(e?.message || e))
      }
    }

    boot()
    return () => {
      destroyed = true
      // unmount flush 待落地位置（避免離開頁面丟進度）。
      flushPosition()
      try {
        book?.destroy()
      } catch {
        /* noop */
      }
    }
    // boot 只跑一次；settings/saved/theme 變更走各自 effect（不重建 book）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // book id 撈到後寫回 ref（boot 時可能尚未 settle）。
  useEffect(() => {
    if (bookRef.current && live.bookId) bookRef.current.__kgBookId = live.bookId
  }, [live.bookId])

  // 鍵盤左右翻頁（iOS 點邊緣的桌面對應）。
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') renditionRef.current?.next()
      else if (e.key === 'ArrowLeft') renditionRef.current?.prev()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 容器尺寸變動 → epub.js 重排（CFI 保位）。epub.js 的 renderTo 用 width:'100%'
  // 但 *不會* 隨 CSS 寬度變化自動 reflow（內文仍排在舊量測欄寬，分頁/座標漂移）。
  // 桌面殼層把 host 鎖到 --reader-measure 居中後，host 像素寬會變，故必須以
  // ResizeObserver 主動呼叫 rendition.resize(w,h) 讓文字重排到新欄寬。重排前先讀
  // 目前 CFI、resize 後 display(cfi) 還原閱讀位置（避免重排把讀者彈回章首）。
  // parity 路徑（.phone-frame 固定 393×852）host 尺寸恆定 → observer 不觸發，零影響。
  useEffect(() => {
    const host = hostRef.current
    if (!host || typeof ResizeObserver === 'undefined') return
    let raf = 0
    let lastW = host.clientWidth
    let lastH = host.clientHeight
    const ro = new ResizeObserver(() => {
      const w = host.clientWidth
      const h = host.clientHeight
      if (w === lastW && h === lastH) return
      lastW = w
      lastH = h
      const r = renditionRef.current
      if (!r || w <= 0 || h <= 0) return
      // 連續 resize 合併到下一動畫幀，避免拖曳時高頻重排卡頓。
      if (raf) cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        raf = 0
        try {
          const cfi: string | undefined = r.currentLocation?.()?.start?.cfi
          r.resize(w, h)
          if (cfi) r.display(cfi).catch(() => {})
        } catch {
          /* teardown / 尚未 ready：下次 resize 會再校 */
        }
      })
    })
    ro.observe(host)
    return () => {
      if (raf) cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [])

  // 位置同步 flush 觸發器：visibilitychange（切背景）+ beforeunload（關頁/重整）。
  useEffect(() => {
    function onVisibility() {
      if (document.visibilityState === 'hidden') flushPosition()
    }
    window.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('beforeunload', flushPosition)
    return () => {
      window.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('beforeunload', flushPosition)
    }
  }, [flushPosition])

  function goTo(href: string) {
    renditionRef.current?.display(href)
    setPanel('none')
  }

  function updateSettings(next: LiveReaderSettings) {
    live.updateSettings(next)
    applyTheme(next, themeRef.current)
  }
  function updateTheme(next: LiveTheme) {
    live.updateTheme(next)
    applyTheme(settingsRef.current, next)
  }

  // shell=1 時優先顯示後端書名（撈到才覆蓋）；否則沿用 EPUB metadata 書名。
  const displayTitle = live.bookTitle || bookTitle || 'Reader'

  return (
    <div
      className="live-reader"
      data-ready={ready ? '' : undefined}
      data-theme={live.theme === 'dark' ? 'dark' : undefined}
      // desktop pane: TOC 變持久左側子面板時，內文欄需讓位（CSS 以此 attr 內推）。
      // 非殼層 / 行動裝置 overlay 路徑此 attr 無 CSS 對應 → 純資料、零視覺影響。
      data-toc-open={panel === 'toc' ? '' : undefined}
    >
      {/* paper 底色（對齊 parity reader paperSepia） */}
      <div className="live-reader-paper">
        <div ref={hostRef} className="live-reader-host" />
      </div>

      {/* 翻頁熱區（左右半屏，iOS Readium 點擊翻頁體感） */}
      <button
        className="live-reader-tap live-reader-tap-prev"
        aria-label="上一頁"
        onClick={() => renditionRef.current?.prev()}
      />
      <button
        className="live-reader-tap live-reader-tap-next"
        aria-label="下一頁"
        onClick={() => renditionRef.current?.next()}
      />

      {/* expanded header（沿用 parity reader.css：書庫 + 居中書名 + 鈕） */}
      <div className="reader-header-expanded live-reader-header">
        <div className="reader-toolbar">
          <button
            type="button"
            className="reader-toolbar-back"
            aria-label="書庫"
            onClick={() => onBack?.()}
          >
            <ChevronLeftIcon size={15} strokeWidth={1.7} />
            <span className="reader-toolbar-back-label">書庫</span>
          </button>
          <span className="reader-toolbar-title">{displayTitle}</span>
          <div className="reader-toolbar-actions">
            <button
              type="button"
              className="reader-chrome-btn"
              aria-label="目錄"
              onClick={() => setPanel((p) => (p === 'toc' ? 'none' : 'toc'))}
            >
              <ListBulletIcon size={14} strokeWidth={1.7} />
            </button>
            <button
              type="button"
              className="reader-chrome-btn"
              aria-label="閱讀設定"
              onClick={() => setPanel((p) => (p === 'settings' ? 'none' : 'settings'))}
            >
              <TextformatSizeIcon size={14} strokeWidth={1.6} />
            </button>
          </div>
        </div>
      </div>

      {/* compact 進度膠囊（沿用 parity .reader-progress-badge） */}
      {progress > 0 && (
        <div className="live-reader-progress">
          <span className="reader-progress-badge">
            <BookClosedIcon size={12} strokeWidth={1.6} />
            <span className="reader-progress-num">{(progress * 100).toFixed(1)}%</span>
          </span>
        </div>
      )}

      {/* TOC 面板（epub.js 章節真跳轉，沿用 parity rpanel 視覺殼） */}
      {panel === 'toc' && (
        <div className="live-reader-overlay" onClick={() => setPanel('none')}>
          <div className="rpanel rpanel-toc live-reader-panel-toc" onClick={(e) => e.stopPropagation()}>
            <header className="rpanel-nav">
              <span className="rpanel-nav-title">目錄</span>
              <button type="button" className="rpanel-nav-action" onClick={() => setPanel('none')}>
                完成
              </button>
            </header>
            <div className="rpanel-toc-body">
              {toc.length > 0 ? (
                <ul className="rpanel-toc-list">
                  {toc.map((t, i) => (
                    <li key={i} className="rpanel-toc-row">
                      <button
                        type="button"
                        className="rpanel-toc-row-text live-reader-toc-btn"
                        onClick={() => goTo(t.href)}
                      >
                        {t.label || `章節 ${i + 1}`}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="rpanel-state-wrap">
                  <div className="rpanel-empty-card">
                    <h2 className="rpanel-empty-title">這本書沒有目錄</h2>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Settings 面板（字級 + serif/sans + 紙色主題即時生效，沿用 parity rsettings 視覺殼） */}
      {panel === 'settings' && (
        <div className="live-reader-overlay live-reader-overlay-bottom" onClick={() => setPanel('none')}>
          <LiveSettingsPanel
            settings={live.settings}
            theme={live.theme}
            onChange={updateSettings}
            onThemeChange={updateTheme}
            onClose={() => setPanel('none')}
          />
        </div>
      )}

      {/* 翻譯面板（真實 parity TranslationPanel，內容來自 /api/translate）。 */}
      {live.panel && (
        <div className="reader-bottom-overlay live-reader-translation" data-overlay="translation">
          <div className="reader-scrim" onClick={live.closePanel} />
          <div onClick={(e) => e.stopPropagation()}>
            <TranslationPanel
              panel={live.panel}
              actions={{
                onToggleExpand: live.toggleExpand,
                onDelete: live.deleteCurrent,
                onClose: live.closePanel,
              }}
            />
          </div>
        </div>
      )}

      {error && <div className="live-reader-error">載入失敗：{error}</div>}
    </div>
  )
}

/** 紙色主題 CSS（注入 section iframe）。paper = 預設不覆寫；dark = 暗底亮字。 */
function themeBodyCss(theme: LiveTheme): string {
  if (theme === 'dark') {
    return `body{background:#1c1c1e !important;color:#e6e1d8 !important;}
a{color:#9bbcdc !important;}`
  }
  return ''
}

/** Live 設定面板 — 字級 stepper + serif/sans 字體 + 紙色主題，即時作用 epub.js。
 *  沿用 parity reader.css 的 rsettings 視覺類別。 */
function LiveSettingsPanel({
  settings,
  theme,
  onChange,
  onThemeChange,
  onClose,
}: {
  settings: LiveReaderSettings
  theme: LiveTheme
  onChange: (s: LiveReaderSettings) => void
  onThemeChange: (t: LiveTheme) => void
  onClose: () => void
}) {
  const fonts: LiveFont[] = ['serif', 'sans']
  const themes: { id: LiveTheme; label: string }[] = [
    { id: 'paper', label: '紙色' },
    { id: 'dark', label: '夜間' },
  ]
  return (
    <div className="rpanel rpanel-settings" onClick={(e) => e.stopPropagation()}>
      <div className="rsettings-card">
        <span className="rsettings-handle" aria-hidden="true" />
        <header className="rsettings-header">
          <span className="rsettings-header-title">閱讀設定</span>
          <button type="button" className="rsettings-close" aria-label="關閉閱讀設定" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="rsettings-scroll">
          <section className="rsettings-section">
            <h3 className="rsettings-section-title">排版</h3>
            <div className="rsettings-font-row">
              <button
                type="button"
                className={`rsettings-stepper${canDecrease(settings.fontSize) ? '' : ' is-disabled'}`}
                data-size="small"
                aria-label="縮小字級"
                disabled={!canDecrease(settings.fontSize)}
                onClick={() => onChange({ ...settings, fontSize: decreaseFontSize(settings.fontSize) })}
              >
                A
              </button>
              <span className="rsettings-font-size">{fontSizeText(settings.fontSize)}</span>
              <button
                type="button"
                className={`rsettings-stepper${canIncrease(settings.fontSize) ? '' : ' is-disabled'}`}
                data-size="large"
                aria-label="放大字級"
                disabled={!canIncrease(settings.fontSize)}
                onClick={() => onChange({ ...settings, fontSize: increaseFontSize(settings.fontSize) })}
              >
                A
              </button>
            </div>
          </section>

          <div className="rsettings-air-divider" />

          <section className="rsettings-section">
            <h3 className="rsettings-section-title">外觀</h3>
            <div className="live-reader-font-toggle">
              {fonts.map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`rsettings-tile${settings.font === f ? ' is-selected' : ''}`}
                  aria-pressed={settings.font === f}
                  onClick={() => onChange({ ...settings, font: f })}
                >
                  {FONT_LABEL[f]}
                </button>
              ))}
            </div>
            <div className="live-reader-font-toggle live-reader-theme-toggle">
              {themes.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`rsettings-tile${theme === t.id ? ' is-selected' : ''}`}
                  aria-pressed={theme === t.id}
                  onClick={() => onThemeChange(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
