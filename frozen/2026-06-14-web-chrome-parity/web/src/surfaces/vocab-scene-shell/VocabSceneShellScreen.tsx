import type { ReactNode } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_SCENE_SHELL_FIXTURES, type SceneShellFixture } from './fixtures'
import './vocab-scene-shell.css'

/**
 * Vocab · Scene Shell surface — iOS `VocabSceneShell`（Vocabulary 統一四態容器：
 * loading / loadingSkeleton / empty / error / content）的 web 鏡像。
 *
 * 殼語意（VocabSceneShell.swift）：
 *   loading/empty/error → `centeredWrapper`（VStack{Spacer;card;Spacer}
 *     .padding(cardBlockPadding=24).vocabCanvasBackground()）= 垂直置中卡片。
 *   loadingSkeleton     → ScrollView{VStack(spacing s3=12){rowCount× AppSkeletonCard}}
 *     .padding(24).vocabCanvasBackground() = 頂部對齊骨架列。
 *   content             → pass-through（範例卡，確認殼不污染 content）。
 *
 * 卡片：
 *   message（loading/error）= AppStateMessageCard.vocab：VStack(s2)[HStack(baseline,s2)
 *     [iconSmall/accent · body-semibold/primary · Spacer] · (caption desc) · accessory]，
 *     card padding(h14,v12) + cardBackground + radius control(sm) + cardBorder 1px。
 *   empty = VocabEmptyStateCard.vocab（同 vocab-empty-state surface 幾何）。
 *   skeleton = AppSkeletonCard：HStack(s3)[VStack(s2)[line 180×14 · 2× line ∞×10]]
 *     padding cardOuterPadding(24) + cardBackground + radius md + cardBorder 1px。
 *
 * vocabCanvasBackground = pageBackground（**不透明**）→ scene 為不透明全幀，
 * 故 shots `transparent:false`、surface 背景 = --page-bg（非透明 component-crop）。
 */
export function VocabSceneShellScreen({ scenario }: { scenario: ScenarioId<'vocab-scene-shell'> }) {
  const fixture = VOCAB_SCENE_SHELL_FIXTURES[scenario]
  const layout = fixture.phase === 'loadingSkeleton' ? 'list' : 'center'
  // content 態 = iOS `.content` pass-through，**不**套 vocabCanvasBackground → ref 透明
  // （alpha-mean 0.008）；其餘 5 態套 pageBackground（不透明）。故 content surface 透明。
  const canvas = fixture.phase === 'content' ? 'transparent' : 'opaque'
  return (
    <div className="vocab-scene-shell-surface" data-layout={layout} data-canvas={canvas}>
      {renderPhase(fixture)}
    </div>
  )
}

function renderPhase(fixture: SceneShellFixture) {
  switch (fixture.phase) {
    case 'loading': {
      const Icon = fixture.icon
      return (
        <MessageCard icon={<Icon className="vss-message-icon" size={12} strokeWidth={1.6} />} title={fixture.title}>
          <Spinner />
        </MessageCard>
      )
    }
    case 'error': {
      const Icon = fixture.icon
      return (
        <MessageCard
          icon={<Icon className="vss-message-icon" size={12} strokeWidth={1.6} />}
          title={fixture.title}
          description={fixture.description}
        >
          <button type="button" className="vss-retry-button">{fixture.retryTitle}</button>
        </MessageCard>
      )
    }
    case 'empty': {
      const Icon = fixture.icon
      const Action = fixture.action
      return (
        <div className="vss-empty-card">
          <div className="vss-empty-content">
            <Icon className="vss-empty-icon" size={30} strokeWidth={1.4} />
            <div className="vss-empty-title">{fixture.title}</div>
            <div className="vss-empty-description">{fixture.description}</div>
            {Action ? (
              <button type="button" className="vss-empty-action">
                <Action.icon className="vss-empty-action-icon" size={16} />
                <span>{Action.title}</span>
              </button>
            ) : null}
          </div>
        </div>
      )
    }
    case 'loadingSkeleton':
      return (
        <>
          {Array.from({ length: fixture.rowCount }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </>
      )
    case 'content':
      return (
        <div className="vss-content">
          <div className="vss-content-word">serendipity</div>
          <div className="vss-content-pos">機緣巧合 · n.</div>
          <div className="vss-content-def">
            The fortunate happenstance of finding something good without looking for it.
          </div>
        </div>
      )
  }
}

function MessageCard({
  icon,
  title,
  description,
  children,
}: {
  icon: ReactNode
  title: string
  description?: string
  children?: ReactNode
}) {
  return (
    <div className="vss-message-card">
      <div className="vss-message-content">
        <div className="vss-message-head">
          {icon}
          <div className="vss-message-title">{title}</div>
          <div className="vss-message-spacer" />
        </div>
        {description ? <div className="vss-message-desc">{description}</div> : null}
        {children}
      </div>
    </div>
  )
}

/** iOS ProgressView(.small) — UIActivityIndicator 風格 12-輻條漸隱環（~16px）。 */
function Spinner() {
  const spokes = 12
  return (
    <svg className="vss-spinner" viewBox="0 0 16 16" width={16} height={16} aria-hidden="true">
      {Array.from({ length: spokes }, (_, i) => {
        const angle = (i * 360) / spokes
        const opacity = 0.25 + (0.75 * i) / (spokes - 1)
        return (
          <rect
            key={i}
            x={7.3}
            y={1.4}
            width={1.4}
            height={3.6}
            rx={0.7}
            fill="currentColor"
            opacity={opacity}
            transform={`rotate(${angle} 8 8)`}
          />
        )
      })}
    </svg>
  )
}

/** AppSkeletonCard：HStack[VStack[title-line 180×14, 2× body-line ∞×10]]。 */
function SkeletonCard() {
  return (
    <div className="vss-skeleton-card">
      <div className="vss-skeleton-lines">
        <div className="vss-skeleton-line vss-skeleton-line--title" />
        <div className="vss-skeleton-line vss-skeleton-line--body" />
        <div className="vss-skeleton-line vss-skeleton-line--body" />
      </div>
    </div>
  )
}
