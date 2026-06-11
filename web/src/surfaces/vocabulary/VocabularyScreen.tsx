import type { ScenarioId } from '../../harness/scenarios'
import { VOCABULARY_FIXTURES } from './fixtures'
import type { RowReviewState, VocabFixture, VocabRowFixture } from './fixtures'
import { BooksIcon, MagnifyingGlassIcon, RefreshIcon, SortIcon, SparklesIcon } from './icons'
import { useVocabStore } from './store'
import './vocabulary.css'

/**
 * Vocabulary surface — iOS VocabularyListView（KGVocabView/KGVocabPresenter）的
 * web 重寫。結構順序對齊 VocabularyListView.body：
 *   large nav title「我的單字本」
 *   → VocabSearchField（muted-fill 圓角輸入框 + magnifyingglass prompt）
 *   → 三態 VocabFilterChipBar（未學習/待複習/已複習 + count pill；stage-bg 容器）
 *   → chip/sort 列（Spacer + VocabSortPill「複習優先」+ 未學複習 CTA pill）
 *   → VocabListCard（白卡）包 KGVocabRow 列表，row 間 hairline divider（leading inset）。
 * 幾何常數逐一對齊（見 vocabulary.css 的 px 註解，measured 標 PNG 實測值）。
 *
 * 互動化（fixtures 當資料層，store 薄狀態）：搜尋框真輸入過濾、三態 chip 點選過濾、
 * row 點擊就地展開 detail。parity 契約：初始狀態（空搜尋 / 未選 chip / 全收合）下
 * DOM 與靜態 PNG 逐像素一致；互動僅在使用者操作後改變 DOM。
 */

const STAT_LABELS = ['未學習', '待複習', '已複習'] as const
const STAT_STATES: RowReviewState[] = ['unlearned', 'due', 'reviewed']

function VocabRow({
  row,
  expanded,
  onToggle,
}: {
  row: VocabRowFixture
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className={`vc-row-wrap${expanded ? ' vc-row-wrap-expanded' : ''}`}>
      <button
        type="button"
        className="vc-row"
        onClick={onToggle}
        aria-expanded={expanded}
        data-word={row.word}
      >
        <div className="vc-row-main">
          <div className="vc-row-head">
            <span className="vc-row-word">{row.word}</span>
            <span className="vc-row-pos">{row.partOfSpeech}</span>
          </div>
          <span className="vc-row-translation">{row.translation}</span>
        </div>
        <span className="vc-row-detail">{row.detail}</span>
      </button>
      {expanded && (
        <div className="vc-row-detail-panel">
          <p className="vc-detail-explanation">{row.expansion.explanation}</p>
          <p className="vc-detail-example">{row.expansion.example}</p>
        </div>
      )}
    </div>
  )
}

function StatSegment({
  stats,
  activeFilter,
  onToggle,
}: {
  stats: VocabFixture['stats']
  activeFilter: RowReviewState | null
  onToggle: (f: RowReviewState) => void
}) {
  const counts = [stats.unlearned, stats.due, stats.reviewed]
  return (
    <div className="vc-segment">
      {STAT_LABELS.map((label, i) => {
        const state = STAT_STATES[i]
        const selected = activeFilter === state
        return (
          <button
            type="button"
            className={`vc-stat${selected ? ' vc-stat-selected' : ''}`}
            key={label}
            onClick={() => onToggle(state)}
            aria-pressed={selected}
          >
            <span className="vc-stat-label">{label}</span>
            <span className="vc-stat-count">{counts[i]}</span>
          </button>
        )
      })}
    </div>
  )
}

export function VocabularyScreen({ scenario }: { scenario: ScenarioId<'vocabulary'> }) {
  const fixture = VOCABULARY_FIXTURES[scenario]
  const store = useVocabStore(fixture)
  const hasNoSeed = fixture.rows.length === 0

  // zero-data（fixture.empty）優先；其次互動過濾後的 no-match 空狀態。
  const showZeroData = hasNoSeed && fixture.empty

  return (
    <div className="vocabulary">
      <header className="vc-nav">
        <h1 className="vc-nav-title">我的單字本</h1>
      </header>

      <div className="vc-scroll">
        {/* VocabSearchField — muted-fill 圓角輸入框，magnifyingglass + 真輸入 */}
        <div className="vc-search">
          <MagnifyingGlassIcon size={17} className="vc-search-icon" />
          <input
            className="vc-search-input"
            type="text"
            placeholder="搜尋單字"
            value={store.query}
            onChange={(e) => store.setQuery(e.target.value)}
            aria-label="搜尋單字"
          />
        </div>

        {/* 三態 stat segment — 可點選的 chip 過濾器（未選 = 顯示全部，對齊靜態態） */}
        <StatSegment
          stats={fixture.stats}
          activeFilter={store.activeFilter}
          onToggle={store.toggleFilter}
        />

        {/* chip/sort 列：Spacer 推到右 → sort pill +（可選）未學複習 CTA pill */}
        <div className="vc-sortbar">
          <span className="vc-sort-pill">
            <SortIcon size={15} />
            <span>複習優先</span>
          </span>
          {fixture.ctaCount > 0 && (
            <span className="vc-cta-pill">
              <SparklesIcon size={14} />
              <span className="vc-cta-num">{fixture.ctaCount}</span>
            </span>
          )}
        </div>

        {/* VocabListCard — 白卡容器 */}
        <div className="vc-card">
          {showZeroData && fixture.empty ? (
            <div className="vc-empty">
              {fixture.empty.icon === 'books' ? (
                <BooksIcon size={44} className="vc-empty-icon" />
              ) : (
                <MagnifyingGlassIcon size={44} className="vc-empty-icon" />
              )}
              <span className="vc-empty-title">{fixture.empty.title}</span>
              <p className="vc-empty-desc">{fixture.empty.description}</p>
              {fixture.empty.actionTitle && (
                <button className="vc-empty-action" type="button">
                  <RefreshIcon size={17} />
                  <span>{fixture.empty.actionTitle}</span>
                </button>
              )}
            </div>
          ) : store.isNoMatch ? (
            <div className="vc-empty">
              <MagnifyingGlassIcon size={44} className="vc-empty-icon" />
              <span className="vc-empty-title">找不到符合的單字</span>
              <p className="vc-empty-desc">試試其他關鍵字，或清除篩選條件以顯示全部單字。</p>
            </div>
          ) : (
            <div className="vc-list">
              {store.visibleRows.map((row, i) => (
                <div key={row.word}>
                  {i > 0 && <div className="vc-row-divider" />}
                  <VocabRow
                    row={row}
                    expanded={store.expandedWord === row.word}
                    onToggle={() => store.toggleExpanded(row.word)}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
