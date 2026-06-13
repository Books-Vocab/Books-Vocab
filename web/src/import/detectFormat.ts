// Format detection from filename extension + optional MIME type.
//
// Pure: no File / DOM dependency — callers pass the bits a browser File already
// exposes (`name`, `type`). PDF is deliberately rejected as unsupported (needs
// pdf.js; deferred) rather than faked.

import { fileExtension } from './clientBookId'
import type { ImportFormat } from './types'

/** Recognized supported extensions -> engine format. */
const EXT_TO_FORMAT: Record<string, ImportFormat> = {
  epub: 'epub',
  txt: 'txt',
  md: 'md',
  markdown: 'md',
  text: 'txt',
}

/** MIME types we can map when the extension is missing / ambiguous. */
const MIME_TO_FORMAT: Record<string, ImportFormat> = {
  'application/epub+zip': 'epub',
  'text/plain': 'txt',
  'text/markdown': 'md',
  'text/x-markdown': 'md',
}

/** Extensions we recognize but deliberately do not support yet. */
const DEFERRED_EXT = new Set(['pdf'])
const DEFERRED_MIME = new Set(['application/pdf'])

/** Lightweight discriminated result for format detection only. */
export type DetectResult =
  | { ok: true; format: ImportFormat }
  | { ok: false; code: 'unsupported_format'; message: string }

/**
 * Detect the import format from a filename + optional MIME.
 *
 * Resolution order: extension first (most reliable for local files), then MIME.
 * PDF (by ext or MIME) is reported as a clear, non-faked unsupported error.
 * Anything else unknown is also `unsupported_format`.
 */
export function detectFormat(filename: string, mime?: string | null): DetectResult {
  const ext = fileExtension(filename)
  const normalizedMime = (mime ?? '').split(';')[0].trim().toLowerCase()

  if (DEFERRED_EXT.has(ext) || DEFERRED_MIME.has(normalizedMime)) {
    return {
      ok: false,
      code: 'unsupported_format',
      message: 'PDF import is not yet supported (requires pdf.js — deferred).',
    }
  }

  const byExt = EXT_TO_FORMAT[ext]
  if (byExt) return { ok: true, format: byExt }

  const byMime = MIME_TO_FORMAT[normalizedMime]
  if (byMime) return { ok: true, format: byMime }

  return {
    ok: false,
    code: 'unsupported_format',
    message: ext
      ? `Unsupported file format ".${ext}" (only EPUB, TXT, MD).`
      : 'Unsupported file: missing or unrecognized extension/type (only EPUB, TXT, MD).',
  }
}
