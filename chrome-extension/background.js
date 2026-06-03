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

  const sideEffect = SIDE_EFFECT_HANDLERS[kind];
  if (sideEffect) {
    return sideEffect(...args);
  }

  // Pure-API kinds map 1:1 onto `KGApi` method names.
  const apiMethod = KGApi[kind];
  if (typeof apiMethod !== 'function') {
    throw new Error(`unroutable message kind: ${kind}`);
  }
  return apiMethod(...args);
}
