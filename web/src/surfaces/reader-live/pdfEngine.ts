/**
 * PDF 渲染引擎（Phase 2）— pdfjs-dist 的 reader-live 封裝。
 *
 * 與 epub.js 路徑對稱的「另一條引擎」：把一份 PDF 渲進 reader pane（canvas 視覺層
 * + 可選文字覆蓋層供選詞），支援上一頁／下一頁、resize 重排、進度回報。
 *
 * 隔離契約（與 epub.js 同）：
 *   - pdfjs 走 dynamic import（`loadPdfjs()`），只在 PDF 路徑載入，不進 parity bundle。
 *   - worker 以 `?url` 懶引入（Vite 切出獨立 chunk），同樣不進 parity 主包。
 *   - 文字覆蓋層不依賴 pdfjs 官方 pdf_viewer.css（避免拉一大包 viewer CSS 進來）；
 *     改以 getTextContent() item 的 transform 自行定位透明文字 span，視覺由
 *     live-reader.css 提供，CSS 全留 surface-local。
 *
 * 選詞流程沿用 LiveReaderScreen 既有的 caret-from-point 詞擷取（PDF 文字 span 為
 * 透明、可被 caretRangeFromPoint 命中），故選詞 / 翻譯 / 存詞迴圈與 epub 路徑共用。
 */

// pdfjs 型別（從 types/ 取，避免 import 進主包）。dynamic import 後以 any 操作 doc/page。
type PdfDocument = { numPages: number; getPage: (n: number) => Promise<PdfPage>; destroy: () => Promise<void> }
type PdfPage = {
  getViewport: (opts: { scale: number }) => PdfViewport
  render: (opts: { canvas: HTMLCanvasElement; viewport: PdfViewport }) => { promise: Promise<void>; cancel: () => void }
  getTextContent: () => Promise<{ items: Array<PdfTextItem | { type?: string }> }>
}
type PdfViewport = { width: number; height: number; transform: number[] }
type PdfTextItem = { str: string; transform: number[]; width: number; height: number }

let pdfjsModule: Promise<typeof import('pdfjs-dist')> | null = null

/**
 * 懶載 pdfjs + 掛 worker。memoize 避免重複載入。與 epub.js 的 `await import('epubjs')`
 * 對稱，確保 pdfjs（含 worker）只在 PDF 路徑載入，不進 parity 主包。
 *
 * worker 用 Vite `?worker` import（給出 Worker constructor）→ GlobalWorkerOptions.workerPort。
 * 為何不用 `?url` + workerSrc：dev 模式 pdfjs-dist 被 Vite 預打包（optimizeDeps），`?url`
 * 會被攔截成預打包模組（.default=undefined → "Invalid workerSrc type"，已實測）。`?worker`
 * 在 dev/prod 都穩定切出獨立 worker chunk 且回傳建構子，故為跨模式正解。
 */
async function loadPdfjs(): Promise<typeof import('pdfjs-dist')> {
  if (!pdfjsModule) {
    pdfjsModule = (async () => {
      const pdfjs = await import('pdfjs-dist')
      const PdfWorker = (await import('pdfjs-dist/build/pdf.worker.min.mjs?worker')).default
      pdfjs.GlobalWorkerOptions.workerPort = new PdfWorker()
      return pdfjs
    })()
  }
  return pdfjsModule
}

/** 渲染裝置像素比上限（避免高 DPI 螢幕產生過大 canvas 拖慢渲染）。 */
const MAX_DPR = 2

export interface PdfReader {
  /** 總頁數。 */
  readonly numPages: number
  /** 當前頁（1-based）。 */
  readonly page: number
  /** 進度 0..1（page / numPages）。 */
  readonly progress: number
  /** 渲染指定頁到 host（清掉舊頁，畫 canvas + 文字覆蓋層）。 */
  goToPage: (n: number) => Promise<void>
  /** 下一頁（到底不動）。回傳是否真的翻了。 */
  next: () => Promise<boolean>
  /** 上一頁（到頂不動）。回傳是否真的翻了。 */
  prev: () => Promise<boolean>
  /** 容器尺寸變動 → 以新寬度重排當前頁（保留頁碼）。 */
  resize: () => Promise<void>
  /** 銷毀：取消在途渲染 + 釋放 pdfjs document。 */
  destroy: () => void
}

/** 把 1-based 頁碼夾到 [1, numPages]。 */
export function clampPage(n: number, numPages: number): number {
  if (numPages <= 0) return 1
  return Math.min(Math.max(1, Math.round(n)), numPages)
}

/** progression(0..1) → 1-based 頁碼（恢復閱讀位置用）。 */
export function pageFromProgress(progress: number | null | undefined, numPages: number): number {
  if (!progress || progress <= 0 || numPages <= 0) return 1
  return clampPage(Math.floor(progress * numPages) + 1, numPages)
}

/**
 * 1-based 頁碼 → progression(0..1)（回寫位置用，與 pageFromProgress 對稱）。
 * 採「該頁起始」分數 (page-1)/numPages：對齊 epub.js percentageFromCfi 的
 * 「位置在頁首」語意，且令 pageFromProgress(progressFromPage(p))===p（round-trip）。
 */
export function progressFromPage(page: number, numPages: number): number {
  if (numPages <= 0) return 0
  return (clampPage(page, numPages) - 1) / numPages
}

/**
 * 開一份 PDF（bytes）並把頁渲進 host 容器。
 *
 * @param host         渲染容器（canvas + 文字層掛這裡，position:relative 由 CSS 提供）
 * @param data         PDF 位元組（getDocument 會 transfer/detach；呼叫端每次給新 buffer）
 * @param onWordSelect 選詞 callback（word, context）— 沿用迴圈的取詞→翻譯→存詞
 * @param onRelocate   翻頁後回報（page, progress）供進度膠囊 + 位置同步
 */
export async function openPdfReader(
  host: HTMLElement,
  data: Uint8Array,
  hooks: {
    onWordSelect: (word: string, context: string) => void
    onRelocate?: (page: number, progress: number) => void
  },
): Promise<PdfReader> {
  const pdfjs = await loadPdfjs()
  const doc = (await pdfjs.getDocument({ data }).promise) as unknown as PdfDocument

  let currentPage = 1
  // 意圖頁碼：next/prev/goTo 同步更新此值（連續翻頁從「最後一次請求」遞進，不卡在已提交頁）。
  let intendedPage = 1
  let activeRender: { cancel: () => void } | null = null
  let destroyed = false
  // 渲染序號守衛：併發 renderPage（連續翻頁／resize 競態）只讓「最後一次」提交 DOM；
  // 較舊的呼叫在每個 await 邊界後檢查 token，過期即靜默 bail（不碰 currentPage / DOM）。
  let renderSeq = 0

  function cssWidth(): number {
    const w = host.clientWidth
    return w > 0 ? w : 612 // host 尚未量到寬度時的安全預設（letter 寬）
  }

  async function renderPage(n: number): Promise<void> {
    if (destroyed) return
    const seq = ++renderSeq
    const target = clampPage(n, doc.numPages)
    intendedPage = target
    // 取消任何在途渲染（連續翻頁／resize 不疊加）；其 await 會丟 cancelled 並由 seq 守衛 bail。
    activeRender?.cancel()
    activeRender = null

    const page = await doc.getPage(target)
    if (destroyed || seq !== renderSeq) return

    // 以 host 寬度推算 CSS scale，讓單頁鋪滿欄寬；canvas 本體用 dpr 放大求清晰。
    const unscaled = page.getViewport({ scale: 1 })
    const targetW = cssWidth()
    const cssScale = targetW / unscaled.width
    const dpr = Math.min(typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1, MAX_DPR)
    // CSS 版型用的 viewport（座標供文字層定位）；canvas 像素用 dpr-放大版。
    const viewport = page.getViewport({ scale: cssScale })
    const deviceViewport = page.getViewport({ scale: cssScale * dpr })

    const canvas = document.createElement('canvas')
    canvas.className = 'live-pdf-canvas'
    canvas.width = Math.floor(deviceViewport.width)
    canvas.height = Math.floor(deviceViewport.height)
    canvas.style.width = `${Math.floor(viewport.width)}px`
    canvas.style.height = `${Math.floor(viewport.height)}px`

    // pdfjs v6：傳 `canvas` 元素（不傳 canvasContext — 兩者並存會 stall，已實測 hang）。
    // dpr 由 deviceViewport 內建（canvas 像素 = CSS×dpr），文字層仍用 CSS viewport 座標。
    const task = page.render({ canvas, viewport: deviceViewport })
    activeRender = task
    try {
      await task.promise
    } catch (e: unknown) {
      // RenderingCancelledException：被新一輪渲染取消，安靜略過。
      if ((e as { name?: string })?.name === 'RenderingCancelledException') return
      throw e
    }
    if (destroyed || seq !== renderSeq) return
    activeRender = null

    // 文字覆蓋層（透明、可選）：以 CSS viewport.transform 定位，供 caretRangeFromPoint 選詞。
    const textLayer = await buildTextLayer(page, viewport)
    if (destroyed || seq !== renderSeq) return

    // 一次性換頁：先備好新節點再清舊，避免翻頁閃白。
    const pageEl = document.createElement('div')
    pageEl.className = 'live-pdf-page'
    pageEl.style.width = `${Math.floor(viewport.width)}px`
    pageEl.style.height = `${Math.floor(viewport.height)}px`
    pageEl.appendChild(canvas)
    pageEl.appendChild(textLayer)

    // 提交：到此 seq 仍為最新，才更新 currentPage + DOM + 回報（避免過期頁覆蓋）。
    currentPage = target
    host.replaceChildren(pageEl)
    hooks.onRelocate?.(currentPage, progressFromPage(currentPage, doc.numPages))
  }

  /** 由 getTextContent 建透明、可點選的文字 span 覆蓋層（不依賴 pdfjs viewer CSS）。 */
  async function buildTextLayer(page: PdfPage, viewport: PdfViewport): Promise<HTMLElement> {
    const layer = document.createElement('div')
    layer.className = 'live-pdf-text-layer'
    layer.style.width = `${Math.floor(viewport.width)}px`
    layer.style.height = `${Math.floor(viewport.height)}px`
    let content: { items: Array<PdfTextItem | { type?: string }> }
    try {
      content = await page.getTextContent()
    } catch {
      return layer // 取文字失敗：仍顯示 canvas，僅選詞不可用
    }
    const vt = viewport.transform
    for (const raw of content.items) {
      const item = raw as PdfTextItem
      if (typeof item.str !== 'string' || item.str.length === 0) continue
      // PDF 文字座標經 viewport.transform 投影到 canvas 座標系（pdfjs Util 同算法）。
      const t = item.transform
      const a = vt[0] * t[0] + vt[2] * t[1]
      const b = vt[1] * t[0] + vt[3] * t[1]
      const c = vt[0] * t[2] + vt[2] * t[3]
      const d = vt[1] * t[2] + vt[3] * t[3]
      const x = vt[0] * t[4] + vt[2] * t[5] + vt[4]
      const y = vt[1] * t[4] + vt[3] * t[5] + vt[5]
      const fontHeight = Math.hypot(c, d)
      const span = document.createElement('span')
      span.textContent = item.str
      span.style.position = 'absolute'
      span.style.left = `${x}px`
      span.style.top = `${y - fontHeight}px`
      span.style.fontSize = `${fontHeight}px`
      span.style.lineHeight = '1'
      span.style.whiteSpace = 'pre'
      // 透明字（canvas 已畫出可見文字）；透明文字仍可被 caretRangeFromPoint 命中。
      span.style.color = 'transparent'
      const angle = Math.atan2(b, a)
      if (angle !== 0) span.style.transform = `rotate(${angle}rad)`
      span.style.transformOrigin = '0 0'
      layer.appendChild(span)
    }
    // 點選：caret-from-point 擷詞（與 epub 路徑同義），命中 → onWordSelect。
    layer.addEventListener('click', (e: MouseEvent) => {
      const hit = wordFromPoint(layer.ownerDocument, e.clientX, e.clientY)
      if (!hit) return
      hooks.onWordSelect(hit.word, hit.context)
    })
    return layer
  }

  const reader: PdfReader = {
    get numPages() {
      return doc.numPages
    },
    get page() {
      return currentPage
    },
    get progress() {
      return progressFromPage(currentPage, doc.numPages)
    },
    async goToPage(n: number) {
      await renderPage(n)
    },
    async next() {
      if (intendedPage >= doc.numPages) return false
      await renderPage(intendedPage + 1)
      return true
    },
    async prev() {
      if (intendedPage <= 1) return false
      await renderPage(intendedPage - 1)
      return true
    },
    async resize() {
      await renderPage(intendedPage)
    },
    destroy() {
      destroyed = true
      activeRender?.cancel()
      activeRender = null
      doc.destroy().catch(() => {})
    },
  }

  await renderPage(1)
  return reader
}

// ── 選詞 caret 擷取（PDF 文字層版；對齊 LiveReaderScreen 的 epub 版邏輯）──────────
// PDF 文字層的 span 各自一行片段；以 caretRangeFromPoint 取命中字，向兩側擴成完整詞，
// context 取該 span（行片段）文字。導出供測試與重用。

const WORD_CHAR = /[a-zA-Z'-]/

/** 在文字層 document 內以座標取詞 + 行片段 context（透明 span 仍可命中 caret）。 */
export function wordFromPoint(
  doc: Document,
  x: number,
  y: number,
): { word: string; context: string } | null {
  const range = doc.caretRangeFromPoint ? doc.caretRangeFromPoint(x, y) : null
  if (!range || range.startContainer.nodeType !== Node.TEXT_NODE) return null
  const text = range.startContainer.textContent || ''
  const off = range.startOffset
  const word = expandWord(text, off)
  if (!word) return null
  return { word, context: text.trim() || word }
}

/** 由命中 offset 向兩側擴成完整英文詞（去頭尾撇號／連字號）。長度 < 2 視為無效。 */
export function expandWord(text: string, offset: number): string | null {
  let s = Math.min(Math.max(offset, 0), text.length)
  let e = s
  while (s > 0 && WORD_CHAR.test(text[s - 1])) s--
  while (e < text.length && WORD_CHAR.test(text[e])) e++
  const word = text.slice(s, e).replace(/^['-]+|['-]+$/g, '')
  return word.length >= 2 ? word : null
}
