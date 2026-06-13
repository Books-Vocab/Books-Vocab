import type { ScenarioId } from '../../harness/scenarios'
import { KG_EMPTY_STATE_FIXTURES } from './fixtures'
import './kg-empty-state.css'

/**
 * KG Empty State surface — iOS `AppEmptyStateContent`（style=.vocab(skin)）經由
 * `KGVocabEmptyState` resolver 解出 title/description/icon/CTA 的 web 鏡像。
 *
 * Scene（KGVocabEmptyStateScenarios.EmptyStateScene, layout=.fill）：
 *   VStack[ Spacer · AppEmptyStateContent.padding(.horizontal,32) · Spacer ]
 *   .frame(maxWidth/maxHeight:.infinity).background(pageBackground)
 * Content：VStack(spacing 14, maxWidth ∞)[ symbolLarge icon(tertiary) ·
 *   sectionTitle title(serif 18 bold, primary) · body description(sans 15,
 *   secondary, centered) · （outline action button：icon+title）]。
 *
 * catalog ref = .fill 全裝置幀（1179×2556，corner srgba(247,246,243,1)=page-bg，
 * 不透明）→ 全 phone-frame 捕捉（無 crop=component、無 transparent）：surface
 * 撐滿 phone-frame、bg=page-bg、內容垂直置中、content 水平內縮 32。
 */
export function KgEmptyStateScreen({ scenario }: { scenario: ScenarioId<'kg-empty-state'> }) {
  const fixture = KG_EMPTY_STATE_FIXTURES[scenario]
  const Icon = fixture.icon
  const Action = fixture.action
  return (
    <div className="kg-empty-state-surface">
      <div className="kg-empty-state-content">
        <Icon className="kg-empty-state-icon" size={30} strokeWidth={1.4} />
        <div className="kg-empty-state-title">{fixture.title}</div>
        <div className="kg-empty-state-description">{fixture.description}</div>
        {Action ? (
          <button type="button" className="kg-empty-state-action">
            <Action.icon className="kg-empty-state-action-icon" size={16} />
            <span>{Action.title}</span>
          </button>
        ) : null}
      </div>
    </div>
  )
}
