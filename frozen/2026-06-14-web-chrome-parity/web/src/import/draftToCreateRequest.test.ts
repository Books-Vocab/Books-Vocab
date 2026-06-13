import { describe, expect, it } from 'vitest'
import type { BookCreateRequest } from '../api/types'
import { draftToCreateRequest } from './draftToCreateRequest'
import type { BookImportDraft } from './types'

const baseDraft: BookImportDraft = {
  title: 'A Tale of Two Cities',
  author: 'Charles Dickens',
  format: 'epub',
  identifier: 'urn:isbn:9780141439600',
  language: 'en',
  coverDataUrl: 'data:image/png;base64,AAAA',
  sizeBytes: 4096,
  clientBookId: 'import-a-tale-4096-epub',
  rawTextPreview: 'should be dropped',
}

describe('draftToCreateRequest', () => {
  it('maps to the exact BookCreateRequest shape (no extra fields)', () => {
    const req = draftToCreateRequest(baseDraft)
    // Exhaustive equality: proves NO draft-only fields leak (cover/identifier/
    // sizeBytes/rawTextPreview must be dropped).
    expect(req).toEqual({
      client_book_id: 'import-a-tale-4096-epub',
      title: 'A Tale of Two Cities',
      author: 'Charles Dickens',
      language: 'en',
      format: 'epub',
    })
    // Type-level assertion that the output IS a BookCreateRequest.
    const typed: BookCreateRequest = req
    expect(typed.client_book_id).toBe('import-a-tale-4096-epub')
  })

  it('uses clientBookId as the idempotency key client_book_id', () => {
    expect(draftToCreateRequest(baseDraft).client_book_id).toBe(baseDraft.clientBookId)
  })

  it('omits author/language when the draft lacks them', () => {
    const draft: BookImportDraft = {
      title: 'Plain',
      format: 'txt',
      sizeBytes: 10,
      clientBookId: 'import-plain-10-txt',
    }
    const req = draftToCreateRequest(draft)
    expect(req).toEqual({
      client_book_id: 'import-plain-10-txt',
      title: 'Plain',
      format: 'txt',
    })
    expect('author' in req).toBe(false)
    expect('language' in req).toBe(false)
  })

  it('carries format through for each parsed type', () => {
    for (const fmt of ['epub', 'txt', 'md'] as const) {
      const req = draftToCreateRequest({ ...baseDraft, format: fmt })
      expect(req.format).toBe(fmt)
    }
  })

  it('re-clamps over-long title/author/language to backend bounds', () => {
    const req = draftToCreateRequest({
      ...baseDraft,
      title: 'T'.repeat(300),
      author: 'A'.repeat(300),
      language: 'x'.repeat(20),
    })
    expect(req.title.length).toBe(200)
    expect(req.author?.length).toBe(200)
    expect(req.language?.length).toBe(10)
  })
})
