// Import-flow status machine — PURE, framework-free, jsdom-free.
//
// The web import surface is: browser File -> parse locally (import engine) ->
// BookImportDraft -> LibraryClient.create (POST /api/library/books). Each picked
// file is one `ImportItem` walking a small status machine:
//
//   pending  → (read+parse)  → ready    (draft extracted, awaiting confirm)
//   pending  → (read+parse)  → error    (unsupported / parse_failed / empty)
//   ready    → (confirm)     → uploading
//   uploading→ (create ok)   → done     (carries the created book id)
//   uploading→ (create fail) → error    (retryable: error → ready → uploading)
//
// React (useImportFlow) owns timing + the real engine + the real LibraryClient.
// THIS module owns the data-only transitions so they can be unit-tested against
// a mock library client with no DOM. The "engine"/"client" are injected as
// async functions, mirroring the iOS import path's seam between parse + create.

import type { BookImportDraft, ImportErrorCode } from '../../import'
import { draftToCreateRequest } from '../../import'
import type { BookCreateRequest, BookMetadataResponse } from '../../api/types'

/** Per-file lifecycle status. */
export type ImportStatus =
  /** Picked, not yet parsed. */
  | 'pending'
  /** Reading bytes / running the engine. */
  | 'parsing'
  /** Parsed into a draft; awaiting confirm-import. */
  | 'ready'
  /** create() in flight. */
  | 'uploading'
  /** create() succeeded; book exists on the backend. */
  | 'done'
  /** Parse or upload failed (retryable when it carries a draft). */
  | 'error'

/** Where a failure happened — drives copy + retry affordance. */
export type ImportFailureStage = 'parse' | 'upload'

/** A structured per-item failure. */
export interface ImportItemError {
  stage: ImportFailureStage
  /** Engine error code when stage==='parse'; undefined for upload failures. */
  code?: ImportErrorCode
  /** Human/debug detail (English; the UI maps to L10n copy). */
  message: string
}

/**
 * One picked file walking the status machine. `id` is a stable per-pick key
 * (NOT the idempotency key — that lives on the draft as clientBookId). `draft`
 * is present once parsing succeeds; `createdBookId` once upload succeeds.
 */
export interface ImportItem {
  id: string
  filename: string
  sizeBytes: number
  status: ImportStatus
  draft?: BookImportDraft
  error?: ImportItemError
  createdBookId?: string
}

/** Minimal surface of LibraryClient the upload step needs (mockable in tests). */
export interface LibraryLike {
  create(req: BookCreateRequest): Promise<BookMetadataResponse>
}

/** Engine result for a single file, as produced by the React layer's reader. */
export type ParseOutcome =
  | { ok: true; draft: BookImportDraft }
  | { ok: false; code: ImportErrorCode; message: string }

// ── pure transitions ─────────────────────────────────────────────────────────

/** Replace the item with matching id; identity if none match. */
export function updateItem(
  items: ImportItem[],
  id: string,
  patch: (item: ImportItem) => ImportItem,
): ImportItem[] {
  return items.map((it) => (it.id === id ? patch(it) : it))
}

/** Drop the item with matching id (remove from the list). */
export function removeItem(items: ImportItem[], id: string): ImportItem[] {
  return items.filter((it) => it.id !== id)
}

/** pending/error(parse) → parsing. Clears any stale parse error. */
export function toParsing(item: ImportItem): ImportItem {
  return { ...item, status: 'parsing', error: undefined }
}

/** parsing → ready|error from a ParseOutcome. */
export function applyParseOutcome(item: ImportItem, outcome: ParseOutcome): ImportItem {
  if (outcome.ok) {
    return { ...item, status: 'ready', draft: outcome.draft, error: undefined }
  }
  return {
    ...item,
    status: 'error',
    error: { stage: 'parse', code: outcome.code, message: outcome.message },
  }
}

/** ready/error(upload) → uploading. Clears any stale upload error. */
export function toUploading(item: ImportItem): ImportItem {
  return { ...item, status: 'uploading', error: undefined }
}

/** uploading → done, recording the created book id. */
export function toDone(item: ImportItem, createdBookId: string): ImportItem {
  return { ...item, status: 'done', createdBookId, error: undefined }
}

/** uploading → error, recording the failure (draft preserved for retry). */
export function toUploadError(item: ImportItem, message: string): ImportItem {
  return { ...item, status: 'error', error: { stage: 'upload', message } }
}

// ── predicates ───────────────────────────────────────────────────────────────

/** An item that has a draft and is waiting to be (re)uploaded. */
export function isConfirmable(item: ImportItem): boolean {
  if (item.draft == null) return false
  return item.status === 'ready' || (item.status === 'error' && item.error?.stage === 'upload')
}

/** Count of items the confirm-import action would act on. */
export function confirmableCount(items: ImportItem[]): number {
  return items.filter(isConfirmable).length
}

/** True once every item is terminal (done or unretryable parse error). */
export function allSettled(items: ImportItem[]): boolean {
  if (items.length === 0) return false
  return items.every((it) => it.status === 'done' || (it.status === 'error' && it.error?.stage === 'parse'))
}

// ── upload orchestration (pure except the injected async client) ──────────────

/**
 * Upload a single confirmable item via the injected client. Returns the next
 * item state (done or upload-error). Does NOT mutate; callers fold the result
 * into list state. The draft → request mapping reuses the engine's
 * draftToCreateRequest so the idempotency key (client_book_id) is identical to
 * a re-import — the backend dedupes, making retries safe.
 */
export async function uploadItem(item: ImportItem, client: LibraryLike): Promise<ImportItem> {
  if (item.draft == null) {
    return toUploadError(item, 'No draft to upload.')
  }
  try {
    const created = await client.create(draftToCreateRequest(item.draft))
    return toDone(item, created.id)
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return toUploadError(item, detail)
  }
}
