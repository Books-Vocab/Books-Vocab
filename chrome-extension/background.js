/**
 * KG Chrome Extension — Background Service Worker
 *
 * Responsibilities:
 * 1. Route API calls from content script / side panel via message passing
 * 2. Receive OAuth token from wordnexus.lol via externally_connectable
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
// External messages — OAuth token from wordnexus.lol
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

// Single-flight guard. A service worker is single-threaded, but multiple flush
// triggers (add, and later alarm/startup) can overlap across `await`s.
// `flushInFlight` serializes them; `flushRequested` coalesces a trigger that
// lands mid-flush into exactly one more pass — no trigger is dropped, none
// stampede the endpoint.
let flushInFlight = false;
let flushRequested = false;

/**
 * Enqueue user adds optimistically and kick a background flush. Returns
 * immediately with an optimistic ack — the network round-trip happens off the
 * caller's path, so a flaky connection never costs the user the word (it stays
 * pending/failed and retries) and the popup confirms instantly.
 *
 * @param {Array<{word: string, translation: string, context?: string,
 *   source?: object}>} entries
 */
async function handleAddVocabOutbox(entries) {
  const list = Array.isArray(entries) ? entries : [];
  let queue = await readOutbox();
  for (const e of list) {
    queue = globalThis.KGOutbox.enqueueAdd(
      queue,
      globalThis.KGOutbox.makeOutboxEntry({
        localId: crypto.randomUUID(),
        word: e.word,
        translation: e.translation,
        context: e.context,
        source: e.source,
        createdAt: new Date().toISOString(),
      }),
    );
  }
  await writeOutbox(queue);
  bumpVocabDirty(); // side panel shows the pending word immediately
  flushOutbox();    // fire-and-forget — do NOT await the network here
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
    do {
      flushRequested = false;
      const toFlush = globalThis.KGOutbox.entriesToFlush(await readOutbox());
      if (toFlush.length === 0) break;

      const payload = toFlush.map((e) => ({
        word: e.word,
        translation: e.translation,
        context: e.context,
        source: e.source,
      }));

      try {
        const resp = await KGApi.addVocab(payload);
        const cardIds = (resp && resp.cardIds) || {};
        let queue = globalThis.KGOutbox.reconcileAddResponse(await readOutbox(), cardIds);
        queue = globalThis.KGOutbox.pruneSynced(queue);
        await writeOutbox(queue);
        bumpVocabDirty(); // server now has these cards → refetch surfaces them
      } catch (err) {
        const ids = toFlush.map((e) => e.localId);
        await writeOutbox(globalThis.KGOutbox.markFailed(await readOutbox(), ids));
        bumpVocabDirty(); // surface failed state to the side panel
        // Stop draining on failure — the next trigger (a fresh add, or the
        // Phase 5 alarm/startup flush) retries. Looping here would hammer a
        // down endpoint.
        break;
      }
    } while (flushRequested);
  } finally {
    flushInFlight = false;
  }
}

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
};

async function handleMessage(msg) {
  // `routeMessage` throws for unknown types. Token writes are NOT routable
  // internally — they go only through `onMessageExternal` above.
  const { kind, args } = globalThis.KGPure.routeMessage(msg);

  // addVocab is intercepted into the persistent outbox: enqueue + optimistic
  // ack + background flush, instead of an inline POST. Every other kind keeps
  // the direct path below.
  if (kind === 'addVocab') {
    return handleAddVocabOutbox(args[0]);
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
