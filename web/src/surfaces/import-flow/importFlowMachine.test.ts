import { describe, expect, it, vi } from 'vitest'
import type { BookImportDraft } from '../../import'
import type { BookCreateRequest, BookMetadataResponse } from '../../api/types'
import {
  allSettled,
  applyParseOutcome,
  confirmableCount,
  isConfirmable,
  removeItem,
  toDone,
  toParsing,
  toUploadError,
  toUploading,
  updateItem,
  uploadItem,
  type ImportItem,
  type LibraryLike,
  type ParseOutcome,
} from './importFlowMachine'

// ── fixtures ──────────────────────────────────────────────────────────────────

function pendingItem(over: Partial<ImportItem> = {}): ImportItem {
  return {
    id: 'pick-1',
    filename: 'My Book.epub',
    sizeBytes: 1024,
    status: 'pending',
    ...over,
  }
}

function draftFor(over: Partial<BookImportDraft> = {}): BookImportDraft {
  return {
    title: 'My Book',
    format: 'epub',
    sizeBytes: 1024,
    clientBookId: 'import-my-book-1024-epub',
    ...over,
  }
}

function bookResponse(over: Partial<BookMetadataResponse> = {}): BookMetadataResponse {
  return {
    id: 'book-server-1',
    client_book_id: 'import-my-book-1024-epub',
    title: 'My Book',
    author: null,
    language: null,
    format: 'epub',
    notebook_id: null,
    is_deleted: false,
    updated_at: null,
    locator: null,
    progression: null,
    position_updated_at: null,
    ...over,
  }
}

/** Mock LibraryClient capturing requests; resolves or rejects per config. */
function mockClient(
  behavior: { ok: true; book?: BookMetadataResponse } | { ok: false; error: Error },
): LibraryLike & { calls: BookCreateRequest[] } {
  const calls: BookCreateRequest[] = []
  return {
    calls,
    create: vi.fn(async (req: BookCreateRequest) => {
      calls.push(req)
      if (behavior.ok) return behavior.book ?? bookResponse()
      throw behavior.error
    }),
  }
}

// ── list helpers ────────────────────────────────────────────────────────────

describe('updateItem / removeItem', () => {
  it('patches only the matching id', () => {
    const items = [pendingItem({ id: 'a' }), pendingItem({ id: 'b' })]
    const next = updateItem(items, 'b', (it) => ({ ...it, status: 'ready' }))
    expect(next[0].status).toBe('pending')
    expect(next[1].status).toBe('ready')
  })

  it('is identity when no id matches', () => {
    const items = [pendingItem({ id: 'a' })]
    expect(updateItem(items, 'zzz', toParsing)).toEqual(items)
  })

  it('removes the matching id', () => {
    const items = [pendingItem({ id: 'a' }), pendingItem({ id: 'b' })]
    expect(removeItem(items, 'a').map((it) => it.id)).toEqual(['b'])
  })
})

// ── parse transitions ─────────────────────────────────────────────────────────

describe('parse status machine', () => {
  it('pending → parsing clears any stale error', () => {
    const item = pendingItem({ status: 'error', error: { stage: 'parse', message: 'x' } })
    const next = toParsing(item)
    expect(next.status).toBe('parsing')
    expect(next.error).toBeUndefined()
  })

  it('parsing → ready on a successful parse', () => {
    const item = toParsing(pendingItem())
    const outcome: ParseOutcome = { ok: true, draft: draftFor() }
    const next = applyParseOutcome(item, outcome)
    expect(next.status).toBe('ready')
    expect(next.draft).toEqual(draftFor())
    expect(next.error).toBeUndefined()
  })

  it('parsing → error on a failed parse (carries code)', () => {
    const item = toParsing(pendingItem())
    const outcome: ParseOutcome = { ok: false, code: 'unsupported_format', message: 'pdf' }
    const next = applyParseOutcome(item, outcome)
    expect(next.status).toBe('error')
    expect(next.error).toEqual({ stage: 'parse', code: 'unsupported_format', message: 'pdf' })
    expect(next.draft).toBeUndefined()
  })
})

// ── confirmable predicates ─────────────────────────────────────────────────────

describe('isConfirmable / confirmableCount', () => {
  it('ready with a draft is confirmable', () => {
    expect(isConfirmable(pendingItem({ status: 'ready', draft: draftFor() }))).toBe(true)
  })

  it('upload-error with a draft is confirmable (retryable)', () => {
    const item = pendingItem({ status: 'error', draft: draftFor(), error: { stage: 'upload', message: 'net' } })
    expect(isConfirmable(item)).toBe(true)
  })

  it('parse-error is NOT confirmable (no draft / not retryable here)', () => {
    const item = pendingItem({ status: 'error', error: { stage: 'parse', code: 'parse_failed', message: 'x' } })
    expect(isConfirmable(item)).toBe(false)
  })

  it('done / uploading / parsing are not confirmable', () => {
    expect(isConfirmable(pendingItem({ status: 'done', draft: draftFor(), createdBookId: 'b' }))).toBe(false)
    expect(isConfirmable(pendingItem({ status: 'uploading', draft: draftFor() }))).toBe(false)
    expect(isConfirmable(pendingItem({ status: 'parsing' }))).toBe(false)
  })

  it('counts only confirmable items', () => {
    const items = [
      pendingItem({ id: 'a', status: 'ready', draft: draftFor() }),
      pendingItem({ id: 'b', status: 'done', draft: draftFor(), createdBookId: 'x' }),
      pendingItem({ id: 'c', status: 'error', draft: draftFor(), error: { stage: 'upload', message: 'n' } }),
      pendingItem({ id: 'd', status: 'error', error: { stage: 'parse', code: 'empty_content', message: 'e' } }),
    ]
    expect(confirmableCount(items)).toBe(2)
  })
})

// ── upload orchestration (against mock client) ────────────────────────────────

describe('uploadItem', () => {
  it('ready → uploading → done, mapping the draft to a create request', async () => {
    const item = toUploading(pendingItem({ status: 'ready', draft: draftFor({ author: 'Ada', language: 'en' }) }))
    const client = mockClient({ ok: true, book: bookResponse({ id: 'book-42' }) })

    const next = await uploadItem(item, client)

    expect(client.calls).toHaveLength(1)
    expect(client.calls[0]).toEqual({
      client_book_id: 'import-my-book-1024-epub',
      title: 'My Book',
      format: 'epub',
      author: 'Ada',
      language: 'en',
    })
    expect(next.status).toBe('done')
    expect(next.createdBookId).toBe('book-42')
    expect(next.error).toBeUndefined()
  })

  it('upload failure → error(upload) preserving the draft for retry', async () => {
    const item = toUploading(pendingItem({ status: 'ready', draft: draftFor() }))
    const client = mockClient({ ok: false, error: new Error('network down') })

    const next = await uploadItem(item, client)

    expect(next.status).toBe('error')
    expect(next.error).toEqual({ stage: 'upload', message: 'network down' })
    expect(next.draft).toEqual(draftFor()) // draft kept → still confirmable
    expect(isConfirmable(next)).toBe(true)
  })

  it('retry: a failed upload re-uploads with the SAME idempotency key and succeeds', async () => {
    let item = toUploading(pendingItem({ status: 'ready', draft: draftFor() }))
    const failing = mockClient({ ok: false, error: new Error('500') })
    item = await uploadItem(item, failing)
    expect(item.status).toBe('error')

    // user hits retry → ready/error(upload) goes back through uploading
    const retried = toUploading(item)
    expect(retried.status).toBe('uploading')
    expect(retried.error).toBeUndefined()
    const ok = mockClient({ ok: true, book: bookResponse({ id: 'book-after-retry' }) })
    const done = await uploadItem(retried, ok)

    expect(failing.calls[0].client_book_id).toBe('import-my-book-1024-epub')
    expect(ok.calls[0].client_book_id).toBe('import-my-book-1024-epub') // identical key → backend dedupes
    expect(done.status).toBe('done')
    expect(done.createdBookId).toBe('book-after-retry')
  })

  it('guards against uploading an item with no draft', async () => {
    const item = pendingItem({ status: 'ready' }) // no draft
    const client = mockClient({ ok: true })
    const next = await uploadItem(item, client)
    expect(client.calls).toHaveLength(0)
    expect(next.status).toBe('error')
    expect(next.error?.stage).toBe('upload')
  })
})

// ── direct transition helpers ─────────────────────────────────────────────────

describe('toDone / toUploadError', () => {
  it('toDone records the created book id and clears error', () => {
    const item = toUploading(pendingItem({ status: 'ready', draft: draftFor(), error: { stage: 'upload', message: 'old' } }))
    const next = toDone(item, 'book-9')
    expect(next.status).toBe('done')
    expect(next.createdBookId).toBe('book-9')
    expect(next.error).toBeUndefined()
  })

  it('toUploadError preserves the draft', () => {
    const item = toUploading(pendingItem({ status: 'ready', draft: draftFor() }))
    const next = toUploadError(item, 'boom')
    expect(next.status).toBe('error')
    expect(next.draft).toEqual(draftFor())
  })
})

// ── settle predicate ───────────────────────────────────────────────────────────

describe('allSettled', () => {
  it('false for an empty list', () => {
    expect(allSettled([])).toBe(false)
  })

  it('true once every item is done or parse-error', () => {
    const items = [
      pendingItem({ id: 'a', status: 'done', draft: draftFor(), createdBookId: 'x' }),
      pendingItem({ id: 'b', status: 'error', error: { stage: 'parse', code: 'empty_content', message: 'e' } }),
    ]
    expect(allSettled(items)).toBe(true)
  })

  it('false while an upload error is still retryable', () => {
    const items = [
      pendingItem({ id: 'a', status: 'done', draft: draftFor(), createdBookId: 'x' }),
      pendingItem({ id: 'b', status: 'error', draft: draftFor(), error: { stage: 'upload', message: 'n' } }),
    ]
    expect(allSettled(items)).toBe(false)
  })
})
