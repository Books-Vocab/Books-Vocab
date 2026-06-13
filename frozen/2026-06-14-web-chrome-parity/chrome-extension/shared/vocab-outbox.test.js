/**
 * Unit tests for shared/vocab-outbox.js — the pure outbox state machine that
 * mirrors iOS `VocabularyEntry` add-path transitions (pending → synced → failed).
 *
 * Zero external dependencies — Node's built-in `node:test`. Run from
 * chrome-extension/:
 *
 *   node --test
 *   node --test shared/vocab-outbox.test.js
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  OUTBOX_STATUS,
  OUTBOX_KEY,
  makeOutboxEntry,
  enqueueAdd,
  reconcileAddResponse,
  markFailed,
  entriesToFlush,
  pruneSynced,
  summarizeOutbox,
  pendingOutboxItems,
  groupEntriesByNotebook,
} = require('./vocab-outbox.js');

// Convenience: a fully-formed pending entry.
function pending(localId, word, extra = {}) {
  return makeOutboxEntry({
    localId,
    word,
    translation: `${word}-t`,
    context: `${word} ctx`,
    source: { type: 'web', title: 'T', url: 'https://x' },
    createdAt: '2026-06-05T00:00:00.000Z',
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// makeOutboxEntry
// ---------------------------------------------------------------------------

test('makeOutboxEntry yields a pending entry with defaults', () => {
  const e = pending('l1', 'qoder');
  assert.equal(e.status, OUTBOX_STATUS.PENDING);
  assert.equal(e.attempts, 0);
  assert.equal(e.cardId, null);
  assert.equal(e.notebookId, 'default');
  assert.equal(e.word, 'qoder');
  assert.equal(e.translation, 'qoder-t');
  assert.equal(e.localId, 'l1');
});

test('makeOutboxEntry preserves an explicit notebookId', () => {
  const e = pending('l1', 'qoder', { notebookId: 'nb-reading' });
  assert.equal(e.notebookId, 'nb-reading');
});

test('makeOutboxEntry preserves byte-exact word (no normalization)', () => {
  // The reconcile contract keys on the *raw* submitted word; the entry must
  // not trim/lowercase it (backend cleans the stored content, not the key).
  const e = pending('l1', 'Chateau,');
  assert.equal(e.word, 'Chateau,');
});

// ---------------------------------------------------------------------------
// enqueueAdd
// ---------------------------------------------------------------------------

test('enqueueAdd appends immutably', () => {
  const q0 = [];
  const q1 = enqueueAdd(q0, pending('l1', 'alpha'));
  assert.equal(q0.length, 0); // original untouched
  assert.equal(q1.length, 1);
  assert.equal(q1[0].word, 'alpha');
});

test('enqueueAdd dedups an unresolved same-word entry (idempotent UX)', () => {
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = enqueueAdd(q, pending('l2', 'alpha')); // double-click same word
  assert.equal(q.length, 1, 'should not queue a 2nd pending for same word');
  assert.equal(q[0].localId, 'l1', 'keeps the first');
});

test('enqueueAdd keeps same word in different notebooks distinct', () => {
  let q = enqueueAdd([], pending('l1', 'alpha', { notebookId: 'default' }));
  q = enqueueAdd(q, pending('l2', 'alpha', { notebookId: 'nb-reading' }));
  assert.equal(q.length, 2);
  assert.deepEqual(q.map((e) => e.notebookId).sort(), ['default', 'nb-reading']);
});

test('enqueueAdd re-queues a word that already synced (legit re-add)', () => {
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = reconcileAddResponse(q, { alpha: 'card-a' }); // synced
  q = enqueueAdd(q, pending('l2', 'alpha'));
  assert.equal(q.length, 2, 'synced entry does not block a fresh add');
});

// ---------------------------------------------------------------------------
// reconcileAddResponse — the convergence contract (sync_lifecycle.md:47-52)
// ---------------------------------------------------------------------------

test('reconcileAddResponse marks synced + backfills cardId on byte-exact word hit', () => {
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = reconcileAddResponse(q, { alpha: 'card-a' });
  assert.equal(q[0].status, OUTBOX_STATUS.SYNCED);
  assert.equal(q[0].cardId, 'card-a');
});

test('reconcileAddResponse leaves entry pending when word absent from cardIds', () => {
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = reconcileAddResponse(q, { beta: 'card-b' }); // no alpha key
  assert.equal(q[0].status, OUTBOX_STATUS.PENDING);
  assert.equal(q[0].cardId, null);
});

test('reconcileAddResponse never content-matches across cleaning boundary', () => {
  // Backend cleans stored content ("Chateau," → "chateau") but echoes the
  // response key as the raw submitted word. Lookup MUST be raw-word exact:
  // a cleaned key must NOT resolve the raw-word entry.
  let q = enqueueAdd([], pending('l1', 'Chateau,'));
  q = reconcileAddResponse(q, { chateau: 'card-c' }); // cleaned key — must miss
  assert.equal(q[0].status, OUTBOX_STATUS.PENDING, 'cleaned key must not match raw word');
  q = reconcileAddResponse(q, { 'Chateau,': 'card-c' }); // raw echo — hits
  assert.equal(q[0].status, OUTBOX_STATUS.SYNCED);
  assert.equal(q[0].cardId, 'card-c');
});

test('reconcileAddResponse ignores inherited Object.prototype keys', () => {
  let q = enqueueAdd([], pending('l1', 'toString'));
  q = reconcileAddResponse(q, {}); // empty map — "toString" must not "hit" via proto
  assert.equal(q[0].status, OUTBOX_STATUS.PENDING);
});

test('reconcileAddResponse converges a FAILED entry when its cardId echoes', () => {
  // A server echo is authoritative proof the card exists, so a failed entry
  // that gets re-sent and succeeds MUST converge — otherwise entriesToFlush
  // keeps re-sending it every flush (re-creating the card / burning enrich).
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = markFailed(q, ['l1']);
  q = reconcileAddResponse(q, { alpha: 'card-a' });
  assert.equal(q[0].status, OUTBOX_STATUS.SYNCED, 'failed converges on echo');
  assert.equal(q[0].cardId, 'card-a');
});

test('reconcileAddResponse scopes convergence to the flushed notebook', () => {
  const q = [
    pending('l1', 'alpha', { notebookId: 'default' }),
    pending('l2', 'alpha', { notebookId: 'nb-reading' }),
  ];
  const next = reconcileAddResponse(q, { alpha: 'card-a' }, 'nb-reading');
  assert.equal(next[0].status, OUTBOX_STATUS.PENDING);
  assert.equal(next[1].status, OUTBOX_STATUS.SYNCED);
  assert.equal(next[1].cardId, 'card-a');
});

test('reconcileAddResponse never re-resolves an already-synced entry', () => {
  // SYNCED is terminal — a later/stale cardIds map must not rewrite the cardId.
  let q = [pending('l1', 'alpha')];
  q = reconcileAddResponse(q, { alpha: 'card-a' });
  const before = q[0];
  q = reconcileAddResponse(q, { alpha: 'card-OTHER' });
  assert.equal(q[0].cardId, 'card-a', 'synced cardId is stable');
  assert.equal(q[0], before, 'no needless churn (same reference)');
});

// ---------------------------------------------------------------------------
// markFailed
// ---------------------------------------------------------------------------

test('markFailed flips matched pending entries to failed and bumps attempts', () => {
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = markFailed(q, ['l1']);
  assert.equal(q[0].status, OUTBOX_STATUS.FAILED);
  assert.equal(q[0].attempts, 1);
  q = markFailed(q, ['l1']);
  assert.equal(q[0].attempts, 2, 'retry failure increments again');
});

test('markFailed leaves unmatched and synced entries alone', () => {
  let q = [pending('l1', 'alpha'), pending('l2', 'beta')];
  q = reconcileAddResponse(q, { alpha: 'card-a' }); // l1 synced
  q = markFailed(q, ['l1', 'l2']);
  assert.equal(q[0].status, OUTBOX_STATUS.SYNCED, 'synced not overwritten by failed');
  assert.equal(q[1].status, OUTBOX_STATUS.FAILED);
});

// ---------------------------------------------------------------------------
// entriesToFlush — pending ∪ failed (failed is retryable, like iOS
// prepareForRetryAttempt folding failed→pending before a push)
// ---------------------------------------------------------------------------

test('entriesToFlush returns pending and failed, excludes synced', () => {
  let q = [pending('l1', 'a'), pending('l2', 'b'), pending('l3', 'c')];
  q = reconcileAddResponse(q, { a: 'card-a' }); // l1 synced
  q = markFailed(q, ['l2']); // l2 failed
  const flush = entriesToFlush(q); // l2 (failed) + l3 (pending)
  assert.deepEqual(flush.map((e) => e.localId).sort(), ['l2', 'l3']);
});

// ---------------------------------------------------------------------------
// pruneSynced — drop converged entries (server list is now authoritative)
// ---------------------------------------------------------------------------

test('pruneSynced removes synced entries, keeps pending/failed', () => {
  let q = [pending('l1', 'a'), pending('l2', 'b'), pending('l3', 'c')];
  q = reconcileAddResponse(q, { a: 'card-a' });
  q = markFailed(q, ['l2']);
  const pruned = pruneSynced(q);
  assert.deepEqual(pruned.map((e) => e.localId).sort(), ['l2', 'l3']);
});

// ---------------------------------------------------------------------------
// summarizeOutbox — sidepanel badge counts
// ---------------------------------------------------------------------------

test('OUTBOX_KEY is the storage key contract', () => {
  assert.equal(OUTBOX_KEY, 'vocab_outbox');
});

test('summarizeOutbox tallies by status', () => {
  let q = [pending('l1', 'a'), pending('l2', 'b'), pending('l3', 'c')];
  q = reconcileAddResponse(q, { a: 'card-a' });
  q = markFailed(q, ['l2']);
  assert.deepEqual(summarizeOutbox(q), { pending: 1, synced: 1, failed: 1, total: 3 });
});

// ---------------------------------------------------------------------------
// pendingOutboxItems — optimistic rows for the side panel (unresolved entries
// not yet on the server list)
// ---------------------------------------------------------------------------

test('pendingOutboxItems returns unresolved entries absent from the server list', () => {
  let q = enqueueAdd([], pending('l1', 'alpha'));
  q = enqueueAdd(q, pending('l2', 'beta'));
  q = enqueueAdd(q, pending('l3', 'gamma'));
  q = reconcileAddResponse(q, { alpha: 'card-a' }); // alpha synced → excluded
  q = markFailed(q, ['l2']); // beta failed → included
  // gamma already on the server (its flush echoed but list shows it) → excluded
  const items = pendingOutboxItems(q, new Set(['gamma']));
  assert.equal(items.length, 1);
  assert.equal(items[0].word, 'beta');
  assert.equal(items[0].syncState, OUTBOX_STATUS.FAILED);
  assert.equal(items[0].meaning, 'beta-t', 'translation surfaces as meaning');
});

test('pendingOutboxItems accepts an array for serverWords and carries source', () => {
  const q = enqueueAdd([], pending('l1', 'alpha', { notebookId: 'nb-reading' }));
  const items = pendingOutboxItems(q, []); // array form
  assert.equal(items.length, 1);
  assert.equal(items[0].word, 'alpha');
  assert.equal(items[0].notebookId, 'nb-reading');
  assert.equal(items[0].syncState, OUTBOX_STATUS.PENDING);
  assert.deepEqual(items[0].source, { type: 'web', title: 'T', url: 'https://x' });
  assert.equal(pendingOutboxItems(q, ['alpha']).length, 0, 'array exclusion works');
});

test('groupEntriesByNotebook batches unresolved entries by notebookId', () => {
  const q = [
    pending('l1', 'a', { notebookId: 'default' }),
    pending('l2', 'b', { notebookId: 'nb-reading' }),
    pending('l3', 'c', { notebookId: 'nb-reading' }),
  ];
  const groups = groupEntriesByNotebook(q);
  assert.deepEqual(
    groups.map((g) => ({ notebookId: g.notebookId, words: g.entries.map((e) => e.word) })),
    [
      { notebookId: 'default', words: ['a'] },
      { notebookId: 'nb-reading', words: ['b', 'c'] },
    ],
  );
});

test('pendingOutboxItems byte-exact server match (no normalization)', () => {
  const q = enqueueAdd([], pending('l1', 'Chateau,'));
  // a cleaned server word must NOT suppress the raw-word pending row
  assert.equal(pendingOutboxItems(q, ['chateau']).length, 1);
  assert.equal(pendingOutboxItems(q, ['Chateau,']).length, 0);
});
