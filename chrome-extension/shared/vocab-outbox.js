/**
 * KG Chrome Extension — Vocab Outbox (pure state machine)
 *
 * Mirrors the *add path* of iOS `VocabularyEntry`'s sync lifecycle so chrome
 * gains a persistent, retryable write queue instead of fire-and-go POSTs:
 *
 *   pending ──(POST /api/vocab → cardIds[word] hit)──▶ synced
 *      │                                                  │
 *      └──(network/server failure)──▶ failed ──(retry)────┘
 *
 * Scope (per the approved plan): add-only. No delete/edit transitions, no
 * offline-first editing. enrich (POST /api/pipeline + re-pull) is a background
 * side-effect that runs *after* an entry converges to synced — it is NOT
 * tracked here, so this stays a clean 3-state machine matching iOS
 * `syncStatus` (0 pending / 1 synced / 2 failed).
 *
 * All functions are PURE: no `chrome.*`, no IO, immutable returns. The IO layer
 * (chrome.storage read/write + flush scheduling) lives in background.js, mirroring
 * the pure/effect split used by shared/pure.js (`routeMessage`) and its
 * SIDE_EFFECT_HANDLERS. Pinned by shared/vocab-outbox.test.js (`node --test`).
 *
 * Convergence contract (sync_lifecycle.md:47-52): an entry is resolved ONLY by
 * the server echoing its cardId, keyed by the *raw submitted word* (byte-exact).
 * The backend cleans stored content ("Chateau," → "chateau") but echoes the
 * response key as the original word — so reconcile MUST look up `entry.word`
 * verbatim and MUST NOT content-compare across that cleaning boundary.
 */

'use strict';

/** Status values — mirror iOS `syncStatus` (0/1/2) semantics. */
const OUTBOX_STATUS = Object.freeze({
  PENDING: 'pending',
  SYNCED: 'synced',
  FAILED: 'failed',
});

/** chrome.storage.local key holding the add-outbox queue (array of entries). */
const OUTBOX_KEY = 'vocab_outbox';

/** An entry is still "owed to the server" (queue it for the next flush). */
function isUnresolved(entry) {
  return entry.status === OUTBOX_STATUS.PENDING || entry.status === OUTBOX_STATUS.FAILED;
}

/**
 * Build a normalized pending outbox entry. `localId` / `createdAt` are supplied
 * by the (impure) caller — id minting and clock reads are side-effects kept out
 * of this pure module. `word` is stored verbatim (the reconcile key).
 *
 * @param {{localId: string, word: string, translation: string,
 *   context?: string, source?: object, createdAt?: string}} fields
 */
function makeOutboxEntry(fields) {
  return {
    localId: fields.localId,
    word: fields.word,
    translation: fields.translation,
    context: fields.context == null ? '' : fields.context,
    source: fields.source == null ? null : fields.source,
    status: OUTBOX_STATUS.PENDING,
    attempts: 0,
    cardId: null,
    createdAt: fields.createdAt == null ? null : fields.createdAt,
  };
}

/**
 * Append an entry. Dedups against an existing *unresolved* (pending|failed)
 * entry for the same word so a double-click doesn't queue twice; a word that
 * already converged (synced) does NOT block a fresh re-add.
 * Immutable — never mutates `queue`.
 */
function enqueueAdd(queue, entry) {
  if (queue.some((e) => e.word === entry.word && isUnresolved(e))) {
    return queue.slice();
  }
  return [...queue, entry];
}

/**
 * Resolve pending entries whose raw word the server echoed back in `cardIds`.
 * Byte-exact, own-property lookup only (no proto keys, no content normalization).
 * Already synced/failed entries are untouched. Returns the same reference when
 * nothing changed (avoids needless storage churn / re-renders).
 *
 * @param {Array<object>} queue
 * @param {Record<string,string>} cardIds — { rawWord: cardId } from VocabAddResponse
 */
function reconcileAddResponse(queue, cardIds) {
  const map = cardIds || {};
  let changed = false;
  const next = queue.map((entry) => {
    // SYNCED is terminal — never re-resolve (a later/stale cardIds map must not
    // rewrite a converged cardId).
    if (entry.status === OUTBOX_STATUS.SYNCED) return entry;
    // PENDING *or* FAILED converges when the server echoes its cardId. The echo
    // is authoritative proof the card exists (backend is idempotent — a re-sent
    // duplicate echoes the same cardId), so a failed-then-resent entry resolves
    // instead of looping forever in entriesToFlush.
    if (!Object.prototype.hasOwnProperty.call(map, entry.word)) return entry;
    changed = true;
    return { ...entry, status: OUTBOX_STATUS.SYNCED, cardId: map[entry.word] };
  });
  return changed ? next : queue;
}

/**
 * Flip the given entries (by localId) to failed and bump their attempt count —
 * the retry counter. Synced entries are never overwritten (server already has
 * them; overwriting would resurrect a converged write). Immutable.
 */
function markFailed(queue, localIds) {
  const ids = new Set(localIds || []);
  return queue.map((entry) => {
    if (!ids.has(entry.localId)) return entry;
    if (entry.status === OUTBOX_STATUS.SYNCED) return entry;
    return { ...entry, status: OUTBOX_STATUS.FAILED, attempts: entry.attempts + 1 };
  });
}

/**
 * Entries owed to the server: pending ∪ failed. failed is folded back in as
 * retryable, matching iOS `prepareForRetryAttempt` (failed→pending before push).
 */
function entriesToFlush(queue) {
  return queue.filter(isUnresolved);
}

/**
 * Drop converged (synced) entries — once the card exists on the server the
 * authoritative copy is the pulled `GET /api/vocab` list, so the optimistic
 * outbox row is no longer needed.
 */
function pruneSynced(queue) {
  return queue.filter((entry) => entry.status !== OUTBOX_STATUS.SYNCED);
}

/** Tally by status for the side panel's sync badge. */
function summarizeOutbox(queue) {
  const out = { pending: 0, synced: 0, failed: 0, total: queue.length };
  for (const entry of queue) {
    if (entry.status === OUTBOX_STATUS.PENDING) out.pending += 1;
    else if (entry.status === OUTBOX_STATUS.SYNCED) out.synced += 1;
    else if (entry.status === OUTBOX_STATUS.FAILED) out.failed += 1;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Exports — triple pattern mirroring shared/pure.js: classic-script global for
// the side panel, side-effect import for the module service worker, CommonJS
// for the node:test runner. NO top-level ESM `export` (SyntaxError in classic).
// ---------------------------------------------------------------------------

const KGOutboxExports = {
  OUTBOX_STATUS,
  OUTBOX_KEY,
  makeOutboxEntry,
  enqueueAdd,
  reconcileAddResponse,
  markFailed,
  entriesToFlush,
  pruneSynced,
  summarizeOutbox,
};

if (typeof globalThis !== 'undefined') {
  globalThis.KGOutbox = KGOutboxExports;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = KGOutboxExports;
}
