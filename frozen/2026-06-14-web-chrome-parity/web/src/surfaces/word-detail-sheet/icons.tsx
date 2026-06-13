import { makeGlyph } from '../../shared/glyph'

/**
 * SF-Symbols-style glyph for WordDetailSheet — 24×24 grid、stroke:currentColor、純裝飾。
 *
 * catalog 的 Word Detail · Sheet 兩個 scene（Minimal / Rich entry）在 snapshot 下
 * 皆停在 WordDetailSheet 的 else-branch（`.task` 內 presenter 尚未算完）→ 渲染
 * 「載入中」placeholder：VocabStateMessageCard(doc.text /accent · 載入中 · ProgressView)。
 * 故唯一需要的 glyph 是 `doc.text`（與 vocab-linked-card icons.tsx 逐字一致）。
 */

/** SF `doc.text` — 「載入中」前綴：文件 + 折角 + 兩條文字線（iconSmall=symbol 12 medium /accent）。 */
export const DocTextIcon = makeGlyph(
  '<path d="M6.5 4.5h6l5 5v10a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1z"/><path d="M12.5 4.5v5h5"/><path d="M8.5 13h6"/><path d="M8.5 16h6"/>',
  { size: 18, strokeWidth: 1.5 },
)
