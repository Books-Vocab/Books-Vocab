import type { ScenarioId } from '../../harness/scenarios'
import { KNOWLEDGE_GRAPH_VIEW_FIXTURES } from './fixtures'
import { VocabKnowledgeGraphLive } from '../vocab-knowledge-graph/VocabKnowledgeGraphLive'
import './knowledge-graph-view.css'

/**
 * Shell gate (?shell=1): the full-screen Knowledge Graph view. The static
 * fixture is the logged-out login prompt; inside the shell the offline mock
 * session is logged in (devLogin), so we mount the live force graph. The parity
 * capture path (no ?shell=1) renders the byte-identical login-prompt card below.
 */
function isShell(): boolean {
  if (typeof window === 'undefined') return false
  return new URLSearchParams(window.location.search).get('shell') === '1'
}

/**
 * Knowledge Graph View surface（知識圖譜全屏 screen）的 web 鏡像。
 *
 * iOS 路徑：KnowledgeGraphView → KnowledgeGraphPresenter
 *   → VocabSceneShell(phase: .empty) → centeredWrapper(VStack[Spacer · card · Spacer]
 *     .padding(cardBlockPadding=24).vocabCanvasBackground=pageBackground)
 *   → VocabEmptyStateCard → AppEmptyStateCard(style=.vocab(skin))
 *     = AppSectionCard(.vocab：cardBg / cardBorder@0.7 / radius md=8 / z1 elevation,
 *       padding=cardPadding 18) { AppEmptyStateContent.padding(.v, verticalPadding=12) }。
 *
 * AppEmptyStateContent(style=.vocab)：VStack(spacing 14, maxWidth ∞)[
 *   Image(systemName).symbolLarge(symbol 30 light)/tertiaryText ·
 *   Text(title).sectionTitle(serif 18 bold)/primaryText ·
 *   Text(description).body(sans 15)/secondaryText.centered ]（無 action）。
 *
 * Scene「Logged out · empty graph」layout=.fill → 全裝置幀（1179×2556，corner
 * srgba(247,246,243,1)=page-bg，alpha-mean=1 不透明）→ 全 phone-frame 捕捉
 * （無 crop=component、無 transparent）：surface 撐滿、bg=page-bg、卡片垂直置中。
 */
export function KnowledgeGraphViewScreen({
  scenario,
}: {
  scenario: ScenarioId<'knowledge-graph-view'>
}) {
  // ?shell=1 → live force graph (logged-in offline session). Parity path unchanged.
  if (isShell()) {
    return <VocabKnowledgeGraphLive />
  }

  const fixture = KNOWLEDGE_GRAPH_VIEW_FIXTURES[scenario]
  const Icon = fixture.icon
  return (
    <div className="kg-view-surface">
      <div className="kg-view-card">
        <div className="kg-view-content">
          <Icon className="kg-view-icon" size={30} />
          <div className="kg-view-title">{fixture.title}</div>
          <div className="kg-view-description">{fixture.description}</div>
        </div>
      </div>
    </div>
  )
}
