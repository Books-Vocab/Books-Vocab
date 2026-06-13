// Live, coordinator-driven Sync screen (shell branch).
//
// This is the SIBLING ...ApiStore variant required by the parity invariant: the
// fixture branch in SyncScreen.tsx stays byte-identical; this view only renders
// when ?shell=1 is present in the URL (gated in SyncScreen). It reuses sync.css
// (same class names → same look) and drives every visual off the real
// SyncCoordinator state machine (web/src/sync) instead of static fixtures.
//
// Mock-first: useSyncCoordinator() defaults to createSyncApi() → createApiClient()
// in mock mode, so Start/Cancel/Retry exercise real client calls offline.

import { useSyncCoordinator, STEP_LABELS } from '../../sync'
import type { CoordinatorState, OutboxEntry, StepProgress } from '../../sync'
import {
  ActivityIndicator,
  CheckmarkCircleFillIcon,
  CircleIcon,
  ExclamationCirclePathIcon,
  MinusCircleIcon,
  RefreshIcon,
  SyncIcon,
  UturnBackwardIcon,
  WarningTriangleFillIcon,
  XmarkCircleFillIcon,
} from './icons'
import './sync.css'

/** Seed a couple of pending mutations so the live screen has something to sync
 *  on first paint (mirrors the fixture `ready` state's two adds + one delete).
 *  Idempotent: the outbox dedups by (notebook + raw word + action). */
function useSeededCoordinator(notebookId: string) {
  const sync = useSyncCoordinator({ notebookId })
  // Seed once per coordinator instance (queue* is idempotent via outbox dedup).
  if (sync.state.phase === 'ready' && sync.state.pending.length === 0) {
    sync.coordinator.queueAdd({ word: 'ineffable', translation: '難以言喻的' })
    sync.coordinator.queueAdd({ word: 'ephemeral', translation: '短暫的' })
    sync.coordinator.queueDelete('obsolete')
  }
  return sync
}

export function SyncApiStore({ notebookId = 'default' }: { notebookId?: string }) {
  const { state, start, cancel, retry } = useSeededCoordinator(notebookId)

  const adds = state.pending.filter((e) => e.action === 'add')
  const deletes = state.pending.filter((e) => e.action === 'delete')
  const showPending = state.phase === 'ready' && state.pending.length > 0
  // steps are meaningful once a run has started (any non-waiting step).
  const showSteps =
    state.phase !== 'ready' && state.steps.some((s) => s.status !== 'waiting')
  const summaryText = summaryFor(state)

  return (
    <div className="sync" data-live="1">
      <header className="sync-nav">
        <h1 className="sync-nav-title">同步</h1>
      </header>

      <div className="sync-scroll">
        <div className="sync-content">
          <div className="sync-header">
            <LiveHeader state={state} addCount={adds.length} deleteCount={deletes.length} />
          </div>

          {showPending && <LivePendingList rows={state.pending} />}
          {showSteps && <LiveSteps steps={state.steps} />}
          {summaryText.length > 0 && <LiveSummary state={state} summaryText={summaryText} />}
        </div>
      </div>

      <LiveActionArea state={state} onStart={start} onCancel={cancel} onRetry={retry} />
    </div>
  )
}

function LiveHeader({
  state,
  addCount,
  deleteCount,
}: {
  state: CoordinatorState
  addCount: number
  deleteCount: number
}) {
  if (state.phase === 'ready') {
    const pendingCount = state.pending.length
    return (
      <div className="sync-hero">
        <span className="sync-hero-icon" style={{ color: 'var(--accent)' }}>
          <SyncIcon size={44} strokeWidth={2} />
        </span>
        <h2 className="sync-hero-title">
          {pendingCount === 0 ? '強制同步到雲端' : `${pendingCount} 個待處理動作`}
        </h2>
        {(addCount > 0 || deleteCount > 0) && (
          <div className="sync-hero-badges">
            {addCount > 0 && (
              <span className="sync-tone-chip" data-tone="success">
                {addCount} 新增
              </span>
            )}
            {deleteCount > 0 && (
              <span className="sync-tone-chip" data-tone="destructive">
                {deleteCount} 刪除
              </span>
            )}
          </div>
        )}
      </div>
    )
  }

  if (state.phase === 'running') {
    return (
      <div className="sync-hero">
        <span className="sync-hero-icon" style={{ color: 'var(--accent)' }}>
          <SyncIcon size={44} strokeWidth={2} />
        </span>
        <h2 className="sync-hero-title">同步中…</h2>
        <p className="sync-hero-desc">離開後同步將繼續在背景執行，可隨時返回查看進度</p>
        <span className="sync-hero-icon" style={{ color: 'var(--text-secondary)' }}>
          <ActivityIndicator size={32} />
        </span>
      </div>
    )
  }

  if (state.phase === 'completed') {
    return (
      <div className="sync-hero">
        <span className="sync-hero-icon" style={{ color: 'var(--success)' }}>
          <CheckmarkCircleFillIcon size={44} />
        </span>
        <h2 className="sync-hero-title">同步完成</h2>
      </div>
    )
  }

  // failed
  if (state.failureKind === 'partial') {
    return (
      <div className="sync-hero">
        <span className="sync-hero-icon" style={{ color: 'var(--warning)' }}>
          <ExclamationCirclePathIcon size={44} strokeWidth={2} />
        </span>
        <h2 className="sync-hero-title">部分同步完成</h2>
        <p className="sync-hero-desc">已完成的步驟會保留，失敗項目可直接重試。</p>
      </div>
    )
  }

  return (
    <div className="sync-hero">
      <span className="sync-hero-icon" style={{ color: 'var(--destructive)' }}>
        <WarningTriangleFillIcon size={44} />
      </span>
      <h2 className="sync-hero-title">同步失敗</h2>
      <p className="sync-hero-desc">請檢查網路、登入狀態或伺服器健康後再試。</p>
    </div>
  )
}

function LivePendingList({ rows }: { rows: OutboxEntry[] }) {
  return (
    <div className="sync-card">
      {rows.map((row, i) => (
        <div key={row.id}>
          <div className="sync-pending-row">
            <div className="sync-wordrow">
              <div className="sync-wordrow-headline">
                <span
                  className="sync-word"
                  data-tone={row.action === 'delete' ? 'destructive' : 'primary'}
                >
                  {row.word}
                </span>
              </div>
              {row.entry?.translation && (
                <span className="sync-translation">{row.entry.translation}</span>
              )}
            </div>
            <div
              className="sync-accessory"
              data-tone={row.action === 'delete' ? 'destructive' : 'secondary'}
              aria-label={row.action === 'delete' ? '復原刪除' : '移除待收錄'}
            >
              {row.action === 'delete' ? (
                <UturnBackwardIcon size={15} />
              ) : (
                <MinusCircleIcon size={15} />
              )}
            </div>
          </div>
          {i < rows.length - 1 && <div className="sync-divider" />}
        </div>
      ))}
    </div>
  )
}

function LiveSteps({ steps }: { steps: StepProgress[] }) {
  return (
    <div className="sync-card">
      <div className="sync-steps">
        {steps.map((s, i) => (
          <div key={s.id}>
            <LiveStepRow step={s} />
            {i < steps.length - 1 && <div className="sync-step-divider" />}
          </div>
        ))}
      </div>
    </div>
  )
}

function LiveStatusSymbol({ status }: { status: StepProgress['status'] }) {
  switch (status) {
    case 'done':
      return <CheckmarkCircleFillIcon size={18} />
    case 'running':
      return <ActivityIndicator size={18} />
    case 'error':
      return <XmarkCircleFillIcon size={18} />
    case 'skipped':
    case 'waiting':
    default:
      return <CircleIcon size={18} />
  }
}

function LiveStepRow({ step }: { step: StepProgress }) {
  const isWaiting = step.status === 'waiting'
  const detail = isWaiting ? '' : step.detail
  const detailTone = step.status === 'error' ? 'error' : 'secondary'
  const showProgress = step.status === 'running' && step.total > 0

  return (
    <div className="sync-timeline-row">
      <span className="sync-step-symbol" data-status={step.status}>
        <LiveStatusSymbol status={step.status} />
      </span>
      <div className="sync-step-body">
        <div className="sync-step-head">
          <span className="sync-step-title" data-tone={isWaiting ? 'waiting' : 'normal'}>
            {STEP_LABELS[step.id]}
          </span>
          {showProgress && (
            <span className="sync-step-trailing">
              <span className="sync-step-progress">
                {step.current}/{step.total}
              </span>
            </span>
          )}
        </div>
        {detail.length > 0 && (
          <span className="sync-step-detail" data-tone={detailTone}>
            {detail}
          </span>
        )}
      </div>
    </div>
  )
}

function summaryFor(state: CoordinatorState): string {
  if (state.phase === 'failed') {
    return state.failureKind === 'partial'
      ? '部分項目未成功同步，可直接再次重試。'
      : '同步未完成，請稍後再試。'
  }
  return ''
}

function LiveSummary({ state, summaryText }: { state: CoordinatorState; summaryText: string }) {
  const title =
    state.failureKind === 'partial'
      ? '有些項目需要再試一次'
      : state.failureKind === 'full'
        ? '同步沒有完成'
        : '同步摘要'
  const Icon = state.failureKind === 'partial' ? ExclamationCirclePathIcon : WarningTriangleFillIcon
  return (
    <div className="sync-summary">
      <div className="sync-summary-head">
        <span className="sync-summary-icon">
          <Icon size={12} strokeWidth={2} />
        </span>
        <h3 className="sync-summary-title">{title}</h3>
      </div>
      <p className="sync-summary-desc">{summaryText}</p>
    </div>
  )
}

function LiveActionArea({
  state,
  onStart,
  onCancel,
  onRetry,
}: {
  state: CoordinatorState
  onStart: () => void
  onCancel: () => void
  onRetry: () => void
}) {
  if (state.phase === 'ready') {
    return (
      <div className="sync-action">
        <button
          type="button"
          className="sync-action-button"
          data-style="primary"
          data-width="fill"
          onClick={onStart}
        >
          <span className="sync-action-button-icon">
            <SyncIcon size={15} strokeWidth={2} />
          </span>
          開始同步
        </button>
      </div>
    )
  }

  if (state.phase === 'running') {
    return (
      <div className="sync-action">
        <button
          type="button"
          className="sync-action-button"
          data-style="neutral"
          data-width="fill"
          onClick={onCancel}
        >
          取消
        </button>
      </div>
    )
  }

  if (state.phase === 'completed') {
    return (
      <div className="sync-action">
        <button
          type="button"
          className="sync-action-button"
          data-style="primary"
          data-width="hug"
          onClick={onStart}
        >
          完成
        </button>
      </div>
    )
  }

  // failed
  const isPartial = state.failureKind === 'partial'
  return (
    <div className="sync-action">
      <button
        type="button"
        className="sync-action-button"
        data-style={isPartial ? 'neutral' : 'warning'}
        data-width="fill"
        onClick={onRetry}
      >
        <span className="sync-action-button-icon">
          <RefreshIcon size={15} strokeWidth={2} />
        </span>
        {isPartial ? '重試失敗項目' : '重試'}
      </button>
    </div>
  )
}
