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
 * Normalise a single raw vocab payload into one canonical shape, collapsing the
 * snake_case-vs-camelCase / legacy field aliases the panel must otherwise paper
 * over at every read site. The side panel renders from canonical names only.
 *
 * Field aliases (first non-empty wins):
 *   word    ← content | word
 *   meaning ← meaning | translation
 *   context ← context_sentence | context
 *
 * Pass-through fields (kept as-is, defaulted so reads never hit `undefined`):
 *   pos (string), note (string), examples (array), collocations (array),
 *   source (object|null).
 *
 * @param {object} item — raw vocab object from the API / iOS payload
 * @returns {{word:string, meaning:string, pos:string, note:string,
 *            context:string, examples:Array, collocations:Array,
 *            source:object|null}}
 */
function normalizeVocabItem(item) {
  const raw = item && typeof item === 'object' ? item : {};
  return {
    word: raw.content || raw.word || '',
    meaning: raw.meaning || raw.translation || '',
    pos: raw.pos || '',
    note: raw.note || '',
    context: raw.context_sentence || raw.context || '',
    examples: Array.isArray(raw.examples) ? raw.examples : [],
    collocations: Array.isArray(raw.collocations) ? raw.collocations : [],
    source: raw.source || null,
    // Review state (CardResponse) — preserved at the single ingress point so the
    // filter chips / row progress can mirror iOS's real classification instead of
    // a mock. djb2 mocks are gone; these feed classifyReviewState / reviewProgress.
    reviewCount: Number(raw.reviewCount) || 0,
    reviewIntervalHours: Number(raw.reviewIntervalHours) || 0,
    nextReviewAt: raw.nextReviewAt || raw.next_review_at || null,
    lastReviewedAt: raw.lastReviewedAt || raw.last_reviewed_at || null,
  };
}

// ---------------------------------------------------------------------------
// Review state — faithful port of iOS VocabularyReview + WordRowPresentation so
// the sidepanel classifies/visualizes review progress identically to the app.
// ---------------------------------------------------------------------------

/** Parse an ISO-ish date string to epoch ms; null/blank/invalid → null. */
function _reviewMs(v) {
  if (v == null || v === '') return null;
  const t = Date.parse(v);
  return Number.isNaN(t) ? null : t;
}

/**
 * Classify a vocab card into iOS's three review states. Mirrors
 * VocabularyEntry.reviewState(at:):
 *   reviewCount == 0     → 'unlearned'
 *   nextReviewAt <= now  → 'due'
 *   else                 → 'reviewed'
 * A reviewed card with no schedule (missing nextReviewAt) is treated as not-due.
 * @param {object} item — a normalizeVocabItem result (or raw CardResponse)
 * @param {number} [nowMs]
 * @returns {'unlearned'|'due'|'reviewed'}
 */
function classifyReviewState(item, nowMs = Date.now()) {
  const raw = item && typeof item === 'object' ? item : {};
  if ((Number(raw.reviewCount) || 0) <= 0) return 'unlearned';
  const next = _reviewMs(raw.nextReviewAt);
  if (next == null) return 'reviewed';
  return next <= nowMs ? 'due' : 'reviewed';
}

/**
 * Tally a list into per-state counts for the filter chips (mirrors iOS chip
 * counts derived from the same predicate).
 * @returns {{unlearned:number, due:number, reviewed:number}}
 */
function countReviewStates(items, nowMs = Date.now()) {
  const counts = { unlearned: 0, due: 0, reviewed: 0 };
  (Array.isArray(items) ? items : []).forEach((it) => {
    counts[classifyReviewState(it, nowMs)] += 1;
  });
  return counts;
}

/** iOS Double.singleDecimalString: one decimal, integers drop the point. */
function _singleDecimal(n) {
  const r = Math.round(n * 10) / 10;
  return r === Math.round(r) ? String(Math.round(r)) : r.toFixed(1);
}

/**
 * iOS TimeInterval.compactReviewLabel: <1h → "Nm" (≥1); <1d → "N.Nh"/"Nh";
 * else "N.Nd"/"Nd". Negative clamps to 0.
 * @param {number} seconds
 * @returns {string}
 */
function compactReviewLabel(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const HOUR = 3600;
  const DAY = 86400;
  if (s < HOUR) return `${Math.max(1, Math.round(s / 60))}m`;
  if (s < DAY) {
    const h = s / HOUR;
    return h < 10 ? `${_singleDecimal(h)}h` : `${Math.round(h)}h`;
  }
  const d = s / DAY;
  return d < 10 ? `${_singleDecimal(d)}d` : `${Math.round(d)}d`;
}

/**
 * Per-row review progress, mirroring WordRowPresentation.reviewProgressData:
 *   unlearned → ratio null (label-only, no bar)
 *   due/reviewed → ratio = max(elapsed / interval, 0), where
 *     start    = lastReviewedAt ?? (nextReviewAt − reviewIntervalHours)   [iOS uses dateAdded;
 *                CardResponse omits it, so derive from the schedule instead]
 *     interval = max(nextReviewAt − start, 60s)
 *     elapsed  = max(0, now − start)
 * @returns {{state:string, ratio:(number|null), elapsedSec:number,
 *            intervalSec:number, intervalHours:number}}
 */
function reviewProgress(item, nowMs = Date.now()) {
  const raw = item && typeof item === 'object' ? item : {};
  const state = classifyReviewState(raw, nowMs);
  const intervalHours = Number(raw.reviewIntervalHours) || 0;
  if (state === 'unlearned') {
    return { state, ratio: null, elapsedSec: 0, intervalSec: 0, intervalHours };
  }
  const next = _reviewMs(raw.nextReviewAt);
  let start = _reviewMs(raw.lastReviewedAt);
  if (start == null) {
    start = next != null ? next - intervalHours * 3600 * 1000 : nowMs;
  }
  const nextMs = next != null ? next : start + Math.max(intervalHours * 3600 * 1000, 60000);
  const intervalSec = Math.max((nextMs - start) / 1000, 60);
  const elapsedSec = Math.max(0, (nowMs - start) / 1000);
  return { state, ratio: Math.max(elapsedSec / intervalSec, 0), elapsedSec, intervalSec, intervalHours };
}

/**
 * Classify an error response (from the background worker / ApiError.toJSON())
 * into the user-facing presentation used by the side panel error state.
 *
 * @param {{code?: string, status?: number, message?: string}} response
 * @returns {{icon: string, title: string, subtitle: string, btnLabel: string,
 *            action: 'reload'|'login'|'settings'}} `icon` is a KGIcons name
 *            (error-login/quota/network/server/generic), rendered as SVG by the
 *            side panel — not an emoji. pure.js stays data-only (no SVG here).
 */
function classifyError(response) {
  const code = response && response.code;
  const status = response && response.status;

  if (code === 'auth_expired' || status === 401) {
    return {
      icon: 'error-login',
      title: '請先登入',
      subtitle: '登入後即可同步詞彙',
      btnLabel: '前往登入',
      action: 'login',
    };
  }

  if (code === 'quota_exceeded' || status === 429) {
    return {
      icon: 'error-quota',
      title: '已達使用上限',
      subtitle: '額度將於明日重置，可前往設定查看',
      btnLabel: '查看額度',
      action: 'settings',
    };
  }

  if (code === 'network_error' || status === 0) {
    return {
      icon: 'error-network',
      title: '無法連線',
      subtitle: '請檢查網路後重試',
      btnLabel: '重試',
      action: 'reload',
    };
  }

  if (code === 'server_error' || code === 'bad_response' ||
      (typeof status === 'number' && status >= 500)) {
    return {
      icon: 'error-server',
      title: '伺服器忙碌中',
      subtitle: '稍後再試',
      btnLabel: '重試',
      action: 'reload',
    };
  }

  return {
    icon: 'error-generic',
    title: '載入失敗',
    subtitle: (response && response.message) || '',
    btnLabel: '重試',
    action: 'reload',
  };
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
  normalizeVocabItem,
  classifyReviewState,
  countReviewStates,
  compactReviewLabel,
  reviewProgress,
  classifyError,
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
