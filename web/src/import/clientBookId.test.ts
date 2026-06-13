import { describe, expect, it } from 'vitest'
import {
  clampLength,
  CLIENT_BOOK_ID_MAX,
  deriveClientBookId,
  fileExtension,
  fileStem,
  normalizeWhitespace,
} from './clientBookId'

describe('fileStem', () => {
  it('strips directory and extension', () => {
    expect(fileStem('path/to/My Book.epub')).toBe('My Book')
    expect(fileStem('C:\\books\\Foo.txt')).toBe('Foo')
  })
  it('returns the name when there is no extension', () => {
    expect(fileStem('README')).toBe('README')
  })
  it('keeps dotfiles intact (leading dot is not an extension)', () => {
    expect(fileStem('.gitignore')).toBe('.gitignore')
  })
  it('strips only the last extension', () => {
    expect(fileStem('notes.tar.gz')).toBe('notes.tar')
  })
})

describe('fileExtension', () => {
  it('lowercases the extension without the dot', () => {
    expect(fileExtension('Book.EPUB')).toBe('epub')
    expect(fileExtension('a/b/c.Md')).toBe('md')
  })
  it('returns empty for no extension, dotfiles, or trailing dot', () => {
    expect(fileExtension('README')).toBe('')
    expect(fileExtension('.env')).toBe('')
    expect(fileExtension('weird.')).toBe('')
  })
})

describe('normalizeWhitespace', () => {
  it('collapses runs and trims', () => {
    expect(normalizeWhitespace('  a\n\t b   c ')).toBe('a b c')
  })
})

describe('clampLength', () => {
  it('trims then returns short strings unchanged', () => {
    expect(clampLength('  hi  ', 10)).toBe('hi')
  })
  it('clamps to max code units', () => {
    expect(clampLength('abcdef', 3)).toBe('abc')
  })
})

describe('deriveClientBookId', () => {
  it('is deterministic for identical identity', () => {
    const a = deriveClientBookId({ filename: 'My Book.epub', sizeBytes: 1234, format: 'epub' })
    const b = deriveClientBookId({ filename: 'My Book.epub', sizeBytes: 1234, format: 'epub' })
    expect(a).toBe(b)
    expect(a).toBe('import-my-book-1234-epub')
  })
  it('differs when size differs', () => {
    const a = deriveClientBookId({ filename: 'x.txt', sizeBytes: 1, format: 'txt' })
    const b = deriveClientBookId({ filename: 'x.txt', sizeBytes: 2, format: 'txt' })
    expect(a).not.toBe(b)
  })
  it('sanitizes non-ascii / unsafe chars', () => {
    const id = deriveClientBookId({ filename: 'Foo Bar! @#.epub', sizeBytes: 9, format: 'epub' })
    expect(id).toMatch(/^[a-z0-9._-]+$/)
    expect(id).toBe('import-foo-bar-9-epub')
  })
  it('falls back to size+format when the stem sanitizes to empty', () => {
    const id = deriveClientBookId({ filename: '中文書.epub', sizeBytes: 5, format: 'epub' })
    expect(id).toBe('import-5-epub')
  })
  it('clamps to CLIENT_BOOK_ID_MAX', () => {
    const id = deriveClientBookId({ filename: 'a'.repeat(500) + '.txt', sizeBytes: 1, format: 'txt' })
    expect(id.length).toBeLessThanOrEqual(CLIENT_BOOK_ID_MAX)
  })
})
