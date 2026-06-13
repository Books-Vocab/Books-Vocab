// Local file-import engine types.
//
// Mirrors the iOS import path: iOS imports EPUB/TXT/MD via Files / share-sheet,
// extracts metadata (title / author / cover / format / identifier — see
// ios/.../Services/BookMetadataExtracting.swift), then creates a library book
// metadata row. The web equivalent is: browser File -> parse locally ->
// BookImportDraft -> LibraryClient.create (POST /api/library/books).
//
// The engine is framework-free and pure: parsers take (filename, content) or an
// ArrayBuffer + an injectable metadata extractor, and never touch React / DOM
// globals beyond what a browser File already gives the caller.

/**
 * Formats this engine can parse locally today.
 *
 * PDF is intentionally NOT here: it needs pdf.js to extract text/metadata and
 * is deferred. `detectFormat` reports a typed `unsupported_format` error for
 * pdf rather than faking a draft. The backend `format` column also allows
 * `pdf`, but this engine does not produce it yet.
 */
export type ImportFormat = 'epub' | 'txt' | 'md'

/**
 * Normalized, parsed book metadata ready to become a create request.
 *
 * `clientBookId` is the idempotency key (maps to BookCreateRequest.client_book_id).
 * It is derived deterministically from stable file identity so re-importing the
 * same file is a no-op on the backend.
 */
export interface BookImportDraft {
  /** Display title (EPUB OPF title / first markdown heading / filename stem). */
  title: string
  /** Author / creator if known (EPUB OPF creator). Undefined for plain text. */
  author?: string
  /** Parsed source format. */
  format: ImportFormat
  /** EPUB OPF identifier (ISBN / UUID / urn) if present. */
  identifier?: string
  /** BCP-47-ish language tag if the source declares one (EPUB OPF language). */
  language?: string
  /** Cover image as a data: URL (EPUB cover), if extracted. */
  coverDataUrl?: string
  /** Original file size in bytes. */
  sizeBytes: number
  /** Idempotency key for BookCreateRequest.client_book_id. */
  clientBookId: string
  /** First slice of decoded plain text (for txt/md previews / debugging). */
  rawTextPreview?: string
}

/** Typed error codes the engine can surface. */
export type ImportErrorCode =
  /** Extension / mime is a format we deliberately do not parse yet (e.g. pdf). */
  | 'unsupported_format'
  /** File content could not be decoded / parsed into a valid draft. */
  | 'parse_failed'
  /** Required metadata (a non-empty title) could not be derived. */
  | 'empty_content'

/** A structured, typed import failure. */
export interface ImportError {
  ok: false
  code: ImportErrorCode
  /** Human-readable detail (English; UI layer maps to L10n separately). */
  message: string
}

/** A successful parse carrying the normalized draft. */
export interface ImportSuccess {
  ok: true
  draft: BookImportDraft
}

/** Discriminated union result of a parse / detect operation. */
export type ImportResult = ImportSuccess | ImportError

/** Construct a typed failure result. */
export function importError(code: ImportErrorCode, message: string): ImportError {
  return { ok: false, code, message }
}

/** Construct a success result. */
export function importSuccess(draft: BookImportDraft): ImportSuccess {
  return { ok: true, draft }
}
