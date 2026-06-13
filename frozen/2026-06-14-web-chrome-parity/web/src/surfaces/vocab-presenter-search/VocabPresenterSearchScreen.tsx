import type { ScenarioId } from '../../harness/scenarios'
import {
  VOCAB_PRESENTER_SEARCH_FIXTURES,
  FILTER_CHIPS,
  EMPTY_STATE,
  SORT_LABEL,
} from './fixtures'
import type { VocabRowFixture } from './fixtures'
import { ArrowUpArrowDownIcon, MagnifyingGlassIcon } from './icons'
import { useVocabPresenterSearchApiStore } from './useVocabPresenterSearchApiStore'
import type { ReviewState } from './useVocabPresenterSearchApiStore'
import { VocabSceneShell } from '../../shared/VocabSceneShell'
import './vocab-presenter-search.css'

/**
 * Vocab Presenter (search) surface — iOS `KGVocabView`（searchText 綁定）→
 * `KGVocabPresenter`（KGVocabPresenter.swift:13）的 web 鏡像，對齊 catalog
 * surface「KG Vocab Presenter」三個搜尋態 scene。
 *
 * iOS view tree（KGVocabPresenter.body）：
 *   VStack(.leading, spacing:0) {
 *     // pinned filter bar — pageBackground 底
 *     VStack(.leading, spacing: microGap=6) {
 *       VocabFilterChipBar(options, selection: $set)      // AppFilterChipBar(.vocab)
 *       HStack(spacing: inlineGap=8) { Spacer · VocabSortPill (· CTA — 本 scene nil) }
 *     }
 *     .padding(.horizontal, pageHorizontalInset=20)
 *     .padding(.top, microGap=6).padding(.bottom, inlineGap=8)
 *     .background(pageBackground)
 *
 *     ScrollView { VStack(.leading, spacing: sectionGap=14) {
 *       (banner — 本 scene 無)
 *       VocabListCard { EmptyView() } content: {
 *         rows.isEmpty ? VocabEmptyStateContent(...) : LazyVStack(rows + dividers)
 *       }
 *     }
 *     .padding(.horizontal, 20).padding(.top, microGap=6).padding(.bottom, pageBottomInset) }
 *     .vocabCanvasBackground()   // pageBackground
 *   }
 *
 * VocabFilterChipBar = AppFilterChipBar(style: .vocab)，selection 空 Set ⇒ 全
 * unselected：title secondaryText、count badge mutedFill + 文字 primaryText、
 * 容器 stageBackground、containerRadius=control+4=10。
 * VocabSortPill：Capsule(mutedFill) + arrow.up.arrow.down + label(caption)
 * secondaryText。
 * VocabListCard = VocabCard(padding:0) → AppSectionCard(.vocab)：white card、
 * radius=md=8、border=cardBorder。header=EmptyView()（.padding(headerPadding)）
 * + 上方 divider；rows-only 分支底下 row 間以 divider(.leading inset 16) 分隔。
 *
 * 每列 = KGVocabRow → WordRow（showsReviewProgress unlearned ratio:nil）：
 *   word(mono18semibold/primary) + pos(caption sans12bold/tertiary) /
 *   translation(sans15/secondary) ··· trailing「首輪 12h」(mono10bold/secondary)。
 *
 * catalog scene layout=.fill → ref = 全裝置幀 1179×2556、corner=page-bg（不透明）。
 * 全 phone-frame 捕捉（無 crop=component、無 transparent）。
 */
export function VocabPresenterSearchScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-presenter-search'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) return <VocabPresenterSearchApi />
  return <VocabPresenterSearchFixture scenario={scenario} />
}

/** Fixture-driven 唯讀搜尋態（parity 路徑，DOM byte-identical）。 */
function VocabPresenterSearchFixture({
  scenario,
}: {
  scenario: ScenarioId<'vocab-presenter-search'>
}) {
  const fx = VOCAB_PRESENTER_SEARCH_FIXTURES[scenario]
  return (
    <VocabPresenterSearchBody
      counts={[fx.counts.unlearned, fx.counts.due, fx.counts.reviewed]}
      rows={fx.rows}
    />
  )
}

/**
 * shell 路徑：可輸入搜尋框 + 可點三態 chip + 可切排序，client-side 過濾 / 排序載入的
 * 卡片。非 ready 態由 VocabSceneShell 包裹。
 */
function VocabPresenterSearchApi() {
  const store = useVocabPresenterSearchApiStore()
  const rows: VocabRowFixture[] = store.rows.map((r) => ({
    word: r.word,
    partOfSpeech: r.partOfSpeech,
    translation: r.translation,
    detailLabel: r.detailLabel,
  }))
  const filterIds: ReviewState[] = ['unlearned', 'due', 'reviewed']
  return (
    <VocabSceneShell
      status={
        store.status === 'ready' ? 'content' : store.status === 'loading' ? 'loading' : 'error'
      }
      onRetry={store.retry}
    >
      <VocabPresenterSearchBody
        counts={[store.counts.unlearned, store.counts.due, store.counts.reviewed]}
        rows={rows}
        query={store.query}
        onQueryChange={store.setQuery}
        activeFilter={store.filter}
        onToggleFilter={(id) => store.toggleFilter(filterIds[id])}
        sortLabel={store.sort === 'alphabetical' ? '字母順序' : SORT_LABEL}
        onToggleSort={store.toggleSort}
      />
    </VocabSceneShell>
  )
}

/**
 * 共用畫面本體（fixture / API 兩條路共用）。互動 prop 全選用性：parity 路徑省略
 * 全部互動 prop → chip/sort 為唯讀 span（DOM 與靜態 PNG 一致）；shell 路徑注入後
 * 升級為可點按鈕並插入搜尋框。
 */
function VocabPresenterSearchBody({
  counts,
  rows,
  query,
  onQueryChange,
  activeFilter,
  onToggleFilter,
  sortLabel,
  onToggleSort,
}: {
  counts: [number, number, number]
  rows: VocabRowFixture[]
  query?: string
  onQueryChange?: (q: string) => void
  activeFilter?: ReviewState | null
  onToggleFilter?: (chipIndex: number) => void
  sortLabel?: string
  onToggleSort?: () => void
}) {
  const interactive = onToggleFilter !== undefined
  const filterIds: ReviewState[] = ['unlearned', 'due', 'reviewed']
  return (
    <div className="vps-surface">
      {/* shell 路徑：搜尋輸入框（parity 路徑不渲染 → DOM 不變） */}
      {onQueryChange ? (
        <div className="vps-search">
          <MagnifyingGlassIcon className="vps-search-icon" size={17} strokeWidth={1.6} />
          <input
            className="vps-search-input"
            type="text"
            placeholder="搜尋單字"
            value={query ?? ''}
            onChange={(e) => onQueryChange(e.target.value)}
            aria-label="搜尋單字"
          />
        </div>
      ) : null}

      {/* pinned filter bar — pageBackground */}
      <div className="vps-pinned">
        {/* VocabFilterChipBar (.vocab) */}
        <div className="vps-chipbar" role="tablist">
          {FILTER_CHIPS.map((chip, i) => {
            const selected = interactive && activeFilter === filterIds[i]
            const content = (
              <>
                <span className="vps-chip-title">{chip.title}</span>
                <span className="vps-chip-count">{counts[i]}</span>
              </>
            )
            return interactive ? (
              <button
                key={chip.id}
                type="button"
                className={`vps-chip${selected ? ' vps-chip-selected' : ''}`}
                role="tab"
                aria-selected={selected}
                onClick={() => onToggleFilter?.(i)}
              >
                {content}
              </button>
            ) : (
              <span key={chip.id} className="vps-chip" role="tab" aria-selected={false}>
                {content}
              </span>
            )
          })}
        </div>
        {/* HStack { Spacer · VocabSortPill } */}
        <div className="vps-sort-row">
          {onToggleSort ? (
            <button type="button" className="vps-sort-pill" onClick={onToggleSort}>
              <ArrowUpArrowDownIcon className="vps-sort-icon" size={15} strokeWidth={1.7} />
              <span className="vps-sort-label">{sortLabel ?? SORT_LABEL}</span>
            </button>
          ) : (
            <span className="vps-sort-pill">
              <ArrowUpArrowDownIcon className="vps-sort-icon" size={15} strokeWidth={1.7} />
              <span className="vps-sort-label">{SORT_LABEL}</span>
            </span>
          )}
        </div>
      </div>

      {/* ScrollView content */}
      <div className="vps-scroll">
        <div className="vps-card">
          {/* VocabListCard header = EmptyView().padding(headerPadding) + divider */}
          <div className="vps-card-header" />
          <div className="vps-card-divider" />
          <div className="vps-card-body">
            {rows.length === 0 ? (
              <div className="vps-empty">
                <div className="vps-empty-content">
                  <MagnifyingGlassIcon className="vps-empty-icon" size={30} strokeWidth={1.4} />
                  <div className="vps-empty-title">{EMPTY_STATE.title}</div>
                  <div className="vps-empty-desc">{EMPTY_STATE.description}</div>
                  <div className="vps-empty-guidance">{EMPTY_STATE.guidanceText}</div>
                </div>
              </div>
            ) : (
              <div className="vps-rows">
                {rows.map((row, i) => (
                  <div key={row.word}>
                    <div className="vps-row">
                      <div className="vps-row-content">
                        <div className="vps-row-main">
                          <div className="vps-row-head">
                            <span className="vps-row-word">{row.word}</span>
                            <span className="vps-row-pos">{row.partOfSpeech}</span>
                          </div>
                          <span className="vps-row-translation">{row.translation}</span>
                        </div>
                        <span className="vps-row-detail">{row.detailLabel}</span>
                      </div>
                    </div>
                    {i < rows.length - 1 && <div className="vps-row-divider" />}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
