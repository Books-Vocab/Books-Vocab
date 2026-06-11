import type { ScenarioId } from '../../harness/scenarios'
import { VOCABULARY_FIXTURES } from './fixtures'
import type { VocabFixture, VocabRowFixture } from './fixtures'
import { BooksIcon, MagnifyingGlassIcon, RefreshIcon, SortIcon, SparklesIcon } from './icons'
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
 */

const STAT_LABELS = ['未學習', '待複習', '已複習'] as const

function VocabRow({ row }: { row: VocabRowFixture }) {
  return (
    <div className="vc-row">
      <div className="vc-row-main">
        <div className="vc-row-head">
          <span className="vc-row-word">{row.word}</span>
          <span className="vc-row-pos">{row.partOfSpeech}</span>
        </div>
        <span className="vc-row-translation">{row.translation}</span>
      </div>
      <span className="vc-row-detail">{row.detail}</span>
    </div>
  )
}

function StatSegment({ stats }: { stats: VocabFixture['stats'] }) {
  const counts = [stats.unlearned, stats.due, stats.reviewed]
  return (
    <div className="vc-segment">
      {STAT_LABELS.map((label, i) => (
        <div className="vc-stat" key={label}>
          <span className="vc-stat-label">{label}</span>
          <span className="vc-stat-count">{counts[i]}</span>
        </div>
      ))}
    </div>
  )
}

export function VocabularyScreen({ scenario }: { scenario: ScenarioId<'vocabulary'> }) {
  const fixture = VOCABULARY_FIXTURES[scenario]
  const isEmpty = fixture.rows.length === 0
  return (
    <div className="vocabulary">
      <header className="vc-nav">
        <h1 className="vc-nav-title">我的單字本</h1>
      </header>

      <div className="vc-scroll">
        {/* VocabSearchField — muted-fill 圓角輸入框，magnifyingglass + placeholder */}
        <div className="vc-search">
          <MagnifyingGlassIcon size={17} className="vc-search-icon" />
          <span className="vc-search-prompt">搜尋單字</span>
        </div>

        {/* 三態 stat segment — stage-bg 容器，三等分 label + count pill */}
        <StatSegment stats={fixture.stats} />

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
          {isEmpty && fixture.empty ? (
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
          ) : (
            <div className="vc-list">
              {fixture.rows.map((row, i) => (
                <div key={row.word}>
                  {i > 0 && <div className="vc-row-divider" />}
                  <VocabRow row={row} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
