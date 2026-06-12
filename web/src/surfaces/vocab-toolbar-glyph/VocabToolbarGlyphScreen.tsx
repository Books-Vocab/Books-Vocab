import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_TOOLBAR_GLYPH_FIXTURES } from './fixtures'
import { SyncIcon } from './icons'
import './vocab-toolbar-glyph.css'

/**
 * VocabToolbarGlyph surface — iOS `VocabToolbarGlyph`（→ `AppToolbarGlyph`，
 * `.vocab(skin)` style）的 web 鏡像。HStack(spacing s1)[icon + 可選 badge]：
 * - icon：SF arrow.triangle.2.circlepath，iconToolbar(symbol 15) secondaryText。
 * - badge：monoLabel(mono 10 bold) white 文字，水平 5 / 垂直 2 內距，
 *   destructive 填色的全圓 Capsule。
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0,0,0,0）：
 * `?crop=component` 令 surface 透明、shots `transparent:true` 以 omitBackground
 * 截圖，使 web 與 ref 同為 glyph-over-transparent（見 vocab-toolbar-glyph.css）。
 */
export function VocabToolbarGlyphScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-toolbar-glyph'>
}) {
  const { badge } = VOCAB_TOOLBAR_GLYPH_FIXTURES[scenario]
  return (
    <div className="vocab-toolbar-glyph-component-surface">
      <span className="vocab-toolbar-glyph">
        <SyncIcon className="vocab-toolbar-glyph-icon" size={15} />
        {badge != null && <span className="vocab-toolbar-glyph-badge">{badge}</span>}
      </span>
    </div>
  )
}
