// Plain-text (.txt) parser. Pure: (filename, content, sizeBytes) -> ImportResult.
//
// Plain text has no embedded metadata, so the title is derived from the filename
// stem (mirrors iOS, which falls back to the filename when an EPUB carries no
// title). Body is the decoded text; we keep a bounded preview.

import {
  clampLength,
  deriveClientBookId,
  fileStem,
  normalizeWhitespace,
  TITLE_MAX,
} from './clientBookId'
import type { ImportResult } from './types'
import { importError, importSuccess } from './types'

/** Max characters kept in `rawTextPreview` (keeps drafts small). */
export const PREVIEW_CHARS = 2000

/** Build a bounded, whitespace-normalized preview of the body. */
export function buildPreview(content: string, limit = PREVIEW_CHARS): string {
  const normalized = normalizeWhitespace(content)
  return normalized.length <= limit ? normalized : normalized.slice(0, limit)
}

/**
 * Parse a plain-text file into a BookImportDraft.
 *
 * Title = filename stem (clamped). Empty/whitespace-only content -> typed
 * `empty_content` error (no point importing a blank book).
 */
export function parseTxt(args: {
  filename: string
  content: string
  sizeBytes: number
}): ImportResult {
  const body = args.content
  if (normalizeWhitespace(body).length === 0) {
    return importError('empty_content', 'The text file is empty.')
  }

  const stem = normalizeWhitespace(fileStem(args.filename))
  const title = clampLength(stem.length > 0 ? stem : 'Untitled', TITLE_MAX)

  return importSuccess({
    title,
    format: 'txt',
    sizeBytes: args.sizeBytes,
    clientBookId: deriveClientBookId({
      filename: args.filename,
      sizeBytes: args.sizeBytes,
      format: 'txt',
    }),
    rawTextPreview: buildPreview(body),
  })
}
