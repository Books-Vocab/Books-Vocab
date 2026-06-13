import { describe, expect, it } from 'vitest'
import { extractMarkdownTitle, parseMarkdown } from './parseMarkdown'

describe('extractMarkdownTitle', () => {
  it('extracts an ATX h1', () => {
    expect(extractMarkdownTitle('# The Title\n\nbody')).toBe('The Title')
  })
  it('extracts deeper ATX headings when they come first', () => {
    expect(extractMarkdownTitle('### Sub heading\nbody')).toBe('Sub heading')
  })
  it('strips trailing closing hashes', () => {
    expect(extractMarkdownTitle('## Closed ##\nbody')).toBe('Closed')
  })
  it('skips leading blank lines', () => {
    expect(extractMarkdownTitle('\n\n   \n# Real Title')).toBe('Real Title')
  })
  it('extracts a Setext (===) heading', () => {
    expect(extractMarkdownTitle('My Book\n=====\n\nbody')).toBe('My Book')
  })
  it('extracts a Setext (---) heading', () => {
    expect(extractMarkdownTitle('My Book\n-----\nbody')).toBe('My Book')
  })
  it('ignores headings that come after body text', () => {
    expect(extractMarkdownTitle('intro paragraph\n\n# Late Heading')).toBeUndefined()
  })
  it('returns undefined when there is no heading', () => {
    expect(extractMarkdownTitle('just plain text\nmore text')).toBeUndefined()
  })
  it('skips YAML front matter and does not treat its --- as a Setext underline', () => {
    const md = '---\ntitle: meta\n---\n# Doc Heading\nbody'
    expect(extractMarkdownTitle(md)).toBe('Doc Heading')
  })
  it('treats an unterminated front matter block as plain content', () => {
    expect(extractMarkdownTitle('---\nstuff\n# Not reached as heading')).toBeUndefined()
  })
  it('normalizes whitespace inside a heading', () => {
    expect(extractMarkdownTitle('#   spaced   words  \nbody')).toBe('spaced words')
  })
})

describe('parseMarkdown', () => {
  it('prefers the heading title over the filename', () => {
    const r = parseMarkdown({ filename: 'chapter-01.md', content: '# Real Title\n\nbody', sizeBytes: 20 })
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.draft.title).toBe('Real Title')
      expect(r.draft.format).toBe('md')
      expect(r.draft.clientBookId).toBe('import-chapter-01-20-md')
      expect(r.draft.rawTextPreview).toContain('Real Title')
    }
  })
  it('falls back to the filename stem when there is no heading', () => {
    const r = parseMarkdown({ filename: 'My Doc.md', content: 'plain body', sizeBytes: 10 })
    expect(r.ok && r.draft.title).toBe('My Doc')
  })
  it('returns empty_content for blank content', () => {
    const r = parseMarkdown({ filename: 'a.md', content: '\n\n  ', sizeBytes: 3 })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.code).toBe('empty_content')
  })
})
