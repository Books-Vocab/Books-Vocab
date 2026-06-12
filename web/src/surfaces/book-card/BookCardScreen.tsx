import type { ScenarioId } from '../../harness/scenarios'
import { BOOK_CARD_FIXTURES } from './fixtures'
import { BookIcon, ICloudArrowDownIcon } from './icons'
import './book-card.css'

/**
 * BookCard surface — iOS `BookCard`(ios/BooksAndVocab/Views/Bookshelf/Components/
 * BookCard.swift) 的 web 鏡像。VStack(spacing s2)：
 *   封面（placeholder：book glyph + 標題 + 非 EPUB 格式 pill，bottomTrailing
 *   iCloud 待下載徽章）→ 進度條（capsule track + 填充，0% 只剩 track + 隱形 %
 *   占位）→ 元資料（caption.medium 標題兩行保留 / caption2 作者 / caption2
 *   相對日期，無日期時單空格撐等高）。
 *
 * BookCard 在 catalog `.frame(width: 180).padding()`。component scene 畫布透明
 * （corner srgba 0,0,0,0）：crop 目標 = surface intrinsic box（card width 180 +
 * scene wrapper .padding(24)），surface 與 phone-frame 在 crop=component 下透明，
 * shots omitBackground 截圖 → web 與 ref 同為 card-over-transparent。
 *
 * 幾何全走 design-system token（cover-height-compact / cover-corner-radius /
 * progress-bar-height-card / s2 / tiny-gap / micro-gap / s1 / radius-sm）；
 * parity-measured 收斂常數（標題 16px lh + 32px min-height + 1px ink 微調、
 * progress mono 10pt line-height 1、徽章 25px 框）沿用 bookshelf BookCard 既證值。
 */
export function BookCardScreen({ scenario }: { scenario: ScenarioId<'book-card'> }) {
  const book = BOOK_CARD_FIXTURES[scenario]
  return (
    <div className="book-card-component-surface">
      <article className="book-card">
        <div className="book-card-cover">
          <div className="book-card-placeholder">
            {/* iOS AppFonts.h1(28pt) SF symbol 渲染框，PNG 實測 ≈34px 寬 */}
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
          <span className="book-card-progress-track">
            <span
              className="book-card-progress-fill"
              style={{ width: `${Math.min(Math.max(book.progression, 0), 1) * 100}%` }}
            />
          </span>
          {/* 0% → opacity 0 但保留寬度占位（iOS .opacity(clamped > 0 ? 1 : 0)） */}
          <span
            className="book-card-progress-label"
            style={{ opacity: book.progression > 0 ? 1 : 0 }}
          >
            {Math.round(Math.min(Math.max(book.progression, 0), 1) * 100)}%
          </span>
        </div>

        <div className="book-card-meta">
          <h3 className="book-card-title">{book.title}</h3>
          <p className="book-card-author">{book.author}</p>
          <p className="book-card-date">{book.dateLabel || ' '}</p>
        </div>
      </article>
    </div>
  )
}
