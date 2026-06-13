import { describe, expect, it } from 'vitest'
import { buildPreview, parseTxt, PREVIEW_CHARS } from './parseTxt'

describe('buildPreview', () => {
  it('normalizes whitespace', () => {
    expect(buildPreview('  hello\n\n  world  ')).toBe('hello world')
  })
  it('truncates to the limit', () => {
    expect(buildPreview('x'.repeat(50), 10)).toBe('x'.repeat(10))
  })
  it('defaults to PREVIEW_CHARS', () => {
    expect(buildPreview('y'.repeat(PREVIEW_CHARS + 100)).length).toBe(PREVIEW_CHARS)
  })
})

describe('parseTxt', () => {
  it('derives title from the filename stem and sets format txt', () => {
    const r = parseTxt({ filename: 'My Notes.txt', content: 'Some body text.', sizeBytes: 15 })
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.draft.title).toBe('My Notes')
      expect(r.draft.format).toBe('txt')
      expect(r.draft.sizeBytes).toBe(15)
      expect(r.draft.clientBookId).toBe('import-my-notes-15-txt')
      expect(r.draft.rawTextPreview).toBe('Some body text.')
      expect(r.draft.author).toBeUndefined()
    }
  })
  it('normalizes a whitespace-laden filename stem', () => {
    const r = parseTxt({ filename: '  spaced   name  .txt', content: 'hi', sizeBytes: 2 })
    expect(r.ok && r.draft.title).toBe('spaced name')
  })
  it('falls back to Untitled when the stem is empty after normalization', () => {
    const r = parseTxt({ filename: '   .txt', content: 'hi', sizeBytes: 2 })
    expect(r.ok && r.draft.title).toBe('Untitled')
  })
  it('returns empty_content for blank/whitespace-only content', () => {
    const r = parseTxt({ filename: 'a.txt', content: '   \n\t ', sizeBytes: 5 })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.code).toBe('empty_content')
  })
})
