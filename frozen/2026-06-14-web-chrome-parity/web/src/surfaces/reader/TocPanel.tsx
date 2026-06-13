import type { ScenarioId } from '../../harness/scenarios'
import { TOC_FIXTURES } from './panel-fixtures'
import { ListBulletRectIcon, TextBookClosedIcon, WarningTriangleFillIcon } from './icons'

/**
 * Reader · TOC 面板 — iOS TOCView / TOCViewPreviewScene 的 web 重寫（R3）。
 * 對齊 ReaderScenarios.swift「Reader · TOC」4 態，幾何見 toc.css 段（reader.css 尾）。
 *
 * 結構：NavigationStack（inline navbar「目錄」，title 落 tertiary 半透明材質）
 *   - loaded：insetGrouped List（章節列 + hairline 分隔，文字 inset）。
 *   - loading：AppStateMessageCard（左對齊 icon+title row + desc + spinner accessory）。
 *   - empty：AppEmptyStateCard（置中 hero icon + serif 粗標題 + desc）。
 *   - failed：AppStateMessageCard（exclamationmark.triangle.fill + 訊息）。
 */
export function TocPanel({ scenario }: { scenario: ScenarioId<'reader'> }) {
  const fixture = TOC_FIXTURES[scenario]
  if (!fixture) return null

  return (
    <div className="rpanel rpanel-toc">
      <header className="rpanel-nav">
        <span className="rpanel-nav-title">目錄</span>
      </header>
      <div className="rpanel-toc-body">
        {fixture.state === 'loaded' && (
          <ul className="rpanel-toc-list">
            {fixture.chapters.map((title, i) => (
              <li key={i} className="rpanel-toc-row">
                <span className="rpanel-toc-row-text">{title}</span>
              </li>
            ))}
          </ul>
        )}

        {fixture.state === 'loading' && (
          <div className="rpanel-state-wrap">
            <div className="rpanel-message-card">
              <div className="rpanel-message-head">
                <span className="rpanel-message-icon is-info">
                  <TextBookClosedIcon size={22} strokeWidth={1.5} />
                </span>
                <span className="rpanel-message-title">載入目錄中</span>
              </div>
              <p className="rpanel-message-desc">正在整理這本書的章節結構。</p>
              <span className="rpanel-spinner" aria-hidden="true" />
            </div>
          </div>
        )}

        {fixture.state === 'empty' && (
          <div className="rpanel-state-wrap">
            <div className="rpanel-empty-card">
              <span className="rpanel-empty-icon">
                <ListBulletRectIcon size={40} strokeWidth={1.4} />
              </span>
              <h2 className="rpanel-empty-title">這本書沒有目錄</h2>
              <p className="rpanel-empty-desc">出版內容沒有提供可導覽的章節列表。</p>
            </div>
          </div>
        )}

        {fixture.state === 'failed' && (
          <div className="rpanel-state-wrap">
            <div className="rpanel-message-card">
              <div className="rpanel-message-head">
                <span className="rpanel-message-icon is-info">
                  <WarningTriangleFillIcon size={22} />
                </span>
                <span className="rpanel-message-title">目錄載入失敗</span>
              </div>
              <p className="rpanel-message-desc">{fixture.failedMessage}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
