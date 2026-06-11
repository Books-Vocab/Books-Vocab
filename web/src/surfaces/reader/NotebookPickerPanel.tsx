import type { ScenarioId } from '../../harness/scenarios'
import { NOTEBOOK_FIXTURES } from './panel-fixtures'
import { CheckmarkIcon, GlobeIcon } from './icons'

/**
 * Reader · Notebook Picker 面板 — web 重寫（R3）。對齊 catalog snapshot
 * （Reader Notebook Picker，4 態）= 指定對拍 ref（見 panel-fixtures.ts 策略註）。
 *
 * snapshot 形態（早於 strict-binding 改版）：
 *   - 頂部 inset 卡「跟隨全域設定」：globe + 兩行（body + secondary 副標）+ boundRemoteId
 *     == null 時 trailing checkmark。
 *   - Section header「單字本」。
 *   - insetGrouped List：列 = 4pt 色條（notebook.color 或 accent）+ 名稱（body，tail
 *     截斷）+ isDefault 時「預設」副標 + 選中 checkmark。
 * 幾何見 reader.css 的 rnotebook 段。
 */
export function NotebookPickerPanel({ scenario }: { scenario: ScenarioId<'reader'> }) {
  const fixture = NOTEBOOK_FIXTURES[scenario]
  if (!fixture) return null

  const followGlobalSelected = fixture.boundRemoteId === null

  return (
    <div className="rpanel rpanel-notebook">
      <header className="rpanel-nav">
        <span className="rpanel-nav-title">選擇單字本</span>
        <button type="button" className="rpanel-nav-action" aria-label="完成">
          完成
        </button>
      </header>
      <div className="rpanel-notebook-body">
        {/* 跟隨全域設定 inset 卡 */}
        <div className="rnotebook-global-card">
          <span className="rnotebook-global-icon">
            <GlobeIcon size={22} strokeWidth={1.5} />
          </span>
          <span className="rnotebook-global-text">
            <span className="rnotebook-global-title">跟隨全域設定</span>
            <span className="rnotebook-global-sub">使用目前選定的單字本</span>
          </span>
          {followGlobalSelected && (
            <span className="rnotebook-check">
              <CheckmarkIcon size={19} strokeWidth={2} />
            </span>
          )}
        </div>

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
                    {nb.isDefault && <span className="rnotebook-default">預設</span>}
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
