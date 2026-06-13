import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_EMPTY_STATE_FIXTURES, type EmptyStateFixture } from './fixtures'
import './vocab-empty-state.css'

/**
 * Vocab · Empty State surface — iOS `VocabEmptyStateContent` /
 * `VocabEmptyStateCard`（皆委派 `AppEmptyStateContent` / `AppEmptyStateCard`，
 * style = `.vocab(skin)`）的 web 鏡像。
 *
 * Content：VStack(spacing 14, maxWidth ∞)[symbolLarge icon · sectionTitle title ·
 * body description ·（body guidance@0.7）·（outline action button）]。
 * Card：AppSectionCard(.vocab) 包 Content，Content 額外 .padding(.vertical, 12)。
 *
 * catalog 元件 scene 畫布透明（component-isolated，scene = 元件
 * .frame(maxWidth:.infinity).padding(24)）：`?crop=component` 令 surface 透明、
 * shots `transparent:true` omitBackground 截圖 → web 與 ref 同為元件-over-transparent。
 */
export function VocabEmptyStateScreen({ scenario }: { scenario: ScenarioId<'vocab-empty-state'> }) {
  const fixture = VOCAB_EMPTY_STATE_FIXTURES[scenario]
  return (
    <div className="vocab-empty-state-surface">
      {fixture.kind === 'card' ? (
        <div className="vocab-empty-state-card">
          <EmptyStateContent fixture={fixture} inCard />
        </div>
      ) : (
        <EmptyStateContent fixture={fixture} />
      )}
    </div>
  )
}

function EmptyStateContent({ fixture, inCard = false }: { fixture: EmptyStateFixture; inCard?: boolean }) {
  const Icon = fixture.icon
  const Action = fixture.action
  return (
    <div className="vocab-empty-state-content" data-in-card={inCard ? '1' : undefined}>
      <Icon className="vocab-empty-state-icon" size={30} strokeWidth={1.4} />
      <div className="vocab-empty-state-title">{fixture.title}</div>
      <div className="vocab-empty-state-description">{fixture.description}</div>
      {fixture.guidance ? <div className="vocab-empty-state-guidance">{fixture.guidance}</div> : null}
      {Action ? (
        <button type="button" className="vocab-empty-state-action">
          <Action.icon className="vocab-empty-state-action-icon" size={16} />
          <span>{Action.title}</span>
        </button>
      ) : null}
    </div>
  )
}
