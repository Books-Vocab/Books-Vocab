import { describe, expect, it } from 'vitest'
import { detectFormat } from './detectFormat'

describe('detectFormat — by extension', () => {
  it('maps epub/txt/md and aliases', () => {
    expect(detectFormat('a.epub')).toEqual({ ok: true, format: 'epub' })
    expect(detectFormat('a.txt')).toEqual({ ok: true, format: 'txt' })
    expect(detectFormat('a.md')).toEqual({ ok: true, format: 'md' })
    expect(detectFormat('a.markdown')).toEqual({ ok: true, format: 'md' })
    expect(detectFormat('a.text')).toEqual({ ok: true, format: 'txt' })
  })
  it('is case-insensitive', () => {
    expect(detectFormat('Book.EPUB')).toEqual({ ok: true, format: 'epub' })
  })
})

describe('detectFormat — by mime when extension is unknown/missing', () => {
  it('falls back to mime', () => {
    expect(detectFormat('noext', 'application/epub+zip')).toEqual({ ok: true, format: 'epub' })
    expect(detectFormat('noext', 'text/markdown')).toEqual({ ok: true, format: 'md' })
    expect(detectFormat('noext', 'text/plain')).toEqual({ ok: true, format: 'txt' })
  })
  it('strips mime parameters and is case-insensitive', () => {
    expect(detectFormat('noext', 'text/plain; charset=utf-8')).toEqual({ ok: true, format: 'txt' })
    expect(detectFormat('noext', 'TEXT/MARKDOWN')).toEqual({ ok: true, format: 'md' })
  })
  it('prefers extension over mime', () => {
    expect(detectFormat('a.txt', 'application/epub+zip')).toEqual({ ok: true, format: 'txt' })
  })
})

describe('detectFormat — pdf is a typed unsupported error (deferred)', () => {
  it('rejects pdf by extension', () => {
    const r = detectFormat('book.pdf')
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.code).toBe('unsupported_format')
      expect(r.message).toMatch(/pdf/i)
      expect(r.message).toMatch(/not yet supported/i)
    }
  })
  it('rejects pdf by mime even with no/odd extension', () => {
    const r = detectFormat('book', 'application/pdf')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.code).toBe('unsupported_format')
  })
})

describe('detectFormat — other unsupported', () => {
  it('rejects unknown extensions', () => {
    const r = detectFormat('archive.zip')
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.code).toBe('unsupported_format')
      expect(r.message).toContain('.zip')
    }
  })
  it('rejects files with no extension and no usable mime', () => {
    const r = detectFormat('mystery')
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.code).toBe('unsupported_format')
      expect(r.message).toMatch(/missing or unrecognized/i)
    }
  })
})
