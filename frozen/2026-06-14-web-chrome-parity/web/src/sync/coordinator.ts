// SyncCoordinator — the orchestrator the visual harness was missing.
//
// Runs the fixed pipeline (upload_delete → upload_add → trigger → push_review →
// pull) for one notebook, driving the local `syncStatus × actionType` state
// machine (stateMachine.ts) against the SyncApi port (api.ts). Emits
// step-progress + phase events; supports cancel + retry-failed-only.
//
// Per-notebook isolation: one coordinator instance == one notebookId; it only
// ever reads/writes that notebook's outbox slice.
//
// Pure-enough to unit-test under node: inject a fake SyncApi + an in-memory
// KVStorage and assert on the emitted event stream / outbox end-state. No React,
// no timers, no jsdom.

import { Outbox } from './outbox'
import {
  applyDeleteReconcile,
  reconcileAdds,
  resetFailedToPending,
} from './stateMachine'
import type {
  CoordinatorState,
  KVStorage,
  OutboxEntry,
  StepProgress,
  SyncApi,
  SyncEvent,
  SyncFailureKind,
  SyncListener,
  SyncPhase,
  SyncStepId,
} from './types'
import type { ReviewEventEntry, ReviewStateEntry } from '../api/types'

const STEP_LABELS: Record<SyncStepId, string> = {
  upload_delete: '刪除 Books & Vocab 單字',
  upload_add: '上傳新單字',
  trigger: '觸發背景 AI 處理',
  push_review: '上傳複習進度',
  pull: '下載單字至本地',
}

const STEP_ORDER: SyncStepId[] = [
  'upload_delete',
  'upload_add',
  'trigger',
  'push_review',
  'pull',
]

function freshSteps(): StepProgress[] {
  return STEP_ORDER.map((id) => ({
    id,
    status: 'waiting',
    current: 0,
    total: 0,
    detail: '',
  }))
}

export interface CoordinatorOptions {
  notebookId: string
  api: SyncApi
  storage: KVStorage
  /** local review progress to push (optional; empty = no-op push step). */
  reviewEvents?: ReviewEventEntry[]
  reviewStates?: ReviewStateEntry[]
}

/** Signals a run was cancelled cooperatively between steps. */
class CancelledError extends Error {
  constructor() {
    super('sync cancelled')
    this.name = 'CancelledError'
  }
}

export class SyncCoordinator {
  readonly notebookId: string
  private readonly api: SyncApi
  private readonly outbox: Outbox
  private reviewEvents: ReviewEventEntry[]
  private reviewStates: ReviewStateEntry[]

  private listeners = new Set<SyncListener>()
  private steps: StepProgress[] = freshSteps()
  private phase: SyncPhase = 'ready'
  private failureKind: SyncFailureKind = null
  private cancelRequested = false
  private running = false

  constructor(opts: CoordinatorOptions) {
    this.notebookId = opts.notebookId
    this.api = opts.api
    this.outbox = new Outbox(opts.storage)
    this.reviewEvents = opts.reviewEvents ?? []
    this.reviewStates = opts.reviewStates ?? []
  }

  // ── subscription ──────────────────────────────────────────────────────────

  subscribe(fn: SyncListener): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private emit(event: SyncEvent): void {
    for (const fn of this.listeners) fn(event)
  }

  // ── observable snapshot ─────────────────────────────────────────────────────

  getState(): CoordinatorState {
    return {
      notebookId: this.notebookId,
      phase: this.phase,
      failureKind: this.failureKind,
      steps: this.steps.map((s) => ({ ...s })),
      pending: this.outbox.entries(this.notebookId).filter((e) => e.status !== 'synced'),
    }
  }

  private emitState(): void {
    this.emit({ type: 'state', state: this.getState() })
  }

  private setPhase(phase: SyncPhase, failureKind: SyncFailureKind = null): void {
    this.phase = phase
    this.failureKind = failureKind
    this.emit({ type: 'phase', phase, failureKind })
    this.emitState()
  }

  private patchStep(id: SyncStepId, patch: Partial<StepProgress>): void {
    const idx = this.steps.findIndex((s) => s.id === id)
    if (idx < 0) return
    this.steps[idx] = { ...this.steps[idx], ...patch }
    this.emit({ type: 'step', step: { ...this.steps[idx] } })
    this.emitState()
  }

  private checkpoint(): void {
    if (this.cancelRequested) throw new CancelledError()
  }

  // ── public commands ─────────────────────────────────────────────────────────

  /** Enqueue a local add (pending+add). Mirrors restorePendingEntry(). */
  queueAdd(entry: import('../api/types').VocabEntry): OutboxEntry {
    const e = this.outbox.enqueueAdd(this.notebookId, entry)
    this.emitState()
    return e
  }

  /** Enqueue a local delete (pending+delete). Mirrors queueDelete(). */
  queueDelete(word: string): OutboxEntry {
    const e = this.outbox.enqueueDelete(this.notebookId, word)
    this.emitState()
    return e
  }

  /** Cooperative cancel — takes effect at the next inter-step checkpoint. */
  cancel(): void {
    if (this.running) this.cancelRequested = true
  }

  /** Full run: flips failed→pending first (SoT §同步失敗後重試 step 3). */
  async start(): Promise<CoordinatorState> {
    return this.run({ retryOnly: false })
  }

  /** Retry: re-run with only the still-outstanding (pending/failed) entries. */
  async retry(): Promise<CoordinatorState> {
    return this.run({ retryOnly: true })
  }

  // ── the pipeline ─────────────────────────────────────────────────────────────

  private async run(_opts: { retryOnly: boolean }): Promise<CoordinatorState> {
    if (this.running) return this.getState()
    this.running = true
    this.cancelRequested = false
    this.steps = freshSteps()
    this.setPhase('running')

    // SoT §同步失敗後重試: flip failed→pending so they retry this run.
    {
      const reset = this.outbox.entries(this.notebookId).map(resetFailedToPending)
      this.outbox.replace(this.notebookId, reset)
    }

    let anyFailure = false
    let anySuccess = false

    try {
      anyFailure = (await this.stepDeletes()) || anyFailure
      this.checkpoint()
      const addOutcome = await this.stepAdds()
      anyFailure = addOutcome.failed || anyFailure
      anySuccess = addOutcome.success || anySuccess
      this.checkpoint()
      // trigger is a SOFT step: its result never flips the overall run verdict
      // (background enrichment failing must not fail the whole sync). We still
      // await it so its step event + checkpoint fire in order.
      await this.stepTrigger()
      this.checkpoint()
      anyFailure = !(await this.stepPushReview()) || anyFailure
      this.checkpoint()
      anyFailure = !(await this.stepPull()) || anyFailure

      const stillPending = this.outbox
        .entries(this.notebookId)
        .some((e) => e.status !== 'synced')

      if (anyFailure || stillPending) {
        // partial = some steps succeeded; full = nothing landed at all.
        const kind: SyncFailureKind = anySuccess || !stillPending ? 'partial' : 'full'
        this.setPhase('failed', kind)
      } else {
        this.setPhase('completed')
      }
    } catch (err) {
      if (err instanceof CancelledError) {
        // Cancel returns to a re-runnable ready phase; queued entries intact.
        this.setPhase('ready')
      } else {
        this.setPhase('failed', anySuccess ? 'partial' : 'full')
      }
    } finally {
      this.running = false
      this.cancelRequested = false
    }
    return this.getState()
  }

  /** upload_delete — POST batch-delete; three-bucket reconcile. Returns true on
   *  any failure. If the batch-delete route is not wired, the step is skipped. */
  private async stepDeletes(): Promise<boolean> {
    const deletes = this.outbox
      .entries(this.notebookId)
      .filter((e) => e.action === 'delete' && e.status !== 'synced')
    if (deletes.length === 0) {
      this.patchStep('upload_delete', { status: 'done', detail: '' })
      return false
    }
    if (!this.api.batchDelete) {
      // No batch-delete route in the frozen foundation — honest skip, retried
      // once the route lands (see api.ts note). Does NOT count as a failure.
      this.patchStep('upload_delete', {
        status: 'skipped',
        total: deletes.length,
        detail: '批次刪除尚未接線',
      })
      return false
    }
    this.patchStep('upload_delete', { status: 'running', total: deletes.length })
    try {
      const result = await this.api.batchDelete(
        deletes.map((e) => e.word),
        this.notebookId,
      )
      const { remaining } = applyDeleteReconcile(deletes, result)
      const others = this.outbox
        .entries(this.notebookId)
        .filter((e) => !(e.action === 'delete' && e.status !== 'synced'))
      this.outbox.replace(this.notebookId, [...others, ...remaining])
      const resolved = deletes.length - remaining.length
      const failed = remaining.length
      this.patchStep('upload_delete', {
        status: failed > 0 ? 'error' : 'done',
        current: resolved,
        detail:
          failed > 0
            ? `已刪除 ${resolved} 個，${failed} 個失敗`
            : `已刪除 ${resolved} 個單字`,
      })
      return failed > 0
    } catch {
      // Whole batch failed → all stay failed+delete (still hidden).
      const others = this.outbox
        .entries(this.notebookId)
        .filter((e) => !(e.action === 'delete' && e.status !== 'synced'))
      this.outbox.replace(this.notebookId, [
        ...others,
        ...deletes.map((e) => ({ ...e, status: 'failed' as const })),
      ])
      this.patchStep('upload_delete', { status: 'error', detail: '刪除失敗' })
      return true
    }
  }

  /** upload_add — POST /api/vocab; cardId-echo reconcile (SoT invariant). */
  private async stepAdds(): Promise<{ failed: boolean; success: boolean }> {
    const adds = this.outbox
      .entries(this.notebookId)
      .filter((e) => e.action === 'add' && e.status !== 'synced')
    if (adds.length === 0) {
      this.patchStep('upload_add', { status: 'done', detail: '' })
      return { failed: false, success: false }
    }
    this.patchStep('upload_add', { status: 'running', total: adds.length })
    try {
      const response = await this.api.uploadAdd(
        adds.map((e) => e.entry!).filter(Boolean),
        this.notebookId,
      )
      const { synced, stillPending } = reconcileAdds(adds, response)
      const others = this.outbox
        .entries(this.notebookId)
        .filter((e) => !(e.action === 'add' && e.status !== 'synced'))
      this.outbox.replace(this.notebookId, [...others, ...synced, ...stillPending])
      // sync_lifecycle.md: success metric = response.created (cardId-confirmed),
      // even when the mock keys cardIds by index (word-echo backfill best-effort).
      const created = response.created
      const dup = response.duplicates.length
      const failedCount = stillPending.length
      this.patchStep('upload_add', {
        status: failedCount > 0 ? 'error' : 'done',
        current: synced.length || created,
        detail:
          failedCount > 0
            ? `部分上傳失敗（${failedCount} 筆）`
            : `${created} 新增, ${dup} 已存在`,
      })
      return { failed: failedCount > 0, success: created > 0 || synced.length > 0 }
    } catch {
      const others = this.outbox
        .entries(this.notebookId)
        .filter((e) => !(e.action === 'add' && e.status !== 'synced'))
      this.outbox.replace(this.notebookId, [
        ...others,
        ...adds.map((e) => ({ ...e, status: 'failed' as const })),
      ])
      this.patchStep('upload_add', { status: 'error', detail: '上傳失敗' })
      return { failed: true, success: false }
    }
  }

  /** trigger — fire-and-forget background enrichment. Soft step: a failure (or a
   *  missing route) never fails the whole sync. Returns true on success. */
  private async stepTrigger(): Promise<boolean> {
    if (!this.api.triggerPipeline) {
      this.patchStep('trigger', { status: 'skipped', detail: '背景處理尚未接線' })
      return true
    }
    this.patchStep('trigger', { status: 'running' })
    try {
      await this.api.triggerPipeline(this.notebookId)
      this.patchStep('trigger', { status: 'done', detail: '已交由伺服器背景處理' })
      return true
    } catch {
      this.patchStep('trigger', { status: 'error', detail: '觸發失敗（不影響其他步驟）' })
      return true // soft — does not flip the overall run to failed
    }
  }

  /** push_review — PATCH review-events + review. Returns true on success. */
  private async stepPushReview(): Promise<boolean> {
    if (this.reviewEvents.length === 0 && this.reviewStates.length === 0) {
      this.patchStep('push_review', { status: 'done', detail: '' })
      return true
    }
    this.patchStep('push_review', {
      status: 'running',
      total: this.reviewEvents.length,
    })
    try {
      const res = await this.api.pushReview({
        events: this.reviewEvents,
        states: this.reviewStates,
      })
      this.patchStep('push_review', {
        status: 'done',
        current: res.insertedEvents,
        detail: `已同步 ${res.insertedEvents} 筆複習紀錄`,
      })
      return true
    } catch {
      this.patchStep('push_review', { status: 'error', detail: '複習進度上傳失敗' })
      return false
    }
  }

  /** pull — GET /api/vocab back to local. Returns true on success. */
  private async stepPull(): Promise<boolean> {
    this.patchStep('pull', { status: 'running' })
    try {
      const { count } = await this.api.pull(this.notebookId)
      this.patchStep('pull', {
        status: 'done',
        current: count,
        total: count,
        detail: '本地單字已建立完成',
      })
      return true
    } catch {
      this.patchStep('pull', { status: 'error', detail: '下載失敗' })
      return false
    }
  }
}

export { STEP_LABELS, STEP_ORDER }
