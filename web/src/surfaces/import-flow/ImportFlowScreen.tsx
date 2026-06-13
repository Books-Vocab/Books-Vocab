import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import {
  ArrowClockwiseIcon,
  ArrowDownDocIcon,
  CheckmarkCircleIcon,
  DocTextIcon,
  ExclamationmarkCircleIcon,
  XmarkIcon,
} from './icons'
import { isConfirmable, type ImportItem, type ImportStatus } from './importFlowMachine'
import { useImportFlow } from './useImportFlow'
import './import-flow.css'

/**
 * Import-flow surface — file picker → import engine → library.create.
 *
 * Reachable standalone at `?surface=import-flow` (no shell/bookshelf dependency),
 * so it is demoable/testable in isolation. Always API-backed: confirm-import
 * POSTs to /api/library/books via the real LibraryClient (idempotent by
 * client_book_id). Honest boundary: the "open import from the bookshelf" button
 * is OUT OF SCOPE here (it touches shell/bookshelf, owned by a concurrent run);
 * wiring that entry point is deferred to reconverge.
 *
 * Structure: large nav title → drop/select zone → parsed-draft list (each with
 * status + remove) → confirm-import footer. Empty state when nothing is picked.
 */

const ACCEPT = '.epub,.txt,.md,.markdown,application/epub+zip,text/plain,text/markdown'

/** Per-status Chinese label (reuses 解析中 / 加入書庫 phrasing). */
const STATUS_LABEL: Record<ImportStatus, string> = {
  pending: '等待中',
  parsing: '解析中',
  ready: '待匯入',
  uploading: '加入書庫中',
  done: '已加入書庫',
  error: '失敗',
}

export function ImportFlowScreen() {
  const flow = useImportFlow()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const onPick = () => inputRef.current?.click()

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) flow.addFiles(files)
    // reset so re-picking the same file fires change again
    e.target.value = ''
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files ?? [])
    if (files.length > 0) flow.addFiles(files)
  }

  const hasItems = flow.items.length > 0

  return (
    <div className="import-flow">
      <header className="if-nav">
        <h1 className="if-nav-title">匯入書籍</h1>
      </header>

      <div className="if-scroll">
        {/* ── drop / select zone ── */}
        <div
          className="if-dropzone"
          data-dragging={dragging ? '1' : undefined}
          role="button"
          tabIndex={0}
          aria-label="選擇或拖放檔案"
          onClick={onPick}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onPick()
            }
          }}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <ArrowDownDocIcon className="if-dropzone-icon" size={34} strokeWidth={1.4} />
          <div className="if-dropzone-title">拖放或選擇檔案</div>
          <div className="if-dropzone-hint">支援 EPUB、TXT、Markdown</div>
          <input
            ref={inputRef}
            className="if-file-input"
            type="file"
            multiple
            accept={ACCEPT}
            onChange={onInputChange}
            aria-hidden="true"
            tabIndex={-1}
          />
        </div>

        {/* ── parsed-draft list / empty ── */}
        {hasItems ? (
          <ul className="if-list">
            {flow.items.map((item) => (
              <ImportRow key={item.id} item={item} onRemove={() => flow.remove(item.id)} onRetry={() => void flow.retry(item.id)} />
            ))}
          </ul>
        ) : (
          <div className="if-empty">
            <DocTextIcon className="if-empty-icon" size={30} strokeWidth={1.3} />
            <div className="if-empty-title">尚未選擇檔案</div>
            <div className="if-empty-desc">選擇本機的 EPUB、TXT 或 Markdown 檔來加入你的書庫。</div>
          </div>
        )}
      </div>

      {/* ── confirm footer（有待匯入項目才掛載）── */}
      {flow.confirmableCount > 0 && (
        <div className="if-footer">
          <button
            type="button"
            className="if-confirm"
            disabled={flow.isBusy}
            onClick={() => void flow.confirmImport()}
          >
            加入書庫（{flow.confirmableCount}）
          </button>
        </div>
      )}
    </div>
  )
}

/** One parsed-draft row: cover/format + title/author + status + remove/retry. */
function ImportRow({
  item,
  onRemove,
  onRetry,
}: {
  item: ImportItem
  onRemove: () => void
  onRetry: () => void
}) {
  const draft = item.draft
  const title = draft?.title ?? item.filename
  return (
    <li className="if-row" data-status={item.status}>
      {/* cover / format badge */}
      <div className="if-row-cover">
        {draft?.coverDataUrl ? (
          <img className="if-row-cover-img" src={draft.coverDataUrl} alt="" />
        ) : (
          <div className="if-row-cover-fallback">
            <span className="if-row-format">{(draft?.format ?? '—').toUpperCase()}</span>
          </div>
        )}
      </div>

      {/* metadata */}
      <div className="if-row-meta">
        <div className="if-row-title">{title}</div>
        <div className="if-row-sub">
          {draft?.author ? <span className="if-row-author">{draft.author}</span> : null}
          <StatusBadge item={item} />
        </div>
        {item.error?.stage === 'parse' ? (
          <div className="if-row-error">{parseErrorCopy(item)}</div>
        ) : null}
        {item.error?.stage === 'upload' ? (
          <div className="if-row-error">無法加入書庫，請重試。</div>
        ) : null}
      </div>

      {/* trailing action: retry (upload error) or remove */}
      <div className="if-row-actions">
        {item.status === 'error' && item.error?.stage === 'upload' && isConfirmable(item) ? (
          <button type="button" className="if-row-retry" aria-label="重試" onClick={onRetry}>
            <ArrowClockwiseIcon size={17} />
          </button>
        ) : null}
        {item.status !== 'uploading' ? (
          <button type="button" className="if-row-remove" aria-label="移除" onClick={onRemove}>
            <XmarkIcon size={16} />
          </button>
        ) : null}
      </div>
    </li>
  )
}

function StatusBadge({ item }: { item: ImportItem }) {
  const label = STATUS_LABEL[item.status]
  if (item.status === 'done') {
    return (
      <span className="if-badge if-badge--done">
        <CheckmarkCircleIcon size={13} />
        {label}
      </span>
    )
  }
  if (item.status === 'error') {
    return (
      <span className="if-badge if-badge--error">
        <ExclamationmarkCircleIcon size={13} />
        {label}
      </span>
    )
  }
  if (item.status === 'parsing' || item.status === 'uploading') {
    return (
      <span className="if-badge if-badge--busy">
        <Spinner />
        {label}
      </span>
    )
  }
  return <span className="if-badge">{label}</span>
}

/** Maps the engine error code to user-facing copy（reuse 不支援的格式 style）. */
function parseErrorCopy(item: ImportItem): string {
  switch (item.error?.code) {
    case 'unsupported_format':
      return '不支援的格式（僅支援 EPUB、TXT、Markdown）。'
    case 'empty_content':
      return '檔案內容是空的。'
    case 'parse_failed':
    default:
      return '無法解析此檔案。'
  }
}

/** Small inline spinner（沿用 VocabSceneShell 12-輻條漸隱環語彙）。 */
function Spinner() {
  const spokes = 12
  return (
    <svg className="if-spinner" viewBox="0 0 16 16" width={13} height={13} aria-hidden="true">
      {Array.from({ length: spokes }, (_, i) => {
        const angle = (i * 360) / spokes
        const opacity = 0.25 + (0.75 * i) / (spokes - 1)
        return (
          <rect
            key={i}
            x={7.3}
            y={1.4}
            width={1.4}
            height={3.6}
            rx={0.7}
            fill="currentColor"
            opacity={opacity}
            transform={`rotate(${angle} 8 8)`}
          />
        )
      })}
    </svg>
  )
}
