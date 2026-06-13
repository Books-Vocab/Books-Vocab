import type { ScenarioId } from '../../harness/scenarios'
import { SyncApiStore } from './SyncApiStore'
import { SYNC_FIXTURES } from './fixtures'
import type { PendingRow, PipelineStep, StepStatus, SyncState } from './fixtures'
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

/**
 * 鏡像 ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncPresenter.swift
 * （+Header / +ActionArea）。catalog scene = .fill 全幀、opaque page-bg → 全 phone-frame
 * 捕捉（無 crop、無 transparent，同 bookshelf pattern）。
 *
 * 五個 scenario 皆 isLoggedIn=true / isConnected=true，依 phase × failureKind 切換
 * hero / pending list / steps / summary / action。
 *
 * 兩條路徑（P6）：
 *  - 預設（parity capture rig 唯一路徑，無 ?shell）：靜態 fixture 渲染，按鈕 no-op，
 *    DOM 逐位元凍結 —— parity 對拍只比首屏靜態像素，此分支永不更動。
 *  - ?shell=1（window.location.search opt-in）：掛 SyncApiStore，由真實
 *    SyncCoordinator（web/src/sync）驅動 Start/Cancel/Retry + step timeline。
 *    rig 的 surface-view 路徑永不帶 ?shell（shell=1 走 AppShell），故 fixture
 *    分支與 parity capture 完全不受影響。
 */
function isShellMode(): boolean {
  if (typeof window === 'undefined') return false
  return new URLSearchParams(window.location.search).get('shell') === '1'
}

export function SyncScreen({ scenario }: { scenario: ScenarioId<'sync'> }) {
  // shell 分支：真實 coordinator。fixture/parity 分支以下完全不動。
  if (isShellMode()) {
    return <SyncApiStore />
  }

  const state = SYNC_FIXTURES[scenario] ?? SYNC_FIXTURES.ready

  const showPending = state.phase === 'ready' && state.pendingRows.length > 0
  const showSteps = state.steps.length > 0
  const showSummary = state.summaryText.length > 0

  return (
    <div className="sync">
      <header className="sync-nav">
        <h1 className="sync-nav-title">同步</h1>
      </header>

      <div className="sync-scroll">
        <div className="sync-content">
          <div className="sync-header">
            <Header state={state} />
          </div>

          {showPending && <PendingList rows={state.pendingRows} />}
          {showSteps && <Steps steps={state.steps} />}
          {showSummary && <SummaryCard state={state} />}
        </div>
      </div>

      <ActionArea state={state} />
    </div>
  )
}

/* === Header（VocabStatusHero）=== */
function Header({ state }: { state: SyncState }) {
  if (state.phase === 'ready') {
    return (
      <div className="sync-hero">
        <span className="sync-hero-icon" style={{ color: 'var(--accent)' }}>
          <SyncIcon size={44} strokeWidth={2} />
        </span>
        <h2 className="sync-hero-title">
          {state.pendingCount === 0 ? '強制同步到雲端' : `${state.pendingCount} 個待處理動作`}
        </h2>
        {(state.addCount > 0 || state.deleteCount > 0) && (
          <div className="sync-hero-badges">
            {state.addCount > 0 && (
              <span className="sync-tone-chip" data-tone="success">
                {state.addCount} 新增
              </span>
            )}
            {state.deleteCount > 0 && (
              <span className="sync-tone-chip" data-tone="destructive">
                {state.deleteCount} 刪除
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
        {/* ProgressView(.large) */}
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

/* === Pending list（ready）=== */
function PendingList({ rows }: { rows: PendingRow[] }) {
  return (
    <div className="sync-card">
      {rows.map((row, i) => (
        <div key={row.word}>
          <div className="sync-pending-row">
            <div className="sync-wordrow">
              <div className="sync-wordrow-headline">
                <span className="sync-word" data-tone={row.action === 'delete' ? 'destructive' : 'primary'}>
                  {row.word}
                </span>
                <span className="sync-pos">{row.pos}</span>
              </div>
              <span className="sync-translation">{row.translation}</span>
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

/* === Steps === */
function Steps({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="sync-card">
      <div className="sync-steps">
        {steps.map((s, i) => (
          <div key={s.id}>
            <StepRow step={s} />
            {i < steps.length - 1 && <div className="sync-step-divider" />}
          </div>
        ))}
      </div>
    </div>
  )
}

function StatusSymbol({ status }: { status: StepStatus }) {
  switch (status) {
    case 'done':
      return <CheckmarkCircleFillIcon size={18} />
    case 'running':
      return <ActivityIndicator size={18} />
    case 'error':
      return <XmarkCircleFillIcon size={18} />
    case 'waiting':
    default:
      return <CircleIcon size={18} />
  }
}

function StepRow({ step }: { step: PipelineStep }) {
  const isWaiting = step.status === 'waiting'
  const detail = isWaiting ? '' : step.detail
  const detailTone = step.status === 'error' ? 'error' : 'secondary'
  const showProgress = step.status === 'running' && step.total > 0

  return (
    <div className="sync-timeline-row">
      <span className="sync-step-symbol" data-status={step.status}>
        <StatusSymbol status={step.status} />
      </span>
      <div className="sync-step-body">
        <div className="sync-step-head">
          <span className="sync-step-title" data-tone={isWaiting ? 'waiting' : 'normal'}>
            {step.label}
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

/* === Summary card（AppStateMessageCard .vocab）=== */
function SummaryCard({ state }: { state: SyncState }) {
  const title =
    state.failureKind === 'partial'
      ? '有些項目需要再試一次'
      : state.failureKind === 'full'
        ? '同步沒有完成'
        : state.phase === 'completed'
          ? '同步完成'
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
      <p className="sync-summary-desc">{state.summaryText}</p>
    </div>
  )
}

/* === Action area === */
function ActionArea({ state }: { state: SyncState }) {
  if (state.phase === 'ready') {
    return (
      <div className="sync-action">
        <button type="button" className="sync-action-button" data-style="primary" data-width="fill">
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
        <button type="button" className="sync-action-button" data-style="neutral" data-width="fill">
          取消
        </button>
      </div>
    )
  }

  if (state.phase === 'completed') {
    return (
      <div className="sync-action">
        <button type="button" className="sync-action-button" data-style="primary" data-width="hug">
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
      >
        <span className="sync-action-button-icon">
          <RefreshIcon size={15} strokeWidth={2} />
        </span>
        {isPartial ? '重試失敗項目' : '重試'}
      </button>
    </div>
  )
}
