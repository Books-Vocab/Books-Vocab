// EPUB parser.
//
// Two layers, deliberately separated so the pure mapping is unit-testable
// without a real EPUB binary or epubjs:
//
//  1. `EpubMetadataExtractor` — a thin injectable seam: ArrayBuffer -> raw OPF
//     metadata (+ optional cover data URL). Production binds it to epubjs
//     (`epubjsExtractor`); tests inject a fake.
//  2. `epubMetadataToDraft` — PURE: (raw metadata, filename, sizeBytes) ->
//     BookImportDraft. Mirrors iOS BookMetadataExtracting (title / author /
//     cover) plus OPF identifier + language. Fully testable in node.

import {
  AUTHOR_MAX,
  clampLength,
  deriveClientBookId,
  fileStem,
  LANGUAGE_MAX,
  normalizeWhitespace,
  TITLE_MAX,
} from './clientBookId'
import type { BookImportDraft, ImportResult } from './types'
import { importError, importSuccess } from './types'

/**
 * Raw EPUB OPF metadata, shaped after epubjs `PackagingMetadataObject`
 * (title / creator / identifier / language) plus an optional extracted cover.
 * All fields optional/best-effort: malformed EPUBs may omit any of them.
 */
export interface RawEpubMetadata {
  title?: string | null
  /** OPF `dc:creator` — maps to BookImportDraft.author. */
  creator?: string | null
  /** OPF `dc:identifier` — ISBN / UUID / urn. */
  identifier?: string | null
  /** OPF `dc:language`. */
  language?: string | null
  /** Cover image as a data: URL, if the extractor resolved one. */
  coverDataUrl?: string | null
}

/** Injectable seam: ArrayBuffer -> raw OPF metadata. */
export interface EpubMetadataExtractor {
  extract(data: ArrayBuffer): Promise<RawEpubMetadata>
}

/** Internal: trim + drop empty/whitespace-only -> undefined. */
function clean(value: string | null | undefined): string | undefined {
  if (value == null) return undefined
  const t = normalizeWhitespace(value)
  return t.length > 0 ? t : undefined
}

/**
 * PURE mapping: raw OPF metadata -> BookImportDraft.
 *
 * Title preference: OPF title, else filename stem, else 'Untitled'. Author from
 * OPF creator. Identifier / language / cover passed through when present. All
 * string fields clamped to backend pydantic max_length bounds. No I/O — fully
 * unit-testable.
 */
export function epubMetadataToDraft(args: {
  meta: RawEpubMetadata
  filename: string
  sizeBytes: number
}): BookImportDraft {
  const { meta, filename, sizeBytes } = args

  const opfTitle = clean(meta.title)
  const stem = clean(fileStem(filename))
  const title = clampLength(opfTitle ?? stem ?? 'Untitled', TITLE_MAX)

  const author = clean(meta.creator)
  const identifier = clean(meta.identifier)
  const language = clean(meta.language)
  const coverDataUrl = clean(meta.coverDataUrl)

  const draft: BookImportDraft = {
    title,
    format: 'epub',
    sizeBytes,
    clientBookId: deriveClientBookId({ filename, sizeBytes, format: 'epub' }),
  }
  if (author) draft.author = clampLength(author, AUTHOR_MAX)
  if (identifier) draft.identifier = identifier
  if (language) draft.language = clampLength(language, LANGUAGE_MAX)
  if (coverDataUrl) draft.coverDataUrl = coverDataUrl
  return draft
}

/**
 * Parse an EPUB ArrayBuffer into a BookImportDraft via the injected extractor.
 *
 * The extractor is the only seam that touches epubjs; everything else is pure.
 * Extraction failures (corrupt EPUB) become a typed `parse_failed` error rather
 * than throwing, so callers thread a single ImportResult union.
 */
export async function parseEpub(args: {
  filename: string
  data: ArrayBuffer
  sizeBytes: number
  extractor: EpubMetadataExtractor
}): Promise<ImportResult> {
  let meta: RawEpubMetadata
  try {
    meta = await args.extractor.extract(args.data)
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return importError('parse_failed', `Failed to read EPUB metadata: ${detail}`)
  }
  return importSuccess(
    epubMetadataToDraft({
      meta,
      filename: args.filename,
      sizeBytes: args.sizeBytes,
    }),
  )
}
