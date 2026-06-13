import { LayoutGroup, motion } from 'framer-motion'
import type { ScenarioId } from '../../harness/scenarios'
import { VOCABULARY_FIXTURES } from './fixtures'
import type { RowReviewState, VocabFixture, VocabRowFixture } from './fixtures'
import {
  BooksIcon,
  KnowledgeGraphIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  RefreshIcon,
  SortIcon,
  SparklesIcon,
} from './icons'
import { useVocabStore } from './store'
import { useVocabApiStore } from './useVocabApiStore'
import { VocabSceneShell } from '../../shared/VocabSceneShell'
import { useShellNav } from '../../shell/ShellNavContext'
import { screenFor } from '../../shell/nav'
import { snappy, usePreferredTransition } from '../../motion'
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
 *
 * 當 URL 含 shell=1 時，切換至 API-backed useVocabApiStore（讀 ?notebook_id= 拉取
 * 真實卡片，映射到 VocabRowFixture 形狀）。搜尋/過濾仍本地處理。非 ready 態由
 * VocabSceneShell 包裹。
 */

const STAT_LABELS = ['未學習', '待複習', '已複習'] as const
const STAT_STATES: RowReviewState[] = ['unlearned', 'due', 'reviewed']

function VocabRow({
  row,
  expanded,
  onToggle,
  onOpen,
}: {
  row: VocabRowFixture
  expanded: boolean
  onToggle: () => void
  /** shell 路徑：點列 → 導航至 word-detail（取代就地展開）；parity 路徑為 undefined。 */
  onOpen?: () => void
}) {
  return (
    <div className={`vc-row-wrap${expanded ? ' vc-row-wrap-expanded' : ''}`}>
      <button
        type="button"
        className="vc-row"
        onClick={onOpen ?? onToggle}
        aria-expanded={onOpen ? undefined : expanded}
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
  animated,
}: {
  stats: VocabFixture['stats']
  activeFilter: RowReviewState | null
  onToggle: (f: RowReviewState) => void
  /**
   * shell 路徑：用 framer-motion 共享 layoutId 讓選中底色在 chip 間 spring 滑移
   * （snappy），並加 press tap feel。parity 路徑為 false → 沿用純 CSS class
   *（選中態僅互動後出現，初始 capture 無此 DOM，逐像素一致）。
   */
  animated: boolean
}) {
  const counts = [stats.unlearned, stats.due, stats.reviewed]
  const transition = usePreferredTransition(snappy)

  // parity 路徑：純靜態 button + CSS class（不掛任何 motion）。選中態僅互動後出現，
  // 初始 capture（activeFilter=null）無此 DOM，故與靜態 PNG 逐像素一致。
  if (!animated) {
    return (
      <div className="vc-segment">
        {STAT_LABELS.map((label, i) => {
          const selected = activeFilter === STAT_STATES[i]
          return (
            <button
              type="button"
              className={`vc-stat${selected ? ' vc-stat-selected' : ''}`}
              key={label}
              onClick={() => onToggle(STAT_STATES[i])}
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

  // shell 路徑：選中底色為共享 layoutId 的 motion.span → 切換 chip 時 spring 滑移
  // 而非瞬跳；button 加 whileTap press feel。reduced-motion 由 transition 收斂為瞬時。
  return (
    <LayoutGroup id="vc-segment">
      <div className="vc-segment">
        {STAT_LABELS.map((label, i) => {
          const state = STAT_STATES[i]
          const selected = activeFilter === state
          return (
            <motion.button
              type="button"
              className={`vc-stat${selected ? ' vc-stat-active' : ''}`}
              key={label}
              onClick={() => onToggle(state)}
              aria-pressed={selected}
              whileTap={{ scale: 0.94 }}
              transition={transition}
            >
              {selected && (
                <motion.span
                  layoutId="vc-stat-pill"
                  className="vc-stat-pill"
                  transition={transition}
                  aria-hidden="true"
                />
              )}
              <span className="vc-stat-label">{label}</span>
              <span className="vc-stat-count">{counts[i]}</span>
            </motion.button>
          )
        })}
      </div>
    </LayoutGroup>
  )
}

export function VocabularyScreen({ scenario }: { scenario: ScenarioId<'vocabulary'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    const notebookId = new URLSearchParams(window.location.search).get('notebook_id')
    return <VocabularyScreenApi notebookId={notebookId} />
  }
  return <VocabularyScreenFixture scenario={scenario} />
}

/** Fixture-driven screen — parity harness 路徑（無 shell=1 時）。 */
function VocabularyScreenFixture({ scenario }: { scenario: ScenarioId<'vocabulary'> }) {
  const fixture = VOCABULARY_FIXTURES[scenario]
  const store = useVocabStore(fixture)
  return <VocabularyBody fixture={fixture} store={store} />
}

/** 殼層 header 動作 bag — 只在 shell 路徑提供（parity 不掛，header 維持純標題）。 */
type VocabHeaderActions = {
  /** 知識圖譜（KG）入口 → push vocab-knowledge-graph（live force graph）。 */
  openKnowledgeGraph: () => void
  /** 新增連結入口 → push vocab-add-link。 */
  openAddLink: () => void
}

/** API-driven screen — shell=1 時使用真實後端資料。 */
function VocabularyScreenApi({ notebookId }: { notebookId: string | null }) {
  const store = useVocabApiStore(notebookId)
  const nav = useShellNav()
  // 點列 → 導航至 word-detail-sheet，攜 params.word（= card.content）+ notebookId。
  // RouteTransition（殼層全域）已為此 push 上 iOS nav-push spring 轉場。
  const openWord = (word: string) =>
    nav.navigate(screenFor('word-detail-sheet', { word, notebookId: notebookId ?? undefined }))
  // header 鈕分派 Phase-1 導航邊：vocabulary → vocab-knowledge-graph / vocab-add-link。
  const headerActions: VocabHeaderActions = {
    openKnowledgeGraph: () => nav.navigate(screenFor('vocab-knowledge-graph')),
    openAddLink: () => nav.navigate(screenFor('vocab-add-link')),
  }
  const stats = {
    unlearned: store.visibleRows.filter((r) => r.reviewState === 'unlearned').length,
    due: store.visibleRows.filter((r) => r.reviewState === 'due').length,
    reviewed: store.visibleRows.filter((r) => r.reviewState === 'reviewed').length,
  }
  const ctaCount = stats.unlearned + stats.due
  const fixture: VocabFixture = {
    stats,
    ctaCount,
    rows: store.visibleRows,
    empty:
      store.visibleRows.length === 0
        ? {
            title: '尚無已收錄單字',
            description: '同步完成後，這裡會顯示你的雲端單字。',
            actionTitle: '重新整理',
            icon: 'books',
          }
        : undefined,
  }
  return (
    <VocabSceneShell
      status={store.status === 'ready' ? 'content' : store.status === 'loading' ? 'loading' : 'error'}
      onRetry={store.retry}
    >
      <VocabularyBody
        fixture={fixture}
        store={store}
        onRowOpen={openWord}
        headerActions={headerActions}
      />
    </VocabSceneShell>
  )
}

/** 共享的 vocabulary 畫面本體（fixture / API 兩條路共用）。 */
function VocabularyBody({
  fixture,
  store,
  onRowOpen,
  headerActions,
}: {
  fixture: VocabFixture
  store: {
    query: string
    setQuery: (q: string) => void
    activeFilter: RowReviewState | null
    toggleFilter: (f: RowReviewState) => void
    visibleRows: VocabRowFixture[]
    isNoMatch: boolean
    expandedWord: string | null
    toggleExpanded: (word: string) => void
  }
  /** shell 路徑：點列導航至 word-detail（word = card.content）。parity 路徑省略 → 就地展開。 */
  onRowOpen?: (word: string) => void
  /**
   * shell 路徑：header 動作 bag（知識圖譜 / 新增連結 鈕）。parity 路徑省略 →
   * header 維持純標題、不掛 motion，DOM 與靜態 PNG 逐像素一致。其在場亦作為
   * 「此為殼層渲染」的單一旗標：驅動 chip 動畫 / 搜尋聚焦 feel / 滾動慣性。
   */
  headerActions?: VocabHeaderActions
}) {
  const hasNoSeed = fixture.rows.length === 0
  const showZeroData = hasNoSeed && fixture.empty
  const isShell = headerActions != null

  return (
    <div className={`vocabulary${isShell ? ' vc-shell' : ''}`}>
      <header className="vc-nav">
        <h1 className="vc-nav-title">我的單字本</h1>
        {headerActions && (
          <div className="vc-nav-actions">
            <button
              type="button"
              className="vc-nav-action"
              aria-label="知識圖譜"
              onClick={headerActions.openKnowledgeGraph}
            >
              <KnowledgeGraphIcon size={20} />
            </button>
            <button
              type="button"
              className="vc-nav-action"
              aria-label="新增連結"
              onClick={headerActions.openAddLink}
            >
              <PlusIcon size={20} />
            </button>
          </div>
        )}
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
          animated={isShell}
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
                    onOpen={onRowOpen ? () => onRowOpen(row.word) : undefined}
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
