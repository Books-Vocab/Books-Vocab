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

  if (code === 'quota_exceeded' || status === 403) {
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
  isTrustedExternalOrigin,
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
