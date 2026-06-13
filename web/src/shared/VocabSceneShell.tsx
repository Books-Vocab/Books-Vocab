import type { ReactNode } from 'react'
import {
  ArrowClockwiseIcon,
  ExclamationmarkTriangleIcon,
  SparklesIcon,
} from './icons'
import './vocab-scene-shell.css'

/**
 * 可複用的 VocabSceneShell 容器 — 對齊 iOS VocabSceneShell 四態：
 * loading / loadingSkeleton / empty / error / content。
 * 殼層內 surface（Notebook/Vocabulary/TodayReview）在 shell=1 時用此包裹非 ready 態。
 *
 * 使用方式：
 *   <VocabSceneShell status={store.status} onRetry={store.retry}>
 *     <ActualContent />
 *   </VocabSceneShell>
 */

export type SceneStatus = 'loading' | 'loadingSkeleton' | 'empty' | 'error' | 'content'

export interface VocabSceneShellProps {
  status: SceneStatus
  onRetry?: () => void
  children: ReactNode
  /** empty 態客製（預設 vocabulary 風格）。 */
  emptyIcon?: ReactNode
  emptyTitle?: string
  emptyDescription?: string
  emptyAction?: { title: string; icon: ReactNode; onClick: () => void }
  /** error 態客製文案。 */
  errorTitle?: string
  errorDescription?: string
  errorRetryTitle?: string
}

export function VocabSceneShell({
  status,
  onRetry,
  children,
  emptyIcon,
  emptyTitle = '尚無已收錄單字',
  emptyDescription = '同步完成後，這裡會顯示你的雲端單字。',
  emptyAction,
  errorTitle = '無法載入單字',
  errorDescription = '請檢查網路連線後重試。',
  errorRetryTitle = '重試',
}: VocabSceneShellProps) {
  if (status === 'content') return <>{children}</>

  const layout = status === 'loadingSkeleton' ? 'list' : 'center'
  const canvas = 'opaque'

  return (
    <div className="vocab-scene-shell-surface" data-layout={layout} data-canvas={canvas}>
      {status === 'loading' && (
        <MessageCard
          icon={<ArrowClockwiseIcon className="vss-message-icon" size={12} strokeWidth={1.6} />}
          title="載入中…"
        >
          <Spinner />
        </MessageCard>
      )}
      {status === 'loadingSkeleton' && (
        <>
          {Array.from({ length: 6 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </>
      )}
      {status === 'empty' && (
        <div className="vss-empty-card">
          <div className="vss-empty-content">
            {emptyIcon ?? <SparklesIcon className="vss-empty-icon" size={30} strokeWidth={1.4} />}
            <div className="vss-empty-title">{emptyTitle}</div>
            <div className="vss-empty-description">{emptyDescription}</div>
            {emptyAction ? (
              <button type="button" className="vss-empty-action" onClick={emptyAction.onClick}>
                {emptyAction.icon}
                <span>{emptyAction.title}</span>
              </button>
            ) : null}
          </div>
        </div>
      )}
      {status === 'error' && (
        <MessageCard
          icon={<ExclamationmarkTriangleIcon className="vss-message-icon" size={12} strokeWidth={1.6} />}
          title={errorTitle}
          description={errorDescription}
        >
          {onRetry ? (
            <button type="button" className="vss-retry-button" onClick={onRetry}>
              {errorRetryTitle}
            </button>
          ) : null}
        </MessageCard>
      )}
    </div>
  )
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
