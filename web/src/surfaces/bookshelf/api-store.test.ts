import { describe, expect, it } from 'vitest'
import {
  findBookByTitle,
  formatFromName,
  metadataFromEpub,
  titleFromName,
  toBookFixture,
} from './useBookshelfApiStore'
import type { BookMetadataResponse } from '../../api/types'

const BASE: BookMetadataResponse = {
  id: 'book-1',
  client_book_id: 'atomic-habits-epub',
  title: 'Atomic Habits',
  author: 'James Clear',
  language: 'en',
  format: 'epub',
  notebook_id: null,
  is_deleted: false,
  updated_at: '2026-06-11T00:00:00Z',
  locator: null,
  progression: 0.42,
  position_updated_at: null,
}

describe('formatFromName', () => {
  it('maps known extensions (case-insensitive) to BookFormat', () => {
    expect(formatFromName('book.epub')).toBe('epub')
    expect(formatFromName('paper.PDF')).toBe('pdf')
    expect(formatFromName('notes.TxT')).toBe('txt')
    expect(formatFromName('readme.md')).toBe('md')
  })

  it('falls back to epub for unknown / missing extensions', () => {
    expect(formatFromName('mystery.doc')).toBe('epub')
    expect(formatFromName('no-extension')).toBe('epub')
    expect(formatFromName('')).toBe('epub')
  })
})

describe('titleFromName', () => {
  it('strips the final extension', () => {
    expect(titleFromName('Atomic Habits.epub')).toBe('Atomic Habits')
    expect(titleFromName('My Notes.final.txt')).toBe('My Notes.final')
  })

  it('uses the whole name when there is no extension', () => {
    expect(titleFromName('Untitled')).toBe('Untitled')
  })

  it('falls back to the raw name when the stem is blank', () => {
    expect(titleFromName('.epub')).toBe('.epub')
  })
})

describe('toBookFixture', () => {
  it('maps API metadata to the presentation BookFixture shape', () => {
    expect(toBookFixture(BASE)).toEqual({
      title: 'Atomic Habits',
      author: 'James Clear',
      format: 'epub',
      dateLabel: '',
      progression: 0.42,
      needsICloudDownload: false,
    })
  })

  it('defaults null author/progression and normalizes unknown format to epub', () => {
    const result = toBookFixture({
      ...BASE,
      author: null,
      progression: null,
      format: 'azw3',
    })
    expect(result.author).toBe('')
    expect(result.progression).toBe(0)
    expect(result.format).toBe('epub')
  })

  it('normalizes uppercase format strings', () => {
    expect(toBookFixture({ ...BASE, format: 'PDF' }).format).toBe('pdf')
  })
})

describe('metadataFromEpub', () => {
  it('prefers EPUB package title/creator/language over the filename', () => {
    const meta = metadataFromEpub(
      { title: 'Atomic Habits', creator: 'James Clear', language: 'en' },
      'whatever.epub',
    )
    expect(meta).toEqual({
      title: 'Atomic Habits',
      author: 'James Clear',
      language: 'en',
      format: 'epub',
    })
  })

  it('falls back to the filename stem when the EPUB title is blank', () => {
    const meta = metadataFromEpub({ title: '   ', creator: '', language: '' }, 'My Book.epub')
    expect(meta.title).toBe('My Book')
    expect(meta.author).toBeNull()
    expect(meta.language).toBeNull()
  })

  it('handles a fully empty metadata object (corrupt / missing OPF)', () => {
    const meta = metadataFromEpub({}, 'Mystery.epub')
    expect(meta.title).toBe('Mystery')
    expect(meta.author).toBeNull()
    expect(meta.language).toBeNull()
    expect(meta.format).toBe('epub')
  })

  it('always reports epub format (only ever called for .epub files)', () => {
    expect(metadataFromEpub({ title: 'X', creator: 'Y', language: 'fr' }, 'x.EPUB').format).toBe(
      'epub',
    )
  })
})

describe('findBookByTitle', () => {
  const a: BookMetadataResponse = { ...BASE, id: 'a', title: 'Alpha' }
  const b: BookMetadataResponse = { ...BASE, id: 'b', title: 'Beta' }
  const deletedBeta: BookMetadataResponse = { ...BASE, id: 'b2', title: 'Beta', is_deleted: true }

  it('resolves a live book by title', () => {
    expect(findBookByTitle([a, b], 'Beta')?.id).toBe('b')
  })

  it('ignores soft-deleted rows', () => {
    expect(findBookByTitle([deletedBeta, b], 'Beta')?.id).toBe('b')
    expect(findBookByTitle([deletedBeta], 'Beta')).toBeUndefined()
  })

  it('returns undefined for an unknown title', () => {
    expect(findBookByTitle([a, b], 'Gamma')).toBeUndefined()
  })
})
