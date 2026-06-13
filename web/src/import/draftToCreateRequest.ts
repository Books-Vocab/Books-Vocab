// BookImportDraft -> BookCreateRequest (POST /api/library/books body).
//
// This is the contract boundary with the API layer. The output type is the
// hand-mirrored BookCreateRequest from web/src/api/types.ts (SoT =
// backend/src/kg/api_models/library.py::BookCreateRequest). Pure mapping.
//
// Note: cover / identifier / rawTextPreview / sizeBytes are NOT part of
// BookCreateRequest — the backend metadata row has no cover/identifier columns
// (see BookMetadataResponse). They live on the draft for the UI / local use
// (e.g. rendering a cover thumbnail before/after create) and are intentionally
// dropped here. clientBookId becomes the idempotency key client_book_id.

import type { BookCreateRequest } from '../api/types'
import { clampLength, TITLE_MAX, AUTHOR_MAX, LANGUAGE_MAX } from './clientBookId'
import type { BookImportDraft } from './types'

/**
 * Map a parsed draft to the exact create-request object LibraryClient.create
 * expects. Only fields present on BookCreateRequest are emitted; optional fields
 * are included only when the draft has them (omitted, not null). String fields
 * are defensively re-clamped to the backend max_length bounds.
 */
export function draftToCreateRequest(draft: BookImportDraft): BookCreateRequest {
  const req: BookCreateRequest = {
    client_book_id: draft.clientBookId,
    title: clampLength(draft.title, TITLE_MAX),
    format: draft.format,
  }
  if (draft.author != null) req.author = clampLength(draft.author, AUTHOR_MAX)
  if (draft.language != null) req.language = clampLength(draft.language, LANGUAGE_MAX)
  return req
}
