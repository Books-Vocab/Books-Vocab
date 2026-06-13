// Pure `syncStatus × actionType` state machine — the heart of the coordinator.
// Every transition here is a transcription of docs/reference/sync_lifecycle.md.
// No I/O, no React, no storage: 100% unit-testable under node.

import type {
  ActionType,
  BatchDeleteResult,
  OutboxEntry,
  SyncStatus,
} from './types'
import type { VocabAddResponse } from '../api/types'

/** The 5 legal (status, action) combos from the SoT 規則表. `synced+delete`
 *  is terminal (the entry leaves the outbox), so it is not a resting state. */
const LEGAL: ReadonlySet<string> = new Set([
  'pending|add',
  'synced|add',
  'pending|delete',
  'failed|add',
  'failed|delete',
])

export function isLegalState(status: SyncStatus, action: ActionType): boolean {
  return LEGAL.has(`${status}|${action}`)
}

/** sync_lifecycle.md §同步失敗後重試 step 3: before a run, `failed` flips back to
 *  `pending` so it is retried. Deletes stay hidden regardless (handled by UI). */
export function resetFailedToPending(e: OutboxEntry): OutboxEntry {
  return e.status === 'failed' ? { ...e, status: 'pending' } : e
}

/** "待同步" set — what the sync page counts as outstanding. From the 規則表:
 *  pending/failed × add|delete all appear in 待同步; synced+add does NOT. */
export function isPending(e: OutboxEntry): boolean {
  return e.status === 'pending' || e.status === 'failed'
}

/** Appears in the reader (規則表 column 會出現在閱讀器). delete entries hide. */
export function showsInReader(e: OutboxEntry): boolean {
  return e.action === 'add' // add (any status) shows; delete always hidden
}

// ── add reconcile (pending+add → synced+add) ────────────────────────────────
//
// sync_lifecycle.md §本地新增上傳成功:
//   - `cardIds` is keyed by the client's RAW submitted word (byte-exact echo).
//   - a hit → backfill kgCardId + markSynced (entry leaves the outbox).
//   - convergence is gated on the returned cardId (authoritative existence),
//     NEVER on content字面 compare (backend _clean_content would silent-miss).
//   - an entry with no cardId echo stays pending+add for the next retry.

export interface AddReconcileOutcome {
  /** entries that converged to synced+add (carry their backfilled cardId). */
  synced: OutboxEntry[]
  /** entries with no cardId echo — stay pending+add. */
  stillPending: OutboxEntry[]
}

export function reconcileAdds(
  adds: OutboxEntry[],
  response: VocabAddResponse,
): AddReconcileOutcome {
  const synced: OutboxEntry[] = []
  const stillPending: OutboxEntry[] = []
  for (const e of adds) {
    // byte-exact lookup on the RAW submitted word (SoT invariant; no normalize).
    const cardId = response.cardIds[e.word]
    if (cardId) {
      synced.push({ ...e, status: 'synced', cardId })
    } else {
      stillPending.push({ ...e, status: 'pending' })
    }
  }
  return { synced, stillPending }
}

// ── delete reconcile (three buckets) ────────────────────────────────────────
//
// sync_lifecycle.md §批次刪除 三個 bucket:
//   locally-resolvable = deleted_words ∪ not_found   (success semantics)
//   must-retry         = failed  ∪  (any word in none of the three buckets)
//
// 不變式 1: never treat not_found as a delete failure (infinite retry loop).
// 不變式 2: never converge `failed` (card still on server → permanent divergence).

export interface DeleteReconcileOutcome {
  /** words to remove from the outbox (delete intent achieved). */
  resolvedWords: string[]
  /** words that must stay failed+delete and retry next run. */
  failedWords: string[]
}

export function locallyResolvableDeletes(r: BatchDeleteResult): Set<string> {
  return new Set([...r.deleted_words, ...r.not_found])
}

export function reconcileDeletes(
  deletes: OutboxEntry[],
  result: BatchDeleteResult,
): DeleteReconcileOutcome {
  const resolvable = locallyResolvableDeletes(result)
  const resolvedWords: string[] = []
  const failedWords: string[] = []
  for (const e of deletes) {
    if (resolvable.has(e.word)) {
      resolvedWords.push(e.word)
    } else {
      // Anything NOT in (deleted ∪ not_found) must retry: this covers both the
      // explicit `failed` bucket (card still on server — 不變式 2) and words
      // absent from all three buckets. Never converge here.
      failedWords.push(e.word)
    }
  }
  return { resolvedWords, failedWords }
}

/** Apply a delete reconcile to the outbox: resolved entries leave; the rest
 *  flip to failed+delete (stay hidden, retried next run). */
export function applyDeleteReconcile(
  deletes: OutboxEntry[],
  result: BatchDeleteResult,
): { remaining: OutboxEntry[] } {
  const { resolvedWords } = reconcileDeletes(deletes, result)
  const resolved = new Set(resolvedWords)
  const remaining = deletes
    .filter((e) => !resolved.has(e.word))
    .map((e) => ({ ...e, status: 'failed' as SyncStatus }))
  return { remaining }
}
