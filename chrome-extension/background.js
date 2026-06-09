/**
 * Books & Vocab Chrome Extension — Background Service Worker
 *
 * Responsibilities:
 * 1. Route API calls from content script / side panel via message passing
 * 2. Receive OAuth token from the trusted Books & Vocab web origin via externally_connectable
 * 3. Open side panel on extension icon click
 */

import * as KGApi from './shared/api.js';
// Side-effect import: registers `globalThis.KGPure` (classic-script module —
// see shared/pure.js). Used for `routeMessage` dispatch + trusted-origin checks.
import './shared/pure.js';
// Side-effect import: registers `globalThis.KGOutbox` (same classic-script
// pattern). The pure add-outbox state machine — IO + flush effects live below.
import './shared/vocab-outbox.js';

const TOKEN_KEY = KGApi.TOKEN_KEY;

// ---------------------------------------------------------------------------
// Side panel behaviour — open on action click
// ---------------------------------------------------------------------------

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

// ---------------------------------------------------------------------------
// Message routing — internal (content script, side panel, options)
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handleMessage(msg).then(sendResponse).catch((err) => {
    sendResponse(err && typeof err.toJSON === 'function' ? err.toJSON() : { error: true, message: String(err) });
  });
  return true; // keep channel open for async response
});

// ---------------------------------------------------------------------------
// External messages — OAuth token from the trusted Books & Vocab web origin
// ---------------------------------------------------------------------------

chrome.runtime.onMessageExternal.addListener((msg, sender, sendResponse) => {
  if (!globalThis.KGPure.isTrustedExternalOrigin(sender && sender.url)) {
    sendResponse({ error: true, message: 'unauthorized origin' });
    return false; // responded synchronously — close the channel
  }

  if (msg && msg.type === 'auth_token' && typeof msg.token === 'string') {
    chrome.storage.local
      .set({ [TOKEN_KEY]: msg.token })
      .then(() => sendResponse({ ok: true }))
      // Without this catch a storage failure would leave the web page's
      // sendMessage promise pending forever — surface it as an error instead.
      .catch((err) => sendResponse({ error: true, message: String(err) }));
    return true; // async
  }

  sendResponse({ error: true, message: 'unknown external message type' });
  return false; // responded synchronously — close the channel
});

// ---------------------------------------------------------------------------
// Message handler — dispatches via the tested pure `routeMessage` table
// ---------------------------------------------------------------------------

/**
 * Adapters for the storage-backed pseudo-kinds `routeMessage` emits. These
 * kinds cannot live in `pure.js` because they touch `chrome.storage` — the
 * routing *decision* is pure (and tested in `pure.test.js`), the *effect*
 * is supplied here. Behaviour mirrors the former hand-coded switch exactly.
 */
// Monotonic tick for VOCAB_DIRTY_KEY bumps. `chrome.storage.onChanged` only
// fires when the stored value actually *changes*, so two bumps in the same
// millisecond must not collide. `Date.now()` alone could; pairing it with an
// in-worker counter guarantees a distinct value on every bump within a service
// worker lifetime, and the timestamp guarantees distinctness across worker
// restarts (wall-clock only advances). Collision would need two adds straddling
// a worker teardown inside one millisecond — physically negligible.
let vocabDirtyTick = 0;

/**
 * Bump VOCAB_DIRTY_KEY so any open side panel silently refetches. Fire-and-forget:
 * a bump failure must never fail or delay the caller. `${now}.${tick}` guarantees
 * a distinct value per bump (see vocabDirtyTick) so back-to-back changes each fire.
 */
function bumpVocabDirty() {
  chrome.storage.local
    .set({ [globalThis.KGPure.VOCAB_DIRTY_KEY]: `${Date.now()}.${++vocabDirtyTick}` })
    .catch((err) => console.error('[KG] vocab_dirty bump failed', err));
}

// ---------------------------------------------------------------------------
// Vocab add outbox — persistent, retryable write queue (mirrors iOS sync)
//
// `addVocab` no longer POSTs inline; it enqueues to chrome.storage (optimistic,
// never lost) and a background flush reconciles against the server. The pure
// state transitions live in shared/vocab-outbox.js (`globalThis.KGOutbox`); the
// IO + scheduling *effects* live here, mirroring the pure/effect split used by
// `routeMessage` / `SIDE_EFFECT_HANDLERS`.
// ---------------------------------------------------------------------------

const OUTBOX_KEY = globalThis.KGOutbox.OUTBOX_KEY;

async function readOutbox() {
  const stored = await chrome.storage.local.get(OUTBOX_KEY);
  const queue = stored[OUTBOX_KEY];
  return Array.isArray(queue) ? queue : [];
}

async function writeOutbox(queue) {
  await chrome.storage.local.set({ [OUTBOX_KEY]: queue });
}

// Serialize every outbox read-modify-write. chrome.storage get/set is async and
// non-atomic, so two near-simultaneous mutations (separate addVocab messages, or
// an enqueue racing a flush's reconcile) could each read the same snapshot and
// the later write would clobber the earlier. A promise-chain mutex makes each
// mutation observe the previous one's write. Network round-trips MUST stay
// OUTSIDE the lock — only the storage read→modify→write belongs inside.
let outboxMutation = Promise.resolve();
function withOutboxLock(mutate) {
  const next = outboxMutation.then(mutate, mutate);
  outboxMutation = next.catch(() => {}); // keep the chain alive past a rejection
  return next;
}

// Single-flight guard. A service worker is single-threaded, but multiple flush
// triggers (add, and later alarm/startup) can overlap across `await`s.
// `flushInFlight` serializes them; `flushRequested` coalesces a trigger that
// lands mid-flush into exactly one more pass — no trigger is dropped, none
// stampede the endpoint.
let flushInFlight = false;
let flushRequested = false;
const OUTBOX_RETRY_ALARM = 'kg-outbox-retry';
const OUTBOX_RETRY_DELAY_MIN = 1;

function scheduleOutboxRetry() {
  chrome.alarms.create(OUTBOX_RETRY_ALARM, { delayInMinutes: OUTBOX_RETRY_DELAY_MIN });
}

/**
 * Enqueue user adds optimistically and kick a background flush. Returns
 * immediately with an optimistic ack — the network round-trip happens off the
 * caller's path, so a flaky connection never costs the user the word (it stays
 * pending/failed and retries) and the popup confirms instantly.
 *
 * @param {Array<{word: string, translation: string, context?: string,
 *   source?: object}>} entries
 */
async function handleAddVocabOutbox(entries, notebookId = 'default') {
  const list = Array.isArray(entries) ? entries : [];
  const targetNotebookId = notebookId || 'default';
  // Mint ids/timestamps up front (side-effects), then commit the enqueue under
  // the lock so a concurrent add/flush can't clobber the write.
  const made = list.map((e) =>
    globalThis.KGOutbox.makeOutboxEntry({
      localId: crypto.randomUUID(),
      notebookId: targetNotebookId,
      word: e.word,
      translation: e.translation,
      context: e.context,
      source: e.source,
      createdAt: new Date().toISOString(),
    }),
  );
  await withOutboxLock(async () => {
    let queue = await readOutbox();
    for (const entry of made) {
      queue = globalThis.KGOutbox.enqueueAdd(queue, entry);
    }
    await writeOutbox(queue);
  });
  bumpVocabDirty(); // side panel shows the pending word immediately
  // fire-and-forget — do NOT await the network here; .catch so a storage/context
  // failure before the inner try can't escape as an unhandled rejection.
  flushOutbox().catch((err) => console.error('[KG] flush failed', err));
  return { ok: true, optimistic: true, queued: list.length };
}

/**
 * Drain the outbox: batch-push all unresolved entries, reconcile the returned
 * cardIds onto the *current* queue (it may have grown during the await), prune
 * synced, and broadcast. On failure, mark the pushed entries failed for a later
 * retry. Re-reads storage after every await so a concurrent enqueue is never
 * clobbered.
 */
async function flushOutbox() {
  if (flushInFlight) {
    flushRequested = true;
    return;
  }
  flushInFlight = true;
  try {
    let stopDraining = false;
    do {
      flushRequested = false;
      const toFlush = globalThis.KGOutbox.entriesToFlush(await readOutbox());
      if (toFlush.length === 0) break;

      for (const group of globalThis.KGOutbox.groupEntriesByNotebook(toFlush)) {
        const payload = group.entries.map((e) => ({
          word: e.word,
          translation: e.translation,
          context: e.context,
          source: e.source,
        }));

        try {
          const resp = await KGApi.addVocab(payload, group.notebookId); // network — OUTSIDE the lock
          const cardIds = (resp && resp.cardIds) || {};
          await withOutboxLock(async () => {
            let queue = globalThis.KGOutbox.reconcileAddResponse(await readOutbox(), cardIds, group.notebookId);
            queue = globalThis.KGOutbox.pruneSynced(queue);
            await writeOutbox(queue);
          });
          bumpVocabDirty(); // server now has these cards → refetch surfaces them
          if (Object.keys(cardIds).length > 0) {
            // Cards landed (bare) — kick enrich + poll so they grow pos/note/examples.
            triggerEnrichPolling(group.notebookId).catch((err) =>
              console.error('[KG] enrich trigger failed', err),
            );
          }
        } catch (err) {
          const ids = group.entries.map((e) => e.localId);
          await withOutboxLock(async () => {
            await writeOutbox(globalThis.KGOutbox.markFailed(await readOutbox(), ids));
          });
          bumpVocabDirty(); // surface failed state to the side panel
          scheduleOutboxRetry();
          // Stop draining on failure — the next trigger (a fresh add, or the
          // retry alarm/startup flush) retries. Looping here would hammer a
          // down endpoint.
          stopDraining = true;
          break;
        }
      }
    } while (flushRequested && !stopDraining);
  } finally {
    flushInFlight = false;
  }
}

// ---------------------------------------------------------------------------
// Enrich polling — after cards land on the server (bare), kick the pipeline and
// re-pull a few times so the side panel surfaces the enriched fields (pos /
// note / examples). Mirrors iOS: trigger POST /api/pipeline, then re-pull
// GET /api/vocab while X-Pipeline-Pending is true, capped at a few attempts.
//
// MV3 note: iOS polls every 10s, but chrome.alarms granularity floors at ~30s,
// and a service worker can be killed between attempts — so we poll via alarms
// (which wake a dead worker) at 30s, capped at 3, with the attempt counter in
// storage (survives worker restarts). Worst case the user re-opens the panel
// and the dirty-driven refetch shows the final enriched state anyway.
// ---------------------------------------------------------------------------

const ENRICH_POLL_ALARM = 'kg-enrich-poll';
const ENRICH_POLL_STATE_KEY = 'enrich_poll_state';
const ENRICH_POLL_MAX = 3;
const ENRICH_POLL_DELAY_MIN = 0.5; // 30s — chrome.alarms floor

function scheduleEnrichPoll() {
  chrome.alarms.create(ENRICH_POLL_ALARM, { delayInMinutes: ENRICH_POLL_DELAY_MIN });
}

/**
 * Best-effort: trigger server enrich for the notebook, then start polling.
 * A failure (quota/transient) is swallowed — the bare cards already exist and a
 * later add/pull can re-trigger; enrich must never fail the user's add/flush.
 */
async function triggerEnrichPolling(notebookId) {
  try {
    await KGApi.triggerPipeline(notebookId);
  } catch (err) {
    console.warn('[KG] triggerPipeline failed (enrich is best-effort)', err);
    return;
  }
  // Preserve an in-flight poll's attempt count so rapid successive adds can't
  // reset the cap and poll forever; accumulate notebook ids so each poll re-pulls
  // the notebook whose pipeline was actually triggered.
  const stored = await chrome.storage.local.get(ENRICH_POLL_STATE_KEY);
  const prior = stored[ENRICH_POLL_STATE_KEY];
  const attempts = prior ? prior.attempts || 0 : 0;
  const notebookIds = new Set(Array.isArray(prior && prior.notebookIds) ? prior.notebookIds : []);
  notebookIds.add(notebookId || 'default');
  await chrome.storage.local.set({ [ENRICH_POLL_STATE_KEY]: { attempts, notebookIds: [...notebookIds] } });
  scheduleEnrichPoll();
}

async function handleEnrichPoll() {
  const stored = await chrome.storage.local.get(ENRICH_POLL_STATE_KEY);
  const state = stored[ENRICH_POLL_STATE_KEY];
  if (!state) return; // nothing in flight (e.g. cleared, or stale alarm)

  // Re-pull each triggered notebook to (a) read X-Pipeline-Pending and (b) bump
  // the side panel so it re-renders the now-enriched cards. Treat a hiccup as
  // "still pending" so we retry up to the cap rather than stop early.
  let pending = false;
  const notebookIds = Array.isArray(state.notebookIds) && state.notebookIds.length
    ? state.notebookIds
    : ['default'];
  for (const notebookId of notebookIds) {
    try {
      await KGApi.listVocab(undefined, (res) => {
        if (res.headers.get('X-Pipeline-Pending') === 'true') pending = true;
      }, notebookId);
    } catch (err) {
      pending = true;
    }
  }
  bumpVocabDirty();

  const attempts = (state.attempts || 0) + 1;
  if (pending && attempts < ENRICH_POLL_MAX) {
    await chrome.storage.local.set({ [ENRICH_POLL_STATE_KEY]: { attempts, notebookIds } });
    scheduleEnrichPoll();
  } else {
    await chrome.storage.local.remove(ENRICH_POLL_STATE_KEY);
    chrome.alarms.clear(ENRICH_POLL_ALARM).catch(() => {});
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ENRICH_POLL_ALARM) {
    handleEnrichPoll().catch((err) => console.error('[KG] enrich poll failed', err));
  } else if (alarm.name === OUTBOX_RETRY_ALARM) {
    flushOutbox().catch((err) => console.error('[KG] outbox retry failed', err));
  }
});

const SIDE_EFFECT_HANDLERS = {
  // `get_auth_status` — report whether a token is stored.
  getAuthStatus: async () => {
    const token = await KGApi.getToken();
    return { authenticated: !!token };
  },
  // `logout` — clear the stored token.
  logout: async () => {
    await chrome.storage.local.remove(TOKEN_KEY);
    return { ok: true };
  },
  // `retryOutbox` — user-triggered flush for failed optimistic rows.
  retryOutbox: async () => {
    await flushOutbox();
    return { ok: true };
  },
};

async function handleMessage(msg) {
  // `routeMessage` throws for unknown types. Token writes are NOT routable
  // internally — they go only through `onMessageExternal` above.
  const { kind, args } = globalThis.KGPure.routeMessage(msg);

  // addVocab is intercepted into the persistent outbox: enqueue + optimistic
  // ack + background flush, instead of an inline POST. Every other kind keeps
  // the direct path below.
  if (kind === 'addVocab') {
    return handleAddVocabOutbox(args[0], args[1]);
  }

  const sideEffect = SIDE_EFFECT_HANDLERS[kind];
  if (sideEffect) {
    return sideEffect(...args);
  }

  // Pure-API kinds map 1:1 onto `KGApi` method names.
  const apiMethod = KGApi[kind];
  if (typeof apiMethod !== 'function') {
    throw new Error(`unroutable message kind: ${kind}`);
  }
  const result = await apiMethod(...args);

  // A future vocab-mutating kind (deleteVocab / updateVocab) that lands on this
  // direct path invalidates any open side panel; bump so it silently refetches.
  // (addVocab is handled above via the outbox, which bumps on its own.)
  if (globalThis.KGPure.isVocabMutatingKind(kind)) {
    bumpVocabDirty();
  }

  return result;
}

// ---------------------------------------------------------------------------
// Startup drain — on every service-worker spin-up (install, or wake from idle
// via a message/alarm), retry any outbox entries a previous worker lifetime left
// unresolved: failed retries, or an add whose flush was cut short when the worker
// was killed mid-network. single-flight makes a concurrent message-driven flush
// safe; an empty outbox is a cheap no-op (one storage read, no network).
// ---------------------------------------------------------------------------
flushOutbox().catch((err) => console.error('[KG] startup flush failed', err));

export const __test__ = {
  flushOutbox,
  handleMessage,
  handleEnrichPoll,
  triggerEnrichPolling,
};
