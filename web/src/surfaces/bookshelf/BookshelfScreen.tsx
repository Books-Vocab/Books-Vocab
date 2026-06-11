import type { ScenarioId } from '../../harness/scenarios'
import { BookCard } from './BookCard'
import { bookshelfFixture } from './fixtures'
import { BookIcon } from './icons'
import './bookshelf.css'

/**
 * 鏡像 ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift 的靜態快照面：
 * （中文文案逐字取自 BookshelfCopy.swift——iOS 端改文案時此處須同步）
 * large-title nav（「書庫」Athelas/Songti 34 bold）+ 書格（2 欄 adaptive、
 * 間距 24）或空狀態（book glyph + 三行文案 + outline 匯入鈕）。
 * Catalog 參考快照不含 toolbar glyph 與 login/demo CTA（preview auth 已登入），
 * web 對拍面同樣不渲染。
 */
export function BookshelfScreen({ scenario }: { scenario: ScenarioId<'bookshelf'> }) {
  const books = bookshelfFixture(scenario)
  return (
    <div className="bookshelf">
      <header className="bookshelf-nav">
        <h1 className="bookshelf-nav-title">書庫</h1>
      </header>
      {books.length === 0 ? <EmptyShelf /> : <BookGrid books={books} />}
    </div>
  )
}

function BookGrid({ books }: { books: ReturnType<typeof bookshelfFixture> }) {
  return (
    <main className="bookshelf-scroll">
      <div className="bookshelf-grid">
        {books.map((book) => (
          <BookCard key={`${book.title}-${book.format}`} book={book} />
        ))}
      </div>
      <a className="bookshelf-guide-link" href="#guide">
        了解更多
      </a>
    </main>
  )
}

function EmptyShelf() {
  return (
    <main className="bookshelf-scroll bookshelf-empty">
      <div className="bookshelf-empty-content">
        {/* measured：iOS 為 symbol(size:48,.ultraLight)，PNG 實測 glyph ≈52pt 框 */}
        <BookIcon size={52} strokeWidth={0.9} className="bookshelf-empty-icon" />
        <p className="bookshelf-empty-title">尚無書籍</p>
        <p className="bookshelf-empty-description">匯入電子書開始閱讀（EPUB・TXT・MD・PDF）</p>
        <p className="bookshelf-empty-guidance">點擊上方匯入按鈕加入你的第一本書</p>
      </div>
      <button type="button" className="bookshelf-empty-import">
        匯入
      </button>
    </main>
  )
}
