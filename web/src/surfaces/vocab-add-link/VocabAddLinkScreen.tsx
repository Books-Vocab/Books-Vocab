import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_ADD_LINK_FIXTURES } from './fixtures'
import { MagnifyingGlassIcon } from './icons'
import './vocab-add-link.css'

/**
 * Vocabulary · Add Link surface — iOS `AddLinkSheet`
 * （VocabularyEntry 卡片連結候選清單 sheet）的 web 鏡像。
 *
 * iOS view tree（AddLinkSheet.swift）：
 *   NavigationStack{ VStack(spacing 0)[
 *     searchField .padding(cardBlockPadding=24)
 *     if searchText.isEmpty → AppEmptyStateContent(
 *         title:"搜尋單字", systemImage:"magnifyingglass",
 *         description:"輸入單字名稱來建立連結").frame(maxHeight:.infinity)
 *     else if filteredEntries.isEmpty → 「沒有結果」空態
 *     else → List(候選列)
 *   ]}.vocabCanvasBackground().navigationTitle("新增連結").inlineNavigationBarTitle()
 *
 *   空態走 AppEmptyStateContent 預設 style = .themed(appTheme)：
 *     icon hero(.light)=40、title h2(.semibold)=serif 22、desc body()=sans 17、spacing 14。
 *
 *   searchField = HStack(spacing cardBlockInnerGap=8)[
 *     Image("magnifyingglass")/tertiaryText
 *     TextField("搜尋單字…")/primaryText（空態 placeholder 色）
 *   ].padding(cardBlockInnerGap*1.5=12)
 *    .background(RoundedRect(radius md=8).fill(cardBackground=白))
 *
 * **渲染當下**：初始 searchText=="" → 固定走第一支空態，與候選有無無關
 * （兩 catalog scene PNG byte-identical 已證實）。故 web 只渲染：
 *   inline nav title「新增連結」（faint serif）+ 白色 search field + 空查詢空態。
 *
 * catalog scene layout = .fill，畫布**不透明**（vocabCanvasBackground 填 #f7f6f3 = --page-bg；
 * alpha channel mean=1 已量測）→ 全 phone-frame 不透明捕捉，manifest 不加 transparent flag。
 */
export function VocabAddLinkScreen({ scenario }: { scenario: ScenarioId<'vocab-add-link'> }) {
  const fx = VOCAB_ADD_LINK_FIXTURES[scenario]
  return (
    <div className="val-surface">
      {/* inline nav bar — 標題置中、faint serif（catalog 量測 ≈ white serif on #f7f6f3，near-invisible） */}
      <div className="val-nav">
        <div className="val-nav-title">新增連結</div>
      </div>

      {/* searchField .padding(cardBlockPadding=24) */}
      <div className="val-search-pad">
        <div className="val-search-field" role="search">
          <MagnifyingGlassIcon size={17} className="val-search-icon" />
          <span className="val-search-text" data-placeholder="1">
            {fx.searchPrompt}
          </span>
        </div>
      </div>

      {/* AppEmptyStateContent（空查詢態）.frame(maxHeight:.infinity) → 撐滿剩餘空間垂直置中 */}
      <div className="val-empty">
        <div className="val-empty-content">
          <MagnifyingGlassIcon size={40} strokeWidth={1.5} className="val-empty-icon" />
          <div className="val-empty-title">{fx.emptyTitle}</div>
          <div className="val-empty-description">{fx.emptyDescription}</div>
        </div>
      </div>
    </div>
  )
}
