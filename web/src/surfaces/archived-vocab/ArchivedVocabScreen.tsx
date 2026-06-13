import type { ScenarioId } from '../../harness/scenarios'
import { ARCHIVED_VOCAB_FIXTURES } from './fixtures'
import { ArchiveboxIcon, ArrowUTurnIcon, MagnifyingGlassIcon, TrashIcon } from './icons'
import { useArchivedVocabApiStore } from './useArchivedVocabApiStore'
import { VocabSceneShell } from '../../shared/VocabSceneShell'
import './archived-vocab.css'

/**
 * Archived Vocab surface — iOS `ArchivedVocabSheet`（ArchivedVocabSheet.swift）
 * 的 web 鏡像。NavigationStack 全螢幕 sheet（layout .fill），含：
 *
 *   inline nav title「封存」（catalog 以極淡 chrome 渲染，量測近頁底色）
 *   → 非空：`List(.plain)` 邊到邊白底 row，每 row = WordRow（archive style）
 *      · leadingSystemImage = archivebox（iconSmall 12 medium / tertiaryText）
 *      · word（rowWord = mono 18 semibold / secondaryText，封存態 wordTone=.secondary）
 *      · partOfSpeech（caption = sans 12 bold / tertiaryText）
 *      · translation（body = sans 15 / secondaryText, lineLimit 2）
 *      row 間 hairline divider（listDividerInset 16pt leading inset，延伸至右緣）
 *   → 空：VocabEmptyStateCard（白卡置中）= archivebox(symbolLarge 30) + title
 *      (sectionTitle serif 18 bold) + description(body 15)；card .vocab style
 *      （cardBackground 白 / cardBorder 0.7 / radius card=8）
 *   → 底部 `.searchable` 列（magnifyingglass + 「搜尋封存單字」prompt，極淡）
 *
 * 幾何量自 ref（1179×2556 native ÷3 = pt）：nav band ≈113pt、單 row ≈66pt、
 * divider leading inset 16pt、頁底色 #F7F6F3 = --page-bg、list row 白 = --card-bg。
 * catalog scene = .fill；Populated/Single/Empty alpha-mean=1（不透明，全 phone-frame
 * 捕捉）；Long list 為過場近空白捕捉（alpha-mean≈0.003），web 照常渲染全列。
 *
 * nav/search chrome 在 catalog 以極淡 alpha 渲染 → 以 token-allow 淡灰近似（對齊
 * notebook-edit 的 nav-title 量測淡字策略）。
 */
export function ArchivedVocabScreen({ scenario }: { scenario: ScenarioId<'archived-vocab'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) return <ArchivedVocabApi />
  return <ArchivedVocabFixture scenario={scenario} />
}

/** shell 路徑：列真實封存卡 + 還原/刪除（單列 + 多選批次）。 */
function ArchivedVocabApi() {
  const store = useArchivedVocabApiStore()
  const selecting = store.selected.size > 0

  return (
    <VocabSceneShell
      status={store.status === 'ready' ? 'content' : store.status === 'loading' ? 'loading' : 'error'}
      onRetry={store.retry}
    >
      <div className="av-surface">
        <header className="av-nav">
          <span className="av-nav-title">封存</span>
        </header>

        <div className="av-body">
          {store.rows.length === 0 ? (
            <div className="av-empty">
              <div className="av-empty-card">
                <ArchiveboxIcon className="av-empty-icon" size={30} strokeWidth={1.2} />
                <div className="av-empty-title">沒有封存的卡片</div>
                <div className="av-empty-desc">左滑卡片即可封存。</div>
              </div>
            </div>
          ) : (
            <div className="av-list">
              {store.rows.map((r, i) => (
                <div className="av-row-cell" key={r.id}>
                  {i > 0 && <div className="av-divider" />}
                  <div className="av-row" data-selected={store.selected.has(r.word) ? '' : undefined}>
                    <button
                      type="button"
                      className="av-row-select"
                      aria-pressed={store.selected.has(r.word)}
                      aria-label={`選取 ${r.word}`}
                      onClick={() => store.toggleSelect(r.word)}
                    >
                      <ArchiveboxIcon className="av-row-icon" size={12} strokeWidth={1.5} />
                    </button>
                    <div className="av-row-main">
                      <div className="av-row-head">
                        <span className="av-row-word">{r.word}</span>
                        {r.partOfSpeech ? <span className="av-row-pos">{r.partOfSpeech}</span> : null}
                      </div>
                      <span className="av-row-translation">{r.translation}</span>
                    </div>
                    <div className="av-row-actions">
                      <button
                        type="button"
                        className="av-row-action"
                        aria-label={`還原 ${r.word}`}
                        onClick={() => store.restore(r.word)}
                      >
                        <ArrowUTurnIcon size={18} strokeWidth={1.6} />
                      </button>
                      <button
                        type="button"
                        className="av-row-action av-row-action--destructive"
                        aria-label={`刪除 ${r.word}`}
                        onClick={() => store.remove(r.word)}
                      >
                        <TrashIcon size={18} strokeWidth={1.6} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {selecting ? (
          <div className="av-batchbar" role="toolbar" aria-label="批次操作">
            <span className="av-batch-count">{`已選 ${store.selected.size}`}</span>
            <button type="button" className="av-batch-btn" onClick={store.restoreSelected}>
              <ArrowUTurnIcon size={20} strokeWidth={1.6} />
              <span>還原</span>
            </button>
            <button
              type="button"
              className="av-batch-btn av-batch-btn--destructive"
              onClick={store.deleteSelected}
            >
              <TrashIcon size={20} strokeWidth={1.6} />
              <span>刪除</span>
            </button>
            <button type="button" className="av-batch-btn" onClick={store.clearSelection}>
              取消
            </button>
          </div>
        ) : (
          <div className="av-search">
            <MagnifyingGlassIcon className="av-search-icon" size={17} />
            <span className="av-search-prompt">搜尋封存單字</span>
          </div>
        )}
      </div>
    </VocabSceneShell>
  )
}

/** Fixture-driven 唯讀列表（parity 路徑，DOM byte-identical）。 */
function ArchivedVocabFixture({ scenario }: { scenario: ScenarioId<'archived-vocab'> }) {
  const fixture = ARCHIVED_VOCAB_FIXTURES[scenario]
  const isEmpty = fixture.rows.length === 0

  return (
    <div className="av-surface">
      {/* inline nav bar：status + bar ≈113pt，標題置中、極淡 */}
      <header className="av-nav">
        <span className="av-nav-title">封存</span>
      </header>

      <div className="av-body">
        {isEmpty ? (
          <div className="av-empty">
            {/* VocabEmptyStateCard：白卡置中，內容 = archivebox + title + desc */}
            <div className="av-empty-card">
              <ArchiveboxIcon className="av-empty-icon" size={30} strokeWidth={1.2} />
              <div className="av-empty-title">沒有封存的卡片</div>
              <div className="av-empty-desc">左滑卡片即可封存。</div>
            </div>
          </div>
        ) : (
          <div className="av-list">
            {fixture.rows.map((r, i) => (
              <div className="av-row-cell" key={r.id}>
                {i > 0 && <div className="av-divider" />}
                <div className="av-row">
                  <div className="av-row-main">
                    <div className="av-row-head">
                      <ArchiveboxIcon className="av-row-icon" size={12} strokeWidth={1.5} />
                      <span className="av-row-word">{r.word}</span>
                      {r.partOfSpeech ? <span className="av-row-pos">{r.partOfSpeech}</span> : null}
                    </div>
                    <span className="av-row-translation">{r.translation}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 底部 .searchable 列（極淡 chrome） */}
      <div className="av-search">
        <MagnifyingGlassIcon className="av-search-icon" size={17} />
        <span className="av-search-prompt">搜尋封存單字</span>
      </div>
    </div>
  )
}
