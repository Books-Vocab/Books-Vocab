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
import { loadingPanel, resolvedPanel } from './mockTranslation'
import type { TranslationPanelData } from '../reader/fixtures'
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
 * Live Reader — web Reader 生產化 phase 1。
 *
 * epub.js 真渲染引擎（spike `ReaderLiveScreen` 的演進）嵌進像素級 parity reader
 * chrome：expanded header（書庫 + 居中書名 + TOC/設定/單字本鈕）、compact 進度膠囊、
 * bottom-overlay 翻譯面板掛點，全部沿用 `reader.css` 的既有視覺語彙。
 *
 *   選詞 → 真實 parity `TranslationPanel`（內容 mock，見 mockTranslation.ts）。
 *   TOC  → epub.js navigation 章節清單 + `rendition.display(href)` 真跳轉。
 *   設定 → 字級（iOS 檔位 0.75…2.0 step 0.125）+ serif/sans 即時作用於 epub.js。
 *   翻頁 → 點左右半屏熱區 + 鍵盤左右；字級/字體改變即時 registerCss 重套。
 *
 * 隔離：epub.js dynamic import，僅此路徑載入，不進 parity bundle；既有 parity
 * surface（?surface=reader 等）DOM 與渲染零改動。
 */

const EPUB_URL = '/spike/childrens-literature.epub'

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

export function LiveReaderScreen({ onBack }: { onBack?: () => void } = {}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const renditionRef = useRef<any>(null)
  const settingsRef = useRef<LiveReaderSettings>(DEFAULT_SETTINGS)

  const [toc, setToc] = useState<TocItem[]>([])
  const [progress, setProgress] = useState(0)
  const [bookTitle, setBookTitle] = useState('')
  const [panelData, setPanelData] = useState<TranslationPanelData | null>(null)
  const [panel, setPanel] = useState<Panel>('none')
  const [settings, setSettings] = useState<LiveReaderSettings>(DEFAULT_SETTINGS)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  // settings → epub.js registerCss（即時生效）。
  const applyTheme = useCallback((s: LiveReaderSettings) => {
    const r = renditionRef.current
    if (!r) return
    // registerCss 以相同 name 重註冊 → 覆寫舊 CSS；select 觸發 iframe 重套樣式。
    r.themes.registerCss('kg', bodyCss(s, location.origin))
    r.themes.select('kg')
  }, [])

  useEffect(() => {
    let destroyed = false
    let book: any = null

    async function boot() {
      try {
        const ePub = (await import('epubjs')).default
        if (destroyed || !hostRef.current) return
        book = ePub(EPUB_URL)
        const rendition = book.renderTo(hostRef.current, {
          width: '100%',
          height: '100%',
          flow: 'paginated',
          spread: 'none',
        })
        renditionRef.current = rendition

        rendition.themes.registerCss('kg', bodyCss(settingsRef.current, location.origin))
        rendition.themes.select('kg')

        // 選詞監聽：從父 context 綁 section document（spike 已驗）。
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
                const word = d.word
                const ctx = extractContext(d.el, word)
                openTranslation(word, ctx)
              },
              true,
            )
          } catch {
            /* teardown race */
          }
        })

        rendition.on('relocated', (loc: any) => {
          if (book.locations && book.locations.length()) {
            setProgress(book.locations.percentageFromCfi(loc.start.cfi) || 0)
          }
        })

        await book.ready
        if (destroyed) return
        setBookTitle((book.packaging?.metadata?.title as string) || 'EPUB')
        const nav = await book.loaded.navigation
        setToc((nav.toc || []).map((t: any) => ({ label: (t.label || '').trim(), href: t.href })))
        await rendition.display()
        setReady(true)
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
    // boot 只跑一次；settings 變更走 applyTheme（不重建 book）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 鍵盤左右翻頁（iOS 點邊緣的桌面對應）。
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') renditionRef.current?.next()
      else if (e.key === 'ArrowLeft') renditionRef.current?.prev()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function openTranslation(word: string, context: string) {
    setPanel('none')
    setPanelData(loadingPanel(word))
    // mock async：模擬翻譯延遲後填入譯文。
    window.setTimeout(() => {
      setPanelData(resolvedPanel(word, context, false))
    }, 280)
  }

  function goTo(href: string) {
    renditionRef.current?.display(href)
    setPanel('none')
  }

  function updateSettings(next: LiveReaderSettings) {
    settingsRef.current = next
    setSettings(next)
    applyTheme(next)
  }

  const closeTranslation = () => {
    setPanelData(null)
  }

  return (
    <div className="live-reader" data-ready={ready ? '' : undefined}>
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

      {/* expanded header（沿用 parity reader.css：書庫 + 居中書名 + 4 鈕） */}
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
          <span className="reader-toolbar-title">{bookTitle || 'Reader'}</span>
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

      {/* Settings 面板（字級 + serif/sans 即時生效，沿用 parity rsettings 視覺殼） */}
      {panel === 'settings' && (
        <div className="live-reader-overlay live-reader-overlay-bottom" onClick={() => setPanel('none')}>
          <LiveSettingsPanel
            settings={settings}
            onChange={updateSettings}
            onClose={() => setPanel('none')}
          />
        </div>
      )}

      {/* 翻譯面板（真實 parity TranslationPanel，內容 mock） */}
      {panelData && (
        <div className="reader-bottom-overlay live-reader-translation" data-overlay="translation">
          <div className="reader-scrim" onClick={closeTranslation} />
          <div onClick={(e) => e.stopPropagation()}>
            <TranslationPanel panel={panelData} />
          </div>
        </div>
      )}

      {error && <div className="live-reader-error">載入失敗：{error}</div>}
    </div>
  )
}

/** Live 設定面板 — 字級 stepper（iOS 檔位）+ serif/sans 字體切換，即時作用 epub.js。
 *  沿用 parity reader.css 的 rsettings 視覺類別。 */
function LiveSettingsPanel({
  settings,
  onChange,
  onClose,
}: {
  settings: LiveReaderSettings
  onChange: (s: LiveReaderSettings) => void
  onClose: () => void
}) {
  const fonts: LiveFont[] = ['serif', 'sans']
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
          </section>
        </div>
      </div>
    </div>
  )
}
