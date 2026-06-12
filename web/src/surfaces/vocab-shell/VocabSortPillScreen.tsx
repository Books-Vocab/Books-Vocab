import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_SORT_PILL_FIXTURES } from './fixtures'
import { SortArrowsIcon } from './icons'
import './vocab-shell.css'

/**
 * VocabSortPill surface — iOS `VocabSortPill` 的 web 鏡像（Vocab Shell 原語層
 * 第一個 atom）。caption(12, bold) secondaryText 文字 + arrow.up.arrow.down
 * 前導圖示，包在 muted-fill 全圓 Capsule 內；內距 = compact-chip token（6h/3v）、
 * icon↔text 間距 = s1(4)。
 *
 * catalog 元件 scene 畫布透明（component-isolated）：`?crop=component` 令
 * surface 透明、shots `transparent:true` 以 omitBackground 截圖，使 web 與
 * ref 同為 pill-over-transparent（見 vocab-shell.css）。
 */
export function VocabSortPillScreen({ scenario }: { scenario: ScenarioId<'vocab-sort-pill'> }) {
  const { label } = VOCAB_SORT_PILL_FIXTURES[scenario]
  return (
    <div className="vocab-shell-component-surface">
      <span className="vocab-sort-pill" role="button" aria-label={`排序方式：${label}`}>
        <SortArrowsIcon className="vocab-sort-pill-icon" />
        <span className="vocab-sort-pill-label">{label}</span>
      </span>
    </div>
  )
}
