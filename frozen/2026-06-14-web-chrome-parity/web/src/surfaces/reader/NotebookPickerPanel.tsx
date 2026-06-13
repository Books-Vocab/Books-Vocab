import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOK_FIXTURES } from './panel-fixtures'
import { CheckmarkIcon } from './icons'

/**
 * Reader · Notebook Picker 面板 — web 重寫（R3）。對齊 catalog snapshot
 * （Reader Notebook Picker，4 態）= 指定對拍 ref（見 panel-fixtures.ts 策略註）。
 *
 * snapshot 形態（2026-06-09 strict-binding 改版後，catalog-full-20260611-130335）：
 *   - 置中導覽標題「選擇單字本」（無「完成」action）。
 *   - Section header「單字本」（caption，secondaryText）。
 *   - insetGrouped List：列 = 4pt 色條（notebook.color 或 accent）+ 名稱（body，tail
 *     截斷）+ 綁定列 trailing accent checkmark。strict-binding 後**無**頂部「跟隨
 *     全域設定」卡、**無** isDefault「預設」副標（每書恰綁一本真實單字本，無 magic
 *     預設 / 全域跟隨；見 notebook-binding-strict）。
 * 幾何見 reader.css 的 rnotebook 段。
 */
export function NotebookPickerPanel({ scenario }: { scenario: ScenarioId<'reader'> }) {
  const fixture = NOTEBOOK_FIXTURES[scenario]
  if (!fixture) return null

  return (
    <div className="rpanel rpanel-notebook">
      <header className="rpanel-nav">
        <span className="rpanel-nav-title">選擇單字本</span>
      </header>
      <div className="rpanel-notebook-body">
        <h2 className="rnotebook-section-header">單字本</h2>
        {fixture.notebooks.length > 0 && (
          <ul className="rnotebook-list">
            {fixture.notebooks.map((nb, i) => {
              const selected = fixture.boundRemoteId === nb.remoteId
              return (
                <li key={nb.remoteId} className="rnotebook-row" data-first={i === 0 ? '' : undefined}>
                  <span className="rnotebook-bar" style={nb.color ? { background: nb.color } : undefined} />
                  <span className="rnotebook-name-block">
                    <span className="rnotebook-name">{nb.name}</span>
                  </span>
                  {selected && (
                    <span className="rnotebook-check">
                      <CheckmarkIcon size={17} strokeWidth={2} />
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
