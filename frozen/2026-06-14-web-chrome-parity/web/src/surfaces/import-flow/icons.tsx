import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyphs local to the import-flow surface — 24×24 grid,
 * stroke currentColor, decorative. Mirror the SF symbols the iOS import path
 * uses (doc / xmark / arrow.down.doc / checkmark / exclamationmark).
 */

/** SF `doc.text` — a parsed book/document row glyph. */
export const DocTextIcon = makeGlyph(
  '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20V4a.5.5 0 0 1 .5-.5z"/>' +
    '<path d="M14 3.5V7.5h4"/>' +
    '<path d="M9.5 12.5h6M9.5 15.5h6"/>',
)

/** SF `arrow.down.doc` — the drop / pick-files zone hero glyph. */
export const ArrowDownDocIcon = makeGlyph(
  '<path d="M6.5 9.5V5a.5.5 0 0 1 .5-.5h7l3.5 3.5V19a.5.5 0 0 1-.5.5h-3"/>' +
    '<path d="M13.5 4.5V8.5h3.5"/>' +
    '<path d="M5 14v5.5h4.5"/>' +
    '<path d="M7.25 17.25 5 19.5 2.75 17.25"/>',
)

/** SF `xmark` — remove an item from the list. */
export const XmarkIcon = makeGlyph('<path d="M6 6l12 12M18 6 6 18"/>')

/** SF `checkmark.circle` — upload succeeded (done). */
export const CheckmarkCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.6-5"/>',
)

/** SF `exclamationmark.circle` — per-item error. */
export const ExclamationmarkCircleIcon = makeGlyph(
  '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.8v4.6"/><path d="M12 15.6h.01"/>',
)

/** SF `arrow.clockwise` — retry a failed upload. */
export const ArrowClockwiseIcon = makeGlyph(
  '<path d="M19 12a7 7 0 1 1-2.05-4.95"/><path d="M19 4.5V8h-3.5"/>',
)
