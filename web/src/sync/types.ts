// Sync coordinator — domain types + ports.
//
// SoT: docs/reference/sync_lifecycle.md. The local `syncStatus × actionType`
// state machine, the batch-delete three-bucket reconciliation, and the
// pending-add cardId-echo invariant are all transcribed from that doc. Field
// shapes for network payloads come from web/src/api/types.ts (the frozen typed
// client). This module owns NO rendering — SyncScreen drives off these types.

import type {
  ReviewEventEntry,
  ReviewStateEntry,
  VocabAddResponse,
  VocabEntry,
} from '../api/types'

// ── state machine (sync_lifecycle.md §核心欄位) ──────────────────────────────

/** `syncStatus` — the per-entry sync lifecycle. 0/1/2 mirror the iOS enum. */
export type SyncStatus = 'pending' | 'synced' | 'failed'

/** `actionType` — what the pending mutation is. `edit` is reserved (Phase 2). */
export type ActionType = 'add' | 'delete'

/** One queued local mutation awaiting reconciliation with the cloud. */
export interface OutboxEntry {
  /** Stable local id (uuid-ish); identity for dedup + reconcile. */
  readonly id: string
  /** The raw, byte-exact submitted word (reconcile key — see SoT invariant). */
  readonly word: string
  /** notebook this mutation belongs to (per-notebook isolation). */
  readonly notebookId: string
  readonly action: ActionType
  status: SyncStatus
  /** add-only payload (translation/context); absent for delete. */
  readonly entry?: VocabEntry
  /** server card id, backfilled on a successful add reconcile. */
  cardId?: string
}

// ── step pipeline (mirrors SyncScreen step ids / iOS SyncPresenter) ──────────

/** Ordered pipeline steps. Ids are byte-identical to the fixture step ids so
 *  the live timeline reuses the same labels/CSS as the parity fixtures. */
export type SyncStepId =
  | 'upload_delete'
  | 'upload_add'
  | 'trigger'
  | 'push_review'
  | 'pull'

export type StepRunStatus = 'waiting' | 'running' | 'done' | 'error' | 'skipped'

export interface StepProgress {
  readonly id: SyncStepId
  status: StepRunStatus
  current: number
  total: number
  detail: string
}

export type SyncPhase = 'ready' | 'running' | 'completed' | 'failed'
export type SyncFailureKind = 'partial' | 'full' | null

/** The full coordinator-observable state for one notebook's run. */
export interface CoordinatorState {
  readonly notebookId: string
  phase: SyncPhase
  failureKind: SyncFailureKind
  steps: StepProgress[]
  /** entries still pending/failed after the last run (drives hero counts). */
  pending: OutboxEntry[]
}

// ── coordinator events (step-progress stream) ───────────────────────────────

export type SyncEvent =
  | { type: 'state'; state: CoordinatorState }
  | { type: 'step'; step: StepProgress }
  | { type: 'phase'; phase: SyncPhase; failureKind: SyncFailureKind }

export type SyncListener = (event: SyncEvent) => void

// ── network port (SyncApi) ──────────────────────────────────────────────────
//
// The coordinator core depends on this narrow port, never on the concrete
// ApiClient. The default adapter (./api.ts::createSyncApi) binds it to the
// frozen typed client + mock. Steps whose backend route does not yet exist in
// the frozen foundation (batch-delete, pipeline trigger) are OPTIONAL here: a
// missing method = that step is reported `skipped` rather than fabricated. When
// the route lands, binding it is a one-line change in the adapter.

/** Result of a batch-delete reconcile (sync_lifecycle.md §三個 bucket). */
export interface BatchDeleteResult {
  /** server confirmed deleted. */
  deleted_words: string[]
  /** lookup miss — already gone; locally resolvable (success semantics). */
  not_found: string[]
  /** graph op failed + rolled back — card STILL exists; must retry. */
  failed: string[]
}

export interface SyncApi {
  /** POST /api/vocab — upload pending adds for one notebook. */
  uploadAdd(
    entries: VocabEntry[],
    notebookId: string,
  ): Promise<VocabAddResponse>

  /** POST /api/vocab/batch-delete — OPTIONAL: absent in frozen foundation. */
  batchDelete?(words: string[], notebookId: string): Promise<BatchDeleteResult>

  /** POST /api/pipeline — OPTIONAL: trigger background enrichment. */
  triggerPipeline?(notebookId: string): Promise<void>

  /** PATCH /api/vocab/review-events + /review — push local review progress. */
  pushReview(req: {
    events: ReviewEventEntry[]
    states: ReviewStateEntry[]
  }): Promise<{ insertedEvents: number; updatedStates: number }>

  /** GET /api/vocab — pull canonical cards back to local. */
  pull(notebookId: string): Promise<{ count: number }>
}

// ── localStorage seam ───────────────────────────────────────────────────────

/** Minimal key/value storage contract (Web Storage subset). Injectable so the
 *  pure core is testable under node (no jsdom / window). */
export interface KVStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}
