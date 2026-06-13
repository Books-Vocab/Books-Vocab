import { useRef, useState } from 'react'
import { useAuth } from '../../auth'
import { Sheet } from '../../motion'
import type { ScenarioId } from '../../harness/scenarios'
import { useShellNav } from '../../shell/ShellNavContext'
import { pushTargetFor, screenFor } from '../../shell/nav'
import { VocabSceneShell } from '../../shared/VocabSceneShell'
import { BookCard } from './BookCard'
import type { BookFixture } from './fixtures'
import { BookIcon, DocIcon, PencilIcon, TrashIcon, XmarkIcon } from './icons'
import { useBookshelfStore } from './store'
import { useBookshelfApiStore } from './useBookshelfApiStore'
import './bookshelf.css'

/**
 * 鏡像 ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift 的靜態快照面：
 * （中文文案逐字取自 BookshelfCopy.swift——iOS 端改文案時此處須同步）
 * large-title nav（「書庫」Athelas/Songti 34 bold）+ 書格（2 欄 adaptive、
 * 間距 24）或空狀態（book glyph + 三行文案 + outline 匯入鈕）。
 * Catalog 參考快照不含 toolbar glyph 與 login/demo CTA（preview auth 已登入），
 * web 對拍面同樣不渲染。
 *
 * 互動化（fixtures 當資料層，store 薄狀態）：匯入入口開 sheet stub（檔案 picker
 * 視覺，不真解析）；書卡 more 選單 → 改名（真輸入）/ 刪除（即時移除，刪光落入
 * empty 視覺）。誠實邊界：web 無 SwiftData/CloudKit/檔案系統，匯入不入庫、改名/
 * 刪除不持久化、不反向傳播 CloudKit（iOS BookshelfCoordinator 對應流程為 no-op）。
 * parity 契約：初值 books = fixture(scenario)、無浮層 → capture 首屏與靜態版逐位元相同。
 *
 * 當 URL 含 shell=1 時，切換至 API-backed useBookshelfApiStore（真實後端書目 +
 * 瀏覽器檔案 picker 匯入 metadata，不上傳 raw bytes）。非 ready 態由 VocabSceneShell 包裹。
 */
export function BookshelfScreen({ scenario }: { scenario: ScenarioId<'bookshelf'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <BookshelfScreenApi />
  }
  return <BookshelfScreenFixture scenario={scenario} />
}

/** Fixture-driven screen — parity harness 路徑（無 shell=1 時，零 API 呼叫）。 */
function BookshelfScreenFixture({ scenario }: { scenario: ScenarioId<'bookshelf'> }) {
  const store = useBookshelfStore(scenario)
  return <BookshelfBody store={store} importMode="stub" />
}

/** API-driven screen — shell=1 時使用真實後端書目 + 檔案 picker 匯入。 */
function BookshelfScreenApi() {
  const { isLoggedIn } = useAuth()
  const store = useBookshelfApiStore()

  // 訪客（未登入）：書庫綁帳號，無 token → list 必 401/失敗。此時顯示友善「登入以
  // 同步書庫」空態，而非把帳號態誤報成「無法載入書庫」網路錯誤。對齊 iOS：登出時
  // 書架顯示登入引導而非錯誤橫幅。
  if (!isLoggedIn) {
    return <GuestShelf />
  }

  return (
    <VocabSceneShell
      status={
        store.status === 'ready' ? 'content' : store.status === 'loading' ? 'loading' : 'error'
      }
      onRetry={store.retry}
      errorTitle="無法載入書庫"
    >
      <BookshelfBody store={store} importMode="file" onImportFile={store.importFile} />
    </VocabSceneShell>
  )
}

/** 訪客空態 — 未登入時的友善書庫引導（非網路錯誤）。 */
function GuestShelf() {
  return (
    <div className="bookshelf">
      <header className="bookshelf-nav">
        <h1 className="bookshelf-nav-title">書庫</h1>
      </header>
      <main className="bookshelf-scroll bookshelf-empty">
        <div className="bookshelf-empty-content">
          <BookIcon size={52} strokeWidth={0.9} className="bookshelf-empty-icon" />
          <p className="bookshelf-empty-title">登入以同步書庫</p>
          <p className="bookshelf-empty-description">登入後，你在各裝置匯入的書籍會在這裡同步顯示。</p>
        </div>
      </main>
    </div>
  )
}

/** 共享的書架本體（fixture / API 兩條路共用）。 */
interface BookshelfBodyStore {
  books: BookFixture[]
  importing: boolean
  menuTitle: string | null
  renamingTitle: string | null
  openImport: () => void
  closeImport: () => void
  openMenu: (title: string) => void
  closeMenu: () => void
  openRenameFor: (title: string) => void
  closeRename: () => void
  renameBook: (oldTitle: string, newTitle: string) => void | Promise<void>
  deleteBook: (title: string) => void | Promise<void>
}

function BookshelfBody({
  store,
  importMode,
  onImportFile,
}: {
  store: BookshelfBodyStore
  /** 'stub' = parity 視覺占位（不真選檔）；'file' = 真檔案 picker（API 路徑）。 */
  importMode: 'stub' | 'file'
  onImportFile?: (file: File) => void | Promise<void>
}) {
  // 殼層導航：點書封面 → push 真閱讀器（帶 bookId=title）。parity 路徑無 provider →
  // navigate no-op，封面點擊不做事，DOM/capture 行為不變。
  const nav = useShellNav()
  const openBook = (title: string) => {
    const target = pushTargetFor(screenFor('bookshelf'), 'open-book', { bookId: title })
    if (target) nav.navigate(target)
  }

  const renamingBook =
    store.renamingTitle !== null
      ? store.books.find((b) => b.title === store.renamingTitle) ?? null
      : null

  return (
    <div className="bookshelf">
      <header className="bookshelf-nav">
        <h1 className="bookshelf-nav-title">書庫</h1>
      </header>
      {store.books.length === 0 ? (
        <EmptyShelf onImport={store.openImport} />
      ) : (
        <BookGrid
          books={store.books}
          onOpen={openBook}
          onMore={store.openMenu}
          onImport={store.openImport}
        />
      )}

      {/* ── 浮層（互動後才掛載，首屏無此 DOM）── */}
      {/* 次動作選單（改名 / 刪除）migrated 到共享 Sheet：vaul 處理 Esc / backdrop /
          drag-dismiss / focus trap，徹底治掉舊 scrim「Esc 不關」的互動 bug。
          導航推進時 menuTitle 仍為 null（openBook 不開選單），故換頁自然無殘留浮層。 */}
      <Sheet
        open={store.menuTitle !== null}
        onClose={store.closeMenu}
        ariaLabel={store.menuTitle ? `${store.menuTitle} 更多動作` : '書籍動作'}
      >
        {store.menuTitle !== null && (
          <BookCardMenuContent
            title={store.menuTitle}
            onRename={() => store.openRenameFor(store.menuTitle!)}
            onDelete={() => store.deleteBook(store.menuTitle!)}
          />
        )}
      </Sheet>
      {/* 匯入 sheet（stub / 真檔案 picker 共用共享 Sheet 殼，dismiss 統一由 vaul 治理）。 */}
      <Sheet open={store.importing} onClose={store.closeImport} ariaLabel="匯入書籍">
        {store.importing &&
          (importMode === 'file' ? (
            <ImportSheetFile onClose={store.closeImport} onPick={onImportFile} />
          ) : (
            <ImportSheet onClose={store.closeImport} />
          ))}
      </Sheet>
      {/* 改名 sheet（真輸入框）。key=書名 → 換書時重建 input 初值（autoFocus 重觸）。 */}
      <Sheet open={renamingBook !== null} onClose={store.closeRename} ariaLabel="重新命名">
        {renamingBook && (
          <RenameSheet
            key={renamingBook.title}
            initialTitle={renamingBook.title}
            onSubmit={(title) => store.renameBook(renamingBook.title, title)}
            onClose={store.closeRename}
          />
        )}
      </Sheet>
    </div>
  )
}

function BookGrid({
  books,
  onOpen,
  onMore,
  onImport,
}: {
  books: BookFixture[]
  onOpen: (title: string) => void
  onMore: (title: string) => void
  onImport: () => void
}) {
  return (
    <main className="bookshelf-scroll">
      {/* 匯入入口 — 透明 overlay 鈕（toolbar import 在 parity 快照不渲染，故以
          pixel-neutral 透明 affordance 承接，hover 才淡入）。 */}
      <button
        type="button"
        className="bookshelf-import-affordance"
        aria-label="匯入書籍"
        onClick={onImport}
      >
        <DocIcon size={18} />
      </button>
      <div className="bookshelf-grid">
        {books.map((book) => (
          <BookCard
            key={`${book.title}-${book.format}`}
            book={book}
            onOpen={() => onOpen(book.title)}
            onMore={() => onMore(book.title)}
          />
        ))}
      </div>
      <a className="bookshelf-guide-link" href="#guide">
        了解更多
      </a>
    </main>
  )
}

function EmptyShelf({ onImport }: { onImport: () => void }) {
  return (
    <main className="bookshelf-scroll bookshelf-empty">
      <div className="bookshelf-empty-content">
        {/* measured：iOS 為 symbol(size:48,.ultraLight)，PNG 實測 glyph ≈52pt 框 */}
        <BookIcon size={52} strokeWidth={0.9} className="bookshelf-empty-icon" />
        <p className="bookshelf-empty-title">尚無書籍</p>
        <p className="bookshelf-empty-description">匯入電子書開始閱讀（EPUB・TXT・MD・PDF）</p>
        <p className="bookshelf-empty-guidance">點擊上方匯入按鈕加入你的第一本書</p>
      </div>
      <button type="button" className="bookshelf-empty-import" onClick={onImport}>
        匯入
      </button>
    </main>
  )
}

/**
 * 書卡次動作選單內容（改名 / 刪除）。鏡射 iOS BookCard contextMenu。
 * 渲染於共享 <Sheet> 內 → scrim / Esc / backdrop / drag-dismiss 由 vaul 統一處理
 * （不再自帶 scrim role=dialog；那曾是「Esc 不關」bug 的根源）。
 */
function BookCardMenuContent({
  title,
  onRename,
  onDelete,
}: {
  title: string
  onRename: () => void
  onDelete: () => void
}) {
  return (
    <div className="bs-menu">
      <p className="bs-menu-title">{title}</p>
      <button type="button" className="bs-menu-item" onClick={onRename}>
        <PencilIcon size={17} />
        <span>改名</span>
      </button>
      <button type="button" className="bs-menu-item bs-menu-item-destructive" onClick={onDelete}>
        <TrashIcon size={17} />
        <span>刪除</span>
      </button>
    </div>
  )
}

/** 匯入 sheet stub — 檔案 picker 視覺（不真解析、不入庫，CloudKit 同步為 web no-op）。 */
function ImportSheet({ onClose }: { onClose: () => void }) {
  const ACCEPTED = ['EPUB', 'PDF', 'TXT', 'MD']
  return (
    <div className="bs-sheet-form">
      <div className="bs-sheet-head">
        <p className="bs-sheet-title">匯入書籍</p>
        <button type="button" className="bs-sheet-close" aria-label="關閉" onClick={onClose}>
          <XmarkIcon size={16} />
        </button>
      </div>
      {/* 檔案 picker 視覺占位 — web 端不真選檔/解析（誠實 stub）。 */}
      <div className="bs-import-picker">
        <DocIcon size={40} className="bs-import-picker-icon" />
        <p className="bs-import-picker-hint">選擇檔案以加入書庫</p>
        <div className="bs-import-formats">
          {ACCEPTED.map((fmt) => (
            <span key={fmt} className="bs-import-format">
              {fmt}
            </span>
          ))}
        </div>
      </div>
      <p className="bs-import-note">web 預覽不解析檔案，匯入於 iOS App 進行。</p>
    </div>
  )
}

/**
 * 匯入 sheet（真檔案 picker）— shell=1 API 路徑。選檔後解析最小 metadata
 * （title=檔名、format=副檔名）並 POST 後端，**不上傳 raw bytes**。
 */
function ImportSheetFile({
  onClose,
  onPick,
}: {
  onClose: () => void
  onPick?: (file: File) => void | Promise<void>
}) {
  const ACCEPTED = ['EPUB', 'PDF', 'TXT', 'MD']
  const inputRef = useRef<HTMLInputElement | null>(null)
  return (
    <div className="bs-sheet-form">
      <div className="bs-sheet-head">
        <p className="bs-sheet-title">匯入書籍</p>
        <button type="button" className="bs-sheet-close" aria-label="關閉" onClick={onClose}>
          <XmarkIcon size={16} />
        </button>
      </div>
      {/* 真檔案 picker：僅讀檔名/格式做 metadata，不讀檔案內容。 */}
      <button
        type="button"
        className="bs-import-picker"
        onClick={() => inputRef.current?.click()}
        aria-label="選擇檔案"
      >
        <DocIcon size={40} className="bs-import-picker-icon" />
        <p className="bs-import-picker-hint">選擇檔案以加入書庫</p>
        <div className="bs-import-formats">
          {ACCEPTED.map((fmt) => (
            <span key={fmt} className="bs-import-format">
              {fmt}
            </span>
          ))}
        </div>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".epub,.txt,.md,.pdf"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onPick?.(file)
          e.target.value = ''
        }}
      />
      <p className="bs-import-note">僅同步書籍資訊（書名・格式），不上傳檔案內容。</p>
    </div>
  )
}

/** 改名 sheet（真輸入框）。鏡射 iOS 書籍改名流程。 */
function RenameSheet({
  initialTitle,
  onSubmit,
  onClose,
}: {
  initialTitle: string
  onSubmit: (title: string) => void
  onClose: () => void
}) {
  const [title, setTitle] = useState(initialTitle)
  const canSubmit = title.trim().length > 0
  return (
    <div className="bs-sheet-form">
      <div className="bs-sheet-head">
        <p className="bs-sheet-title">重新命名</p>
        <button type="button" className="bs-sheet-close" aria-label="關閉" onClick={onClose}>
          <XmarkIcon size={16} />
        </button>
      </div>
      <input
        className="bs-sheet-input"
        type="text"
        placeholder="書名"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="書名"
        autoFocus
      />
      <button
        type="button"
        className="bs-sheet-submit"
        disabled={!canSubmit}
        onClick={() => onSubmit(title)}
      >
        儲存
      </button>
    </div>
  )
}
