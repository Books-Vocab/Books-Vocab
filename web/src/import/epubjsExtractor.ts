// Production EpubMetadataExtractor bound to epubjs.
//
// This is the ONLY module in the import engine that imports epubjs, so the pure
// parsers/mappers (and their unit tests) stay framework-free. It loads the OPF
// packaging metadata and resolves a cover blob URL -> data: URL.
//
// epubjs is a browser-oriented library (Book.coverUrl returns a blob: URL via
// URL.createObjectURL); this extractor therefore runs in the browser, not node.
// Its pure output (RawEpubMetadata) is what the unit-tested mapper consumes.

import ePub from 'epubjs'
import type { EpubMetadataExtractor, RawEpubMetadata } from './parseEpub'

/**
 * Resolve epubjs's cover URL (a blob: URL) into a self-contained data: URL so
 * the draft can carry the cover without holding a live object URL. Returns
 * undefined when the EPUB has no cover or fetching fails.
 */
async function resolveCoverDataUrl(coverUrl: string | null): Promise<string | undefined> {
  if (!coverUrl) return undefined
  try {
    const resp = await fetch(coverUrl)
    const blob = await resp.blob()
    return await blobToDataUrl(blob)
  } catch {
    return undefined
  } finally {
    if (coverUrl.startsWith('blob:')) URL.revokeObjectURL(coverUrl)
  }
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error('FileReader failed'))
    reader.onload = () => resolve(String(reader.result))
    reader.readAsDataURL(blob)
  })
}

/**
 * The production extractor. Opens the ArrayBuffer with epubjs, awaits packaging,
 * and maps OPF metadata + cover into RawEpubMetadata. Always destroys the Book
 * to release resources.
 */
export const epubjsExtractor: EpubMetadataExtractor = {
  async extract(data: ArrayBuffer): Promise<RawEpubMetadata> {
    const book = ePub(data)
    try {
      await book.opened
      const meta = await book.loaded.metadata
      const coverUrl = await book.coverUrl()
      const coverDataUrl = await resolveCoverDataUrl(coverUrl)
      return {
        title: meta?.title ?? null,
        creator: meta?.creator ?? null,
        identifier: meta?.identifier ?? null,
        language: meta?.language ?? null,
        coverDataUrl: coverDataUrl ?? null,
      }
    } finally {
      book.destroy()
    }
  },
}
