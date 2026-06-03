/**
 * Pure logic for the KG Chrome extension.
 *
 * Everything here is free of `chrome.*`, DOM and network side effects so it can
 * be unit-tested with Node's built-in `node:test` runner (zero dependencies).
 *
 * Consumed by the extension via the global `KGPure` (classic-script pattern,
 * same as `shared/theme.js`) and by `shared/pure.test.js` via CommonJS require.
 */

const VALID_THEMES = ['light', 'dark', 'sepia'];
const DEFAULT_THEME = 'light';

/**
 * Build the request body for `/api/translate/phrase`.
 *
 * The backend `TranslateRequest` model keys the translatable text on `word`
 * (NOT `text`) for both the quick and phrase endpoints — a body shaped
 * `{ text, context }` is rejected with HTTP 422. This helper centralises the
 * mapping so the contract stays pinned by `pure.test.js`.
 *
 * @param {string} text — the phrase/sentence to translate
 * @param {string} [context] — surrounding sentence
 * @returns {{word: string, context: string}}
 */
function buildPhraseTranslateBody(text, context) {
  return { word: text, context: context || '' };
}

/**
 * Resolve a possibly-invalid stored value to a known theme name.
 * @param {*} raw
 * @returns {'light'|'dark'|'sepia'}
 */
function resolveTheme(raw) {
  return VALID_THEMES.includes(raw) ? raw : DEFAULT_THEME;
}

/**
 * Build the query string for `/api/vocab`, optionally filtering by `since`.
 * Returns '' when `since` is absent/blank so the path stays unchanged.
 * @param {*} since — ISO 8601 timestamp or falsy
 * @returns {string} e.g. '' or '?since=2024-01-01T00%3A00%3A00Z'
 */
function buildVocabQuery(since) {
  if (since === undefined || since === null) return '';
  const s = String(since).trim();
  if (!s) return '';
  return `?since=${encodeURIComponent(s)}`;
}

/**
 * Normalise a list-vocab API response into a plain array. The endpoint may
 * return a bare array, or an envelope `{ items: [...] }` / `{ data: [...] }`.
 * Anything unexpected collapses to an empty array rather than throwing.
 * @param {*} response
 * @returns {Array<object>}
 */
function normalizeVocabList(response) {
  if (Array.isArray(response)) return response;
  if (response && Array.isArray(response.items)) return response.items;
  if (response && Array.isArray(response.data)) return response.data;
  return [];
}

/**
 * Classify an error response (from the background worker / ApiError.toJSON())
 * into the user-facing presentation used by the side panel error state.
 *
 * @param {{code?: string, status?: number, message?: string}} response
 * @returns {{icon: string, title: string, subtitle: string, btnLabel: string,
 *            action: 'reload'|'login'|'settings'}}
 */
function classifyError(response) {
  const code = response && response.code;
  const status = response && response.status;

  if (code === 'auth_expired' || status === 401) {
    return {
      icon: '🔒',
      title: '請先登入',
      subtitle: '登入後即可同步詞彙',
      btnLabel: '前往登入',
      action: 'login',
    };
  }

  if (code === 'quota_exceeded' || status === 429) {
    return {
      icon: '⏳',
      title: '已達使用上限',
      subtitle: '額度將於明日重置，可前往設定查看',
      btnLabel: '查看額度',
      action: 'settings',
    };
  }

  if (code === 'network_error' || status === 0) {
    return {
      icon: '📡',
      title: '無法連線',
      subtitle: '請檢查網路後重試',
      btnLabel: '重試',
      action: 'reload',
    };
  }

  if (code === 'server_error' || code === 'bad_response' ||
      (typeof status === 'number' && status >= 500)) {
    return {
      icon: '🛠️',
      title: '伺服器忙碌中',
      subtitle: '稍後再試',
      btnLabel: '重試',
      action: 'reload',
    };
  }

  return {
    icon: '⚠️',
    title: '載入失敗',
    subtitle: (response && response.message) || '',
    btnLabel: '重試',
    action: 'reload',
  };
}

/**
 * True when the supplied selection text is a translatable length.
 * Mirrors the content-script bounds (1‥200 chars).
 * @param {*} text
 * @returns {boolean}
 */
function isSelectable(text) {
  if (typeof text !== 'string') return false;
  const len = text.trim().length;
  return len >= 1 && len <= 200;
}

/**
 * Decide whether a selection should be translated as a phrase (long) or a
 * single word. Mirrors the content-script threshold.
 * @param {string} text
 * @returns {boolean}
 */
function isPhrase(text) {
  return typeof text === 'string' && text.length > 50;
}

/**
 * Extract the sentence surrounding `offset` within `text`, using terminal
 * punctuation (incl. CJK) and newlines as boundaries. Result is trimmed and
 * capped at 500 chars. Pure mirror of the content-script `extractContext`
 * boundary scan, decoupled from the DOM `Selection`.
 *
 * @param {string} text
 * @param {number} offset — caret position inside `text`
 * @returns {string}
 */
function extractSentence(text, offset) {
  if (typeof text !== 'string' || !text) return '';
  const breaks = /[.!?。！？\n]/;
  let pos = offset;
  if (!Number.isFinite(pos) || pos < 0) pos = 0;
  if (pos > text.length) pos = text.length;

  let start = pos;
  while (start > 0 && !breaks.test(text[start - 1])) start--;
  let end = pos;
  while (end < text.length && !breaks.test(text[end])) end++;

  return text.slice(start, end).trim().substring(0, 500);
}

/**
 * Build the runtime message a content-script popup sends to the background
 * worker for a given selection. Long selections (`isPhrase`) go to the
 * `/api/translate/phrase` route keyed on `text`; short ones to the quick
 * `translate` route keyed on `word`.
 *
 * Pure mirror of the content-script `createPopup` message-shape decision,
 * decoupled from `chrome.runtime.sendMessage`.
 *
 * @param {string} word — the selected text
 * @param {string} [context] — surrounding sentence
 * @returns {{type:'translate',word:string,context:string}
 *          |{type:'translatePhrase',text:string,context:string}}
 */
function buildSelectionMessage(word, context) {
  const ctx = context == null ? '' : String(context);
  const text = typeof word === 'string' ? word : String(word == null ? '' : word);
  if (isPhrase(text)) {
    return { type: 'translatePhrase', text, context: ctx };
  }
  return { type: 'translate', word: text, context: ctx };
}

/**
 * The set of internal message types the background worker routes. Centralised
 * so `routeMessage` and the worker's `handleMessage` switch stay in sync and
 * the contract is pinned by `pure.test.js`.
 */
const ROUTABLE_MESSAGE_TYPES = [
  'translate',
  'translatePhrase',
  'explain',
  'addVocab',
  'listVocab',
  'lookupWord',
  'get_auth_status',
  'logout',
];

/**
 * Pure descriptor of the background worker's `handleMessage` routing table.
 * Maps an inbound message to `{ kind, args }` — the API method name (or
 * pseudo-kind for storage ops) plus the positional arguments extracted from
 * the message — without invoking `KGApi` or touching `chrome.*`.
 *
 * Throws for unknown types, mirroring `handleMessage`'s `throw new Error(...)`
 * branch so the error contract is testable.
 *
 * Note: token writes are intentionally *not* routable here. The auth token is
 * written exclusively via `onMessageExternal` gated by `isTrustedExternalOrigin`
 * (see `background.js`); there is no internal `auth_token` sender, so exposing
 * an internal `setToken` route would be unguarded dead surface.
 *
 * @param {{type?: string}} msg
 * @returns {{kind: string, args: Array<*>}}
 */
function routeMessage(msg) {
  const type = msg && msg.type;
  switch (type) {
    case 'translate':
      return { kind: 'translate', args: [msg.word, msg.context] };
    case 'translatePhrase':
      return { kind: 'translatePhrase', args: [msg.text, msg.context] };
    case 'explain':
      return { kind: 'explain', args: [msg.word, msg.context] };
    case 'addVocab':
      return { kind: 'addVocab', args: [msg.entries] };
    case 'listVocab':
      return { kind: 'listVocab', args: [msg.since] };
    case 'lookupWord':
      return { kind: 'lookupWord', args: [msg.word] };
    case 'get_auth_status':
      return { kind: 'getAuthStatus', args: [] };
    case 'logout':
      return { kind: 'logout', args: [] };
    default:
      throw new Error(`unknown message type: ${type}`);
  }
}

/**
 * Whether an external sender URL is the trusted KG web origin. Used to gate
 * `onMessageExternal` auth-token injection.
 *
 * Parses the URL and requires an exact host + https scheme, so look-alikes
 * such as `https://wordnexus.lol.evil.com` are rejected (a plain
 * `startsWith('https://wordnexus.lol')` check would accept them).
 *
 * @param {*} url
 * @returns {boolean}
 */
function isTrustedExternalOrigin(url) {
  if (typeof url !== 'string' || !url) return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && parsed.hostname === 'wordnexus.lol';
  } catch (_err) {
    return false;
  }
}

/**
 * Defense-in-depth helper for rendering user-controlled values into `href`
 * (or `src`) attributes.
 *
 * Allowlists only safe schemes — `http:`, `https:`, and `chrome-extension:`
 * (the last is needed for internal pages such as `options/options.html`
 * obtained via `chrome.runtime.getURL`). Anything else — including
 * `javascript:`, `data:`, `vbscript:`, `file:`, scheme-relative `//evil`,
 * or non-strings — collapses to `'#'`, which is inert when navigated.
 *
 * Callers should still HTML-escape the result before string-concatenating
 * it into markup; this helper is *only* about the URL scheme.
 *
 * @param {*} raw
 * @param {string} [fallback='#']
 * @returns {string}
 */
function safeUrl(raw, fallback = '#') {
  if (typeof raw !== 'string' || !raw) return fallback;
  // Strip leading/trailing whitespace + ASCII control chars (U+0000-U+001F,
  // U+007F): browsers ignore these when resolving `href`, so a payload like
  // ` \tjavascript:alert(1)` would otherwise sneak past a naive prefix check.
  // We rely on `URL` for the real parse — this trim just normalises input.
  // eslint-disable-next-line no-control-regex
  const trimmed = raw.replace(/^[\s\x00-\x1f\x7f]+|[\s\x00-\x1f\x7f]+$/g, '');
  if (!trimmed) return fallback;
  try {
    // Use a base so relative URLs (which are safe) still parse; the resulting
    // protocol will be the base's (`https:`) and thus allowlisted.
    const parsed = new URL(trimmed, 'https://invalid.example/');
    const proto = parsed.protocol;
    if (proto === 'http:' || proto === 'https:' || proto === 'chrome-extension:') {
      // Return the normalized href, not the raw input: `URL` percent-encodes
      // characters that are dangerous in an attribute context (notably `"`),
      // closing the attribute-breakout vector at the source.
      return parsed.href;
    }
    return fallback;
  } catch (_err) {
    return fallback;
  }
}

/**
 * Escape HTML special characters so a user-controlled string can be safely
 * concatenated into a markup template literal (e.g. `innerHTML = ...`).
 *
 * Encodes `&`, `<`, `>`, `"` and `'`. The quote characters are encoded so the
 * output is safe to interpolate into a `"`-wrapped (or `'`-wrapped) attribute
 * value — e.g. `href="${escapeHtml(url)}"` — without a raw quote breaking out
 * of the attribute and injecting markup.
 *
 * Pure (no DOM dependency) so it's testable under `node:test`. Mirrored
 * inline by `content/content.js`, which runs in an isolated world without
 * access to KGPure — keep that copy in sync.
 *
 * @param {*} str — coerced to string; `null`/`undefined` become `''`
 * @returns {string}
 */
function escapeHtml(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const KGPureExports = {
  VALID_THEMES,
  DEFAULT_THEME,
  resolveTheme,
  buildPhraseTranslateBody,
  buildVocabQuery,
  normalizeVocabList,
  classifyError,
  isSelectable,
  isPhrase,
  extractSentence,
  buildSelectionMessage,
  ROUTABLE_MESSAGE_TYPES,
  routeMessage,
  isTrustedExternalOrigin,
  safeUrl,
  escapeHtml,
};

// This file is loaded as a *classic* script by the side panel / options page
// (and for side effects by the module service worker), so it must NOT use a
// top-level `export` — that would be a SyntaxError in a classic context.
// Mirrors the `shared/theme.js` global-only pattern.
if (typeof globalThis !== 'undefined') {
  globalThis.KGPure = KGPureExports;
}

// CommonJS export — only reached by Node's `node:test` runner. Browsers never
// define `module`, so this branch is inert in the extension.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = KGPureExports;
}
