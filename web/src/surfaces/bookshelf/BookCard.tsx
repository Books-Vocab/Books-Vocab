import type { BookFixture } from './fixtures'
import { BookIcon, ICloudArrowDownIcon } from './icons'

/**
 * 鏡像 ios/BooksAndVocab/Views/Bookshelf/Components/BookCard.swift：
 * 封面（placeholder：book glyph + 標題 + 非 EPUB 格式 pill）→ 進度條
 * （0% 只剩 track + 隱形 % 占位）→ 標題（兩行保留）/作者/相對日期。
 * 幾何常數對齊 AppBookshelfMetrics（封面高 210、radius 10、徽章 padding 6）。
 */
export function BookCard({ book }: { book: BookFixture }) {
  return (
    <article className="book-card">
      <div className="book-card-cover">
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
