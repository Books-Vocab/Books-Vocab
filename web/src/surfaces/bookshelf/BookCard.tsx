import { useRef } from 'react'
import { motion } from 'framer-motion'
import { snappy, usePreferredTransition } from '../../motion'
import type { BookFixture } from './fixtures'
import { BookIcon, EllipsisIcon, ICloudArrowDownIcon } from './icons'

/**
 * 鏡像 ios/BooksAndVocab/Views/Bookshelf/Components/BookCard.swift：
 * 封面（placeholder：book glyph + 標題 + 非 EPUB 格式 pill）→ 進度條
 * （0% 只剩 track + 隱形 % 占位）→ 標題（兩行保留）/作者/相對日期。
 * 幾何常數對齊 AppBookshelfMetrics（封面高 210、radius 10、徽章 padding 6）。
 *
 * 互動模型（iOS 對標 + web feel）：
 *  - 主動作 = 單擊封面 → `onOpen`（開書進閱讀器，殼層以 RouteTransition push）。
 *    鏡射 iOS BookCard 的 tap-to-open（context menu 才是次要動作，非主動作）。
 *  - 次動作（改名 / 刪除）= `onMore`，以三種次要 affordance 觸發：
 *      desktop hover-revealed overflow 鈕（右上三點）、touch long-press、right-click。
 *    對齊 iOS BookCard 的 `.contextMenu`（長按）語意，桌面補 hover overflow。
 *  - 按壓手感：封面 whileTap 微縮放 + 變暗（snappy spring，尊重 reduced-motion）。
 *
 * parity 邊界：`onOpen`/`onMore` 缺省時（靜態 / 元件級用法）overflow 鈕與封面互動
 * 全不掛載，封面退回純 <div> → 首屏 DOM/像素零變動。overflow 鈕 glyph 預設隱形
 * （hover/focus 才淡入），即使掛載亦 pixel-neutral；按壓手感僅 :active 期間生效，
 * 不影響靜止首屏。
 */
const LONG_PRESS_MS = 450

export function BookCard({
  book,
  onOpen,
  onMore,
}: {
  book: BookFixture
  /** 單擊封面 → 開書（殼層接 open-book nav intent）。缺省 = 封面不互動。 */
  onOpen?: () => void
  /** 次動作（改名 / 刪除）：overflow 鈕 / long-press / right-click 觸發。 */
  onMore?: () => void
}) {
  // 按壓手感過渡：snappy spring，prefers-reduced-motion 時瞬時（無縮放動畫）。
  const pressTransition = usePreferredTransition(snappy)

  // Long-press（touch 次要 affordance）：按住封面達門檻 → onMore；提前抬起/移動/
  // 取消則作廢，避免與單擊（onOpen）衝突。
  const longPressTimer = useRef<number | null>(null)
  const longPressed = useRef(false)

  const clearLongPress = () => {
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
  }

  const startLongPress = () => {
    if (!onMore) return
    longPressed.current = false
    clearLongPress()
    longPressTimer.current = window.setTimeout(() => {
      longPressed.current = true
      onMore()
    }, LONG_PRESS_MS)
  }

  const coverInteractive = Boolean(onOpen || onMore)

  const coverInner = (
    <>
      {/* overflow 鈕置於 cover 首位（badge 之前）：badge 的 backdrop-filter 取樣其
          下方內容，overflow 在 badge 之下 → 不擾動 badge 合成，pixel-neutral。 */}
      {onMore && (
        <button
          type="button"
          className="book-card-overflow"
          aria-label={`${book.title} 更多動作`}
          data-title={book.title}
          onClick={(e) => {
            // 次動作鈕：阻止冒泡到封面 onOpen，僅開選單。
            e.stopPropagation()
            onMore()
          }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <EllipsisIcon size={18} className="book-card-overflow-glyph" />
        </button>
      )}
      <div className="book-card-placeholder">
        {/* measured：iOS 為 AppFonts.h1(28pt) 字級的 SF symbol 渲染框，PNG 實測 ≈34pt 寬 */}
        <BookIcon size={34} className="book-card-placeholder-icon" />
        <span className="book-card-placeholder-title">{book.title}</span>
        {book.format !== 'epub' && (
          <span className="book-card-format-pill">{book.format.toUpperCase()}</span>
        )}
      </div>
      {book.needsICloudDownload && (
        <span className="book-card-cloud-badge">
          <ICloudArrowDownIcon size={13} strokeWidth={2.2} />
        </span>
      )}
    </>
  )

  return (
    <article className="book-card">
      {coverInteractive ? (
        <motion.button
          type="button"
          className="book-card-cover book-card-cover-button"
          aria-label={`開啟 ${book.title}`}
          // 按壓手感：縮放 + 變暗（spring）。reduced-motion → 瞬時。
          whileTap={{ scale: 0.97, opacity: 0.88 }}
          transition={pressTransition}
          onClick={() => {
            // long-press 已觸發次動作 → 吞掉這次 click，不誤開書。
            if (longPressed.current) {
              longPressed.current = false
              return
            }
            onOpen?.()
          }}
          onContextMenu={
            onMore
              ? (e) => {
                  e.preventDefault()
                  onMore()
                }
              : undefined
          }
          onPointerDown={startLongPress}
          onPointerUp={clearLongPress}
          onPointerLeave={clearLongPress}
          onPointerCancel={clearLongPress}
          onPointerMove={clearLongPress}
        >
          {coverInner}
        </motion.button>
      ) : (
        <div className="book-card-cover">{coverInner}</div>
      )}

      <div className="book-card-progress">
        <span className="book-card-progress-track" />
        {/* 0% 時 opacity 0 但保留寬度占位 — 對齊 iOS `.opacity(clamped > 0 ? 1 : 0)` */}
        <span
          className="book-card-progress-label"
          style={{ opacity: book.progression > 0 ? 1 : 0 }}
        >
          {Math.round(book.progression * 100)}%
        </span>
      </div>

      <div className="book-card-meta">
        <h3 className="book-card-title">{book.title}</h3>
        <p className="book-card-author">{book.author}</p>
        <p className="book-card-date">{book.dateLabel || ' '}</p>
      </div>
    </article>
  )
}
