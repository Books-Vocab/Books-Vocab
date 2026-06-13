// Pure transformers: library seed → API-response shapes.

import type { BookMetadataResponse } from '../../api/types'
import type { BookSeed } from '../seeds/library.seed'

export function toBookMetadataResponse(b: BookSeed, nowIso: string): BookMetadataResponse {
  return {
    id: b.id,
    client_book_id: b.clientBookId,
    title: b.title,
    author: b.author,
    language: b.language,
    format: b.format,
    notebook_id: b.notebookId,
    is_deleted: false,
    updated_at: nowIso,
    locator: b.locator,
    progression: b.progression,
    position_updated_at: b.positionUpdatedAt,
  }
}

export function toBookMetadataResponses(seeds: BookSeed[], nowIso: string): BookMetadataResponse[] {
  return seeds.map((b) => toBookMetadataResponse(b, nowIso))
}
