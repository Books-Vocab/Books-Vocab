import type { ScenarioId } from '../../harness/scenarios'
import { SELECTION_TOOLBAR_FIXTURES } from './fixtures'
import { ArchiveboxIcon, TrashIcon } from './icons'
import './selection.css'

/**
 * Selection Toolbar surface — iOS SelectionToolbar 的 web 重寫。vocab 多選底欄：
 * 全寬白卡（cardBackground）pinned 到 frame 底部、上方 z2 elevation 陰影，內含
 * archive + delete 兩鈕（各 flex:1 等分、VStack icon + caption label）。
 *
 * tone 規則（對齊 iOS）：selectionCount==0 → 兩鈕皆 quaternaryText（disabled）；
 * >0 → archive=quaternaryText、delete=destructive 紅。
 *
 * 幾何量測（catalog PNG 1179×2556 dpr3，÷3 得 pt，measured）：
 *  - card top ≈ 762pt（card 高 90pt → 底部 852）。
 *  - icon band ≈ 772–786pt、label band ≈ 795–807pt。
 *  - 兩鈕中心 ≈ 104.7pt / 288pt（各半寬置中，flex:1）。
 */
export function SelectionToolbarScreen({ scenario }: { scenario: ScenarioId<'selection-toolbar'> }) {
  const fixture = SELECTION_TOOLBAR_FIXTURES[scenario]
  const enabled = fixture.selectionCount > 0
  return (
    <div className="selection-toolbar-surface">
      <div className="selection-toolbar" data-enabled={enabled ? '' : undefined}>
        <button
          type="button"
          className="selection-toolbar-btn"
          data-tone="neutral"
          disabled={!enabled}
          aria-label="封存"
        >
          <ArchiveboxIcon size={22} strokeWidth={1.5} />
          <span className="selection-toolbar-label">封存</span>
        </button>
        <button
          type="button"
          className="selection-toolbar-btn"
          data-tone={enabled ? 'destructive' : 'neutral'}
          disabled={!enabled}
          aria-label="刪除"
        >
          <TrashIcon size={22} strokeWidth={1.5} />
          <span className="selection-toolbar-label">刪除</span>
        </button>
      </div>
    </div>
  )
}
