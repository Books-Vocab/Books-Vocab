import { useEffect, useRef, useState, type CSSProperties } from 'react'
import './reader-live.css'

/**
 * Reader 引擎 spike（探索性，非 parity 路徑）。只在 ?surface=reader-live 啟用，
 * epub.js 走 dynamic import → 不進 parity capture bundle，既有 ?surface=reader 等
 * 路徑與 DOM 完全不變。
 *
 * 目標：驗證 web 能否複製 iOS Readium 閱讀體感 ——
 *   橫向分頁（CSS columns，epub.js paginated flow）、章節跳轉、單字點選取詞+座標、
 *   套用既有 reader 字體/排版 token（CrimsonPro serif）讓視覺與 parity 版同源。
 *
 * iOS 的選詞/取 context 是注入 webview 的純 JS（非 Readium API），故可原樣移植到
 * epub.js 的 per-section iframe（rendition.hooks.content）。
 */

const EPUB_URL = '/spike/childrens-literature.epub'

type TocItem = { label: string; href: string }
type SelectedWord = { word: string; context: string; x: number; y: number }

// iOS buildWordRangeFromPoint 的 web 移植：caret 吸附 + 詞邊界擴展 + 去頭尾標點。
// SPIKE 發現：epub.js 把 section 渲染進 *sandboxed* iframe（無 allow-scripts），
// 故注入 <script> 會被瀏覽器擋。改從父 context 在 contents.document 上綁監聽
// （epub.js 把 section document 暴露給父框，同源可直接操作）。
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

export function ReaderLiveScreen() {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const renditionRef = useRef<any>(null)
  const [toc, setToc] = useState<TocItem[]>([])
  const [tocOpen, setTocOpen] = useState(false)
  const [progress, setProgress] = useState(0)
  const [bookTitle, setBookTitle] = useState('')
  const [selected, setSelected] = useState<SelectedWord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let destroyed = false
    let book: any = null

    async function boot() {
      try {
        // dynamic import：epub.js 只在此 spike 路徑載入，永不進 parity bundle。
        const ePub = (await import('epubjs')).default
        if (destroyed || !hostRef.current) return
        book = ePub(EPUB_URL)
        const rendition = book.renderTo(hostRef.current, {
          width: '100%',
          height: '100%',
          flow: 'paginated', // 橫向分頁（CSS columns）= iOS Readium 同款體感
          spread: 'none',
        })
        renditionRef.current = rendition

        // 套既有 reader 字體/排版 token（與 parity 版同源）：CrimsonPro serif 注入
        // section iframe。iframe 為獨立 document，@font-face 需用絕對 URL。
        rendition.themes.registerCss(
          'kg',
          `@font-face{font-family:'CrimsonPro';src:url('${location.origin}/fonts/CrimsonPro.woff2') format('woff2');font-weight:200 900;}
           body{font-family:'CrimsonPro',Georgia,serif !important;font-size:19px !important;line-height:1.6 !important;color:#37352f !important;padding:0 8px !important;}
           p{text-align:left !important;}`,
        )
        rendition.themes.select('kg')

        // 每個 section 渲染後，從父 context 在 section document 綁選詞監聽。
        // contents.document 由 epub.js 暴露給父框（同源），故無需注入 script。
        rendition.hooks.content.register((contents: any) => {
          try {
            const doc: Document = contents.document
            doc.addEventListener(
              'click',
              (e: MouseEvent) => {
                if ((e.target as Element)?.closest?.('a')) return
                const d = wordFromPoint(doc, e.clientX, e.clientY)
                if (!d) return
                const dx = Math.max(d.rect.left - e.clientX, 0, e.clientX - d.rect.right)
                const dy = Math.max(d.rect.top - e.clientY, 0, e.clientY - d.rect.bottom)
                if (Math.sqrt(dx * dx + dy * dy) > 12) return
                // section iframe 在父框的位移：用 frame 的 getBoundingClientRect。
                const frame = contents.window?.frameElement as HTMLIFrameElement | undefined
                const off = frame ? frame.getBoundingClientRect() : { left: 0, top: 0 }
                const word = d.word
                const ctx = extractContext(d.el, word)
                setSelected({
                  word,
                  context: ctx,
                  x: off.left + d.rect.left + d.rect.width / 2,
                  y: off.top + d.rect.top,
                })
                // eslint-disable-next-line no-console
                console.log('[reader-live] wordTap', word, '@', d.rect, 'ctx:', ctx.slice(0, 80))
              },
              true,
            )
          } catch {
            /* teardown race — spike 容忍 */
          }
        })

        rendition.on('relocated', (loc: any) => {
          if (book.locations && book.locations.length()) {
            setProgress(book.locations.percentageFromCfi(loc.start.cfi) || 0)
          }
          setSelected(null) // 翻頁清掉選詞浮層
        })

        await book.ready
        if (destroyed) return
        setBookTitle((book.packaging?.metadata?.title as string) || 'EPUB')
        const nav = await book.loaded.navigation
        setToc(
          (nav.toc || []).map((t: any) => ({ label: (t.label || '').trim(), href: t.href })),
        )
        await rendition.display()
        setReady(true)
        // locations：分頁進度模型（iOS totalProgression 對應物）。背景生成，不阻塞首屏。
        book.locations.generate(1600).catch(() => {})
      } catch (e: any) {
        if (!destroyed) setError(String(e?.message || e))
      }
    }

    boot()
    return () => {
      destroyed = true
      try {
        book?.destroy()
      } catch {
        /* noop */
      }
    }
  }, [])

  const goTo = (href: string) => {
    renditionRef.current?.display(href)
    setTocOpen(false)
  }

  return (
    <div className="rlive" data-ready={ready ? '' : undefined}>
      {/* 本體：epub.js 掛載點（分頁 iframe 渲染於此） */}
      <div ref={hostRef} className="rlive-host" onClick={() => setSelected(null)} />

      {/* 翻頁熱區（左右半屏，iOS Readium 點擊翻頁體感） */}
      <button
        className="rlive-tap rlive-tap-prev"
        aria-label="上一頁"
        onClick={() => renditionRef.current?.prev()}
      />
      <button
        className="rlive-tap rlive-tap-next"
        aria-label="下一頁"
        onClick={() => renditionRef.current?.next()}
      />

      {/* 頂部 chrome（沿用 parity 視覺語彙） */}
      <div className="rlive-header">
        <button className="rlive-chrome-btn" onClick={() => setTocOpen((v) => !v)} aria-label="目錄">
          ☰
        </button>
        <span className="rlive-title">{bookTitle || 'Reader 引擎 spike'}</span>
        <span className="rlive-progress">{(progress * 100).toFixed(0)}%</span>
      </div>

      {/* TOC 面板（接 parity TocPanel 視覺殼的精神，簡化版） */}
      {tocOpen && (
        <div className="rlive-toc">
          <div className="rlive-toc-head">目錄</div>
          <ul className="rlive-toc-list">
            {toc.map((t, i) => (
              <li key={i}>
                <button onClick={() => goTo(t.href)}>{t.label || `章節 ${i + 1}`}</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 選詞浮層（不接翻譯，僅展示 word + 座標 + context，驗證 hook 能力） */}
      {selected && (
        <div
          className="rlive-selection"
          style={{ '--x': `${selected.x}px`, '--y': `${selected.y}px` } as CSSProperties}
        >
          <strong className="rlive-selection-word">{selected.word}</strong>
          <span className="rlive-selection-ctx">{selected.context}</span>
        </div>
      )}

      {error && <div className="rlive-error">載入失敗：{error}</div>}
    </div>
  )
}
