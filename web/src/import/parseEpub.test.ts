import { describe, expect, it } from 'vitest'
import {
  epubMetadataToDraft,
  parseEpub,
  type EpubMetadataExtractor,
  type RawEpubMetadata,
} from './parseEpub'

const FILENAME = 'A Tale.epub'
const SIZE = 4096

function draftFor(meta: RawEpubMetadata) {
  return epubMetadataToDraft({ meta, filename: FILENAME, sizeBytes: SIZE })
}

describe('epubMetadataToDraft (pure mapping)', () => {
  it('maps full OPF metadata into a draft', () => {
    const d = draftFor({
      title: 'A Tale of Two Cities',
      creator: 'Charles Dickens',
      identifier: 'urn:isbn:9780141439600',
      language: 'en',
      coverDataUrl: 'data:image/png;base64,AAAA',
    })
    expect(d).toEqual({
      title: 'A Tale of Two Cities',
      author: 'Charles Dickens',
      identifier: 'urn:isbn:9780141439600',
      language: 'en',
      coverDataUrl: 'data:image/png;base64,AAAA',
      format: 'epub',
      sizeBytes: SIZE,
      clientBookId: 'import-a-tale-4096-epub',
    })
  })

  it('falls back to the filename stem when OPF title is missing/blank', () => {
    expect(draftFor({ title: null }).title).toBe('A Tale')
    expect(draftFor({ title: '   ' }).title).toBe('A Tale')
  })

  it("uses 'Untitled' when both OPF title and filename stem are empty", () => {
    const d = epubMetadataToDraft({ meta: {}, filename: '   .epub', sizeBytes: SIZE })
    expect(d.title).toBe('Untitled')
  })

  it('omits author/identifier/language/cover when absent or blank', () => {
    const d = draftFor({ title: 'X', creator: '  ', identifier: null, language: undefined })
    expect(d.author).toBeUndefined()
    expect(d.identifier).toBeUndefined()
    expect(d.language).toBeUndefined()
    expect(d.coverDataUrl).toBeUndefined()
  })

  it('normalizes whitespace in title and author', () => {
    const d = draftFor({ title: '  Spaced   Title ', creator: 'Jane\tDoe' })
    expect(d.title).toBe('Spaced Title')
    expect(d.author).toBe('Jane Doe')
  })

  it('clamps title to 200 and author to 200 chars', () => {
    const d = draftFor({ title: 'T'.repeat(300), creator: 'A'.repeat(300) })
    expect(d.title.length).toBe(200)
    expect(d.author?.length).toBe(200)
  })

  it('clamps language to 10 chars', () => {
    const d = draftFor({ title: 'X', language: 'x'.repeat(20) })
    expect(d.language?.length).toBe(10)
  })
})

describe('parseEpub (with injected fake extractor)', () => {
  const fakeExtractor = (meta: RawEpubMetadata): EpubMetadataExtractor => ({
    extract: async () => meta,
  })

  it('produces a success draft from the extractor output', async () => {
    const r = await parseEpub({
      filename: FILENAME,
      data: new ArrayBuffer(8),
      sizeBytes: SIZE,
      extractor: fakeExtractor({ title: 'Book', creator: 'Author' }),
    })
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.draft.title).toBe('Book')
      expect(r.draft.author).toBe('Author')
      expect(r.draft.format).toBe('epub')
    }
  })

  it('returns a typed parse_failed error when the extractor throws', async () => {
    const r = await parseEpub({
      filename: FILENAME,
      data: new ArrayBuffer(8),
      sizeBytes: SIZE,
      extractor: { extract: async () => { throw new Error('corrupt zip') } },
    })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.code).toBe('parse_failed')
      expect(r.message).toContain('corrupt zip')
    }
  })
})
