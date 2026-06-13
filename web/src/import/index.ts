// Local book-import engine — public barrel.
//
// Mirrors the iOS import path (EPUB/TXT/MD file -> parse locally -> book
// metadata -> create request). Framework-free and pure except for
// `epubjsExtractor`, which is the single epubjs binding behind the
// EpubMetadataExtractor seam.

// Types & result helpers
export type {
  BookImportDraft,
  ImportFormat,
  ImportResult,
  ImportSuccess,
  ImportError,
  ImportErrorCode,
} from './types'
export { importError, importSuccess } from './types'

// Format detection
export { detectFormat } from './detectFormat'
export type { DetectResult } from './detectFormat'

// Parsers (pure)
export { parseTxt, buildPreview, PREVIEW_CHARS } from './parseTxt'
export { parseMarkdown, extractMarkdownTitle } from './parseMarkdown'

// EPUB: pure mapper + injectable seam + production binding
export { parseEpub, epubMetadataToDraft } from './parseEpub'
export type { RawEpubMetadata, EpubMetadataExtractor } from './parseEpub'
export { epubjsExtractor } from './epubjsExtractor'

// Create-request mapping
export { draftToCreateRequest } from './draftToCreateRequest'

// Idempotency / filename helpers
export {
  deriveClientBookId,
  fileStem,
  fileExtension,
  clampLength,
  normalizeWhitespace,
  CLIENT_BOOK_ID_MAX,
  TITLE_MAX,
  AUTHOR_MAX,
  LANGUAGE_MAX,
} from './clientBookId'
