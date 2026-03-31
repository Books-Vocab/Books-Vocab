/**
 * KG Chrome Extension — Background Service Worker
 *
 * Responsibilities:
 * 1. Route API calls from content script / side panel via message passing
 * 2. Receive OAuth token from wordnexus.lol via externally_connectable
 * 3. Open side panel on extension icon click
 */

// Load shared modules into service worker scope
importScripts('shared/api.js', 'shared/theme.js');

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
  if (!sender.url || !sender.url.startsWith('https://wordnexus.lol')) {
    sendResponse({ error: true, message: 'unauthorized origin' });
    return;
  }

  if (msg.type === 'auth_token' && typeof msg.token === 'string') {
    chrome.storage.local.set({ [TOKEN_KEY]: msg.token }).then(() => {
      sendResponse({ ok: true });
    });
    return true; // async
  }

  sendResponse({ error: true, message: 'unknown external message type' });
});

// ---------------------------------------------------------------------------
// Message handler — maps type → API call
// ---------------------------------------------------------------------------

async function handleMessage(msg) {
  switch (msg.type) {
    case 'translate':
      return KGApi.translate(msg.word, msg.context);

    case 'translatePhrase':
      return KGApi.translatePhrase(msg.text, msg.context);

    case 'explain':
      return KGApi.explain(msg.word, msg.context);

    case 'addVocab':
      return KGApi.addVocab(msg.entries);

    case 'listVocab':
      return KGApi.listVocab(msg.since);

    case 'lookupWord':
      return KGApi.lookupWord(msg.word);

    case 'auth_token':
      // Allow internal pages to set token too
      if (typeof msg.token === 'string') {
        await chrome.storage.local.set({ [TOKEN_KEY]: msg.token });
        return { ok: true };
      }
      throw new Error('missing token');

    case 'get_auth_status': {
      const token = await KGApi.getToken();
      return { authenticated: !!token };
    }

    case 'logout':
      await chrome.storage.local.remove(TOKEN_KEY);
      return { ok: true };

    default:
      throw new Error(`unknown message type: ${msg.type}`);
  }
}
