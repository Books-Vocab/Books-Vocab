// Deterministic idempotency-key + filename helpers for the import engine.
//
// BookCreateRequest.client_book_id is the idempotency key (backend dedupes on
// it). We derive it deterministically from stable file identity (name + size +
// format) so re-importing the same file produces the same key and the backend
// create is a no-op. This is a content-adjacent fingerprint, NOT a content hash
// (we avoid hashing whole EPUB binaries) — name+size collisions across genuinely
// different files are acceptable for an idempotency key and match the iOS habit
// of keying on file identity.

/** Backend cap: BookCreateRequest.client_book_id has max_length=128. */
export const CLIENT_BOOK_ID_MAX = 128

/** Backend cap: BookCreateRequest.title has max_length=200. */
export const TITLE_MAX = 200

/** Backend cap: BookCreateRequest.author has max_length=200. */
export const AUTHOR_MAX = 200

/** Backend cap: BookCreateRequest.language has max_length=10. */
export const LANGUAGE_MAX = 10

/**
 * Strip the file extension and directory, returning the bare stem.
 * `path/My Book.epub` -> `My Book`; `notes.tar.gz` -> `notes.tar` (last ext only).
 */
export function fileStem(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? filename
  const dot = base.lastIndexOf('.')
  if (dot <= 0) return base // no extension, or dotfile like `.gitignore`
  return base.slice(0, dot)
}

/** Lowercased extension without the dot, or '' if none. `Book.EPUB` -> `epub`. */
export function fileExtension(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? filename
  const dot = base.lastIndexOf('.')
  if (dot <= 0 || dot === base.length - 1) return ''
  return base.slice(dot + 1).toLowerCase()
}

/** Collapse runs of whitespace and trim. */
export function normalizeWhitespace(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

/**
 * Clamp a string to a max length (code units). Returns trimmed-then-clamped.
 * Used to keep title/author within the backend's pydantic max_length bounds.
 */
export function clampLength(s: string, max: number): string {
  const trimmed = s.trim()
  return trimmed.length <= max ? trimmed : trimmed.slice(0, max)
}

/**
 * Sanitize a candidate id to the charset backends/idempotency keys are happy
 * with: keep ASCII alnum, dot, underscore, hyphen; replace any other run with a
 * single hyphen; collapse/trim hyphens; lowercase.
 */
function sanitizeIdPart(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

/**
 * Derive the deterministic idempotency key for a file.
 *
 * Shape: `import-<stem>-<size>-<format>`, sanitized and clamped to
 * CLIENT_BOOK_ID_MAX. Deterministic for identical (name, size, format), which is
 * what idempotent re-import needs. Always non-empty (falls back to size+format
 * when the stem sanitizes to empty, e.g. a CJK-only filename).
 */
export function deriveClientBookId(args: {
  filename: string
  sizeBytes: number
  format: string
}): string {
  const stem = sanitizeIdPart(fileStem(args.filename))
  const tail = `${args.sizeBytes}-${sanitizeIdPart(args.format)}`
  const core = stem ? `${stem}-${tail}` : tail
  const id = `import-${core}`
  return id.length <= CLIENT_BOOK_ID_MAX ? id : id.slice(0, CLIENT_BOOK_ID_MAX)
}
