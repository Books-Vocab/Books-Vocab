import { makeGlyph } from '../../shared/glyph'

/**
 * SF `chevron.up` — 摺頁收合手柄。iOS：`Image(systemName: "chevron.up")`
 * `.font(iconTiny.weight(.semibold))`（iconTiny=symbol 10pt）。glyph 24-grid、
 * stroke:currentColor、aria-hidden 純裝飾；semibold 由 strokeWidth 表現。
 */
export const ChevronUpIcon = makeGlyph('<path d="M5 15l7-7 7 7"/>')
