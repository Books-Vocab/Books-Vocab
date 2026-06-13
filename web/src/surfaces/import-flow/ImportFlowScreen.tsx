import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { Transition } from 'framer-motion'
import { gentle, reduced as instant, sheet, snappy } from '../../motion'

/** Pick a spring vs the instant transition based on the reduced-motion flag. */
function springOr(prefersReduced: boolean, spring: Transition): Transition {
  return prefersReduced ? instant : spring
}
import {
  ArrowClockwiseIcon,
  ArrowDownDocIcon,
  CheckmarkCircleIcon,
  DocTextIcon,
  ExclamationmarkCircleIcon,
  XmarkIcon,
} from './icons'
import { allSettled, isConfirmable, type ImportItem, type ImportStatus } from './importFlowMachine'
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
 * status + remove) → confirm-import footer. Empty state when nothing is picked,
 * success banner when every confirmable draft has landed in the library.
 *
 * ── FEEL (Phase 2) ───────────────────────────────────────────────────────────
 * The whole flow is choreographed with the shared motion springs (no hand-rolled
 * physics): the dropzone springs on drag-over, rows enter/exit via AnimatePresence
 * (slide+fade `snappy`), parsing rows carry an animated indeterminate progress
 * bar, the status badge cross-fades between phases (the done checkmark pops in
 * with a `sheet` spring), the confirm footer springs up from the bottom edge, and
 * a success banner fades+rises in once everything is settled. Every animation is
 * gated by `useReducedMotion()` so motion-sensitive users get an instant swap.
 *
 * PARITY ISOLATION: this surface is NOT a parity-captured Catalog mirror (it has
 * no ?scenario/?appearance capture axis — see App.tsx). framer-motion here only
 * adds transform/opacity to surface-local DOM; it cannot reach the .phone-frame
 * parity fixtures of other surfaces.
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
  const reduced = useReducedMotion() ?? false

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
  // Success = at least one book landed AND nothing is left to do/retry.
  const doneCount = flow.items.filter((it) => it.status === 'done').length
  const settled = allSettled(flow.items)
  const showSuccess = settled && doneCount > 0

  return (
    <div className="import-flow">
      <header className="if-nav">
        <h1 className="if-nav-title">匯入書籍</h1>
      </header>

      <div className="if-scroll">
        {/* ── drop / select zone ──
            Springs on drag-over (snappy scale) so the drop affordance feels
            "live"; reduced-motion users get the colour change only. */}
        <motion.div
          className="if-dropzone"
          data-dragging={dragging ? '1' : undefined}
          role="button"
          tabIndex={0}
          aria-label="選擇或拖放檔案"
          animate={{ scale: !reduced && dragging ? 1.02 : 1 }}
          transition={springOr(reduced, snappy)}
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
        </motion.div>

        {/* ── success banner ──
            Rises+fades in once every confirmable draft has landed; honest
            celebration only (no nav: import-flow has no shell entry/exit edge —
            see verification gap note). */}
        <AnimatePresence initial={false}>
          {showSuccess ? (
            <motion.div
              key="if-success"
              className="if-success"
              role="status"
              initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
              transition={springOr(reduced, sheet)}
            >
              <motion.span
                className="if-success-icon"
                initial={reduced ? false : { scale: 0.6, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={springOr(reduced, sheet)}
              >
                <CheckmarkCircleIcon size={22} />
              </motion.span>
              <div className="if-success-text">
                <div className="if-success-title">已加入書庫</div>
                <div className="if-success-desc">
                  {doneCount} 本書已加入你的書庫，可在書架中開啟。
                </div>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {/* ── parsed-draft list / empty ──
            Rows enter/exit via AnimatePresence so picks slide+fade in and
            removals animate out instead of snapping. */}
        {hasItems ? (
          <ul className="if-list">
            <AnimatePresence initial={false}>
              {flow.items.map((item) => (
                <ImportRow
                  key={item.id}
                  item={item}
                  reduced={reduced}
                  onRemove={() => flow.remove(item.id)}
                  onRetry={() => void flow.retry(item.id)}
                />
              ))}
            </AnimatePresence>
          </ul>
        ) : (
          <motion.div
            className="if-empty"
            initial={reduced ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springOr(reduced, gentle)}
          >
            <DocTextIcon className="if-empty-icon" size={30} strokeWidth={1.3} />
            <div className="if-empty-title">尚未選擇檔案</div>
            <div className="if-empty-desc">選擇本機的 EPUB、TXT 或 Markdown 檔來加入你的書庫。</div>
          </motion.div>
        )}
      </div>

      {/* ── confirm footer（有待匯入項目才掛載）──
          Springs up from the bottom edge on mount / down on unmount. */}
      <AnimatePresence initial={false}>
        {flow.confirmableCount > 0 ? (
          <motion.div
            key="if-footer"
            className="if-footer"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: '100%' }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: '100%' }}
            transition={springOr(reduced, sheet)}
          >
            <button
              type="button"
              className="if-confirm"
              disabled={flow.isBusy}
              onClick={() => void flow.confirmImport()}
            >
              加入書庫（{flow.confirmableCount}）
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}

/** One parsed-draft row: cover/format + title/author + status + remove/retry. */
function ImportRow({
  item,
  reduced,
  onRemove,
  onRetry,
}: {
  item: ImportItem
  reduced: boolean
  onRemove: () => void
  onRetry: () => void
}) {
  const draft = item.draft
  const title = draft?.title ?? item.filename
  const parsing = item.status === 'parsing' || item.status === 'pending'
  return (
    <motion.li
      className="if-row"
      data-status={item.status}
      layout={!reduced}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: item.status === 'done' ? 0.7 : 1, y: 0, scale: 1 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, x: 24, scale: 0.98 }}
      transition={springOr(reduced, snappy)}
    >
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
          <StatusBadge item={item} reduced={reduced} />
        </div>
        {/* animated indeterminate progress while reading/parsing */}
        <AnimatePresence initial={false}>
          {parsing ? (
            <motion.div
              key="parse-progress"
              className="if-progress"
              initial={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 3 }}
              exit={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
              transition={springOr(reduced, gentle)}
              aria-hidden="true"
            >
              {!reduced ? (
                <motion.span
                  className="if-progress-bar"
                  animate={{ x: ['-60%', '160%'] }}
                  transition={{ duration: 1.1, ease: 'easeInOut', repeat: Infinity }}
                />
              ) : (
                <span className="if-progress-bar if-progress-bar--static" />
              )}
            </motion.div>
          ) : null}
        </AnimatePresence>
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
    </motion.li>
  )
}

function StatusBadge({ item, reduced }: { item: ImportItem; reduced: boolean }) {
  const label = STATUS_LABEL[item.status]
  // Cross-fade between status phases so a row's badge transitions with feel
  // instead of swapping abruptly (keyed by status → AnimatePresence swap).
  return (
    <AnimatePresence initial={false} mode="wait">
      <motion.span
        key={item.status}
        className={badgeClass(item.status)}
        initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.85 }}
        transition={springOr(reduced, item.status === 'done' ? sheet : snappy)}
      >
        {item.status === 'done' ? <CheckmarkCircleIcon size={13} /> : null}
        {item.status === 'error' ? <ExclamationmarkCircleIcon size={13} /> : null}
        {item.status === 'parsing' || item.status === 'uploading' ? <Spinner /> : null}
        {label}
      </motion.span>
    </AnimatePresence>
  )
}

/** Per-status badge class (kept in sync with the status enum). */
function badgeClass(status: ImportStatus): string {
  if (status === 'done') return 'if-badge if-badge--done'
  if (status === 'error') return 'if-badge if-badge--error'
  if (status === 'parsing' || status === 'uploading') return 'if-badge if-badge--busy'
  return 'if-badge'
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
