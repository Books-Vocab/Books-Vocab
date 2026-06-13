// Markdown (.md) parser. Pure: (filename, content, sizeBytes) -> ImportResult.
//
// Title preference: the first ATX/Setext heading in the document, else the
// filename stem. The body preview is the plain text with markdown markers
// stripped enough to be readable (we are not rendering — just deriving a
// title + preview for book metadata).

import {
  clampLength,
  deriveClientBookId,
  fileStem,
  normalizeWhitespace,
  TITLE_MAX,
} from './clientBookId'
import { buildPreview } from './parseTxt'
import type { ImportResult } from './types'
import { importError, importSuccess } from './types'

/**
 * Extract the first markdown heading title, if any.
 *
 * Supports:
 *  - ATX: a line starting with 1-6 `#` then space (trailing `#` stripped).
 *  - Setext: a non-blank line immediately followed by a line of `===`/`---`.
 *
 * Returns the trimmed heading text, or undefined when no heading is found.
 * Skips a leading YAML front-matter block (`---` … `---`) so its delimiter is
 * not mistaken for a Setext underline.
 */
export function extractMarkdownTitle(content: string): string | undefined {
  const lines = stripFrontMatter(content.split(/\r?\n/))

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    if (trimmed.length === 0) continue

    // ATX heading: # … ######
    const atx = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(trimmed)
    if (atx) {
      const text = normalizeWhitespace(atx[2])
      if (text.length > 0) return text
      continue
    }

    // Setext heading: text line followed by === or --- underline.
    const next = lines[i + 1]?.trim() ?? ''
    if (/^=+$/.test(next) || /^-+$/.test(next)) {
      const text = normalizeWhitespace(trimmed)
      if (text.length > 0) return text
    }

    // First non-blank, non-heading content line: stop looking — a title that
    // comes after body text is not a document title.
    break
  }

  return undefined
}

/** Drop a leading `---`-delimited YAML front-matter block, if present. */
function stripFrontMatter(lines: string[]): string[] {
  if (lines.length === 0 || lines[0].trim() !== '---') return lines
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === '---') return lines.slice(i + 1)
  }
  return lines // unterminated front matter: treat as plain content
}

/**
 * Parse a markdown file into a BookImportDraft.
 *
 * Title = first heading, else filename stem (clamped). Empty content -> typed
 * `empty_content` error.
 */
export function parseMarkdown(args: {
  filename: string
  content: string
  sizeBytes: number
}): ImportResult {
  const body = args.content
  if (normalizeWhitespace(body).length === 0) {
    return importError('empty_content', 'The markdown file is empty.')
  }

  const heading = extractMarkdownTitle(body)
  const stem = normalizeWhitespace(fileStem(args.filename))
  const rawTitle = heading ?? (stem.length > 0 ? stem : 'Untitled')
  const title = clampLength(rawTitle, TITLE_MAX)

  return importSuccess({
    title,
    format: 'md',
    sizeBytes: args.sizeBytes,
    clientBookId: deriveClientBookId({
      filename: args.filename,
      sizeBytes: args.sizeBytes,
      format: 'md',
    }),
    rawTextPreview: buildPreview(body),
  })
}
