import type { BookFixture } from './fixtures'
import { BookIcon, EllipsisIcon, ICloudArrowDownIcon } from './icons'

/**
 * 鏡像 ios/BooksAndVocab/Views/Bookshelf/Components/BookCard.swift：
 * 封面（placeholder：book glyph + 標題 + 非 EPUB 格式 pill）→ 進度條
 * （0% 只剩 track + 隱形 % 占位）→ 標題（兩行保留）/作者/相對日期。
 * 幾何常數對齊 AppBookshelfMetrics（封面高 210、radius 10、徽章 padding 6）。
 *
 * 互動化：封面疊透明 more overlay 鈕（鏡射 iOS BookCard context menu 的 long-press），
 * 無視覺 chrome → pixel-neutral；點擊開 more 選單（改名 / 刪除）。`onMore` 缺省時
 * 不掛 overlay（靜態用法零變動）。
 */
export function BookCard({ book, onMore }: { book: BookFixture; onMore?: () => void }) {
  return (
    <article className="book-card">
      <div className="book-card-cover">
        {/* more overlay 置於 cover 首位（badge 之前）：badge 的 backdrop-filter 取樣
            其下方內容，overlay 在 badge 之下 → 不擾動 badge 合成，pixel-neutral。 */}
        {onMore && (
          <button
            type="button"
            className="book-card-more"
            aria-label={`${book.title} 選單`}
            data-title={book.title}
            onClick={onMore}
          >
            <EllipsisIcon size={18} className="book-card-more-glyph" />
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
      </div>

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
        <p className="book-card-date">{book.dateLabel || ' '}</p>
      </div>
    </article>
  )
}
