/**
 * Books & Vocab API client for the Chrome extension.
 * All methods return Promises. Auth token is read from chrome.storage.local.
 */

const API_BASE = globalThis.KGPure.PUBLIC_WEB_ORIGIN;
const TOKEN_KEY = 'auth_token';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Read the stored auth token.
 * @returns {Promise<string|null>}
 */
async function getToken() {
  const result = await chrome.storage.local.get(TOKEN_KEY);
  return result[TOKEN_KEY] || null;
}

/**
 * Authenticated fetch wrapper.
 * - Attaches Authorization: Bearer header when token exists.
 * - On 401 clears the token and dispatches a re-login notification.
 * - On 429 rejects with a quota-exceeded error (matches backend QuotaExceededError).
 *
 * @param {string} path — relative to API_BASE (e.g. '/api/translate')
 * @param {RequestInit} [opts]
 * @returns {Promise<any>} parsed JSON body
 */
async function apiFetch(path, opts = {}) {
  // `onResponse` is a non-fetch advisory hook (peek at response headers, e.g.
  // X-Pipeline-Pending); strip it so it never leaks into the fetch init.
  const { onResponse, headers: optHeaders, ...fetchOpts } = opts;
  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(optHeaders || {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...fetchOpts,
      headers,
    });
  } catch (err) {
    // Preserve already-typed ApiError (defensive — fetch itself won't throw these).
    if (err instanceof ApiError) throw err;
    // Preserve caller-driven cancellations so they don't masquerade as network failures.
    if (err && (err.name === 'AbortError' || err instanceof DOMException)) throw err;
    // Network failure (DNS, offline, TLS, CORS abort) — fetch rejects with TypeError.
    // Normalise into ApiError so UI can distinguish from auth/api errors.
    throw new ApiError('network_error', '網路連線失敗，請檢查連線後重試', 0);
  }

  if (res.status === 401) {
    await chrome.storage.local.remove(TOKEN_KEY);
    chrome.runtime.sendMessage({ type: 'auth_expired' }).catch(() => {});
    throw new ApiError('auth_expired', '登入已過期，請重新登入', 401);
  }

  // Backend QuotaExceededError surfaces as HTTP 429 (exceptions.py). A 403 is a
  // genuine ForbiddenError (e.g. another user's notebook) — let it fall through
  // to the generic branch rather than mislabel it as a quota hit.
  if (res.status === 429) {
    throw new ApiError('quota_exceeded', '已達使用上限', 429);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    // 5xx — surface as a distinct code so UI can offer "try later" instead of plain retry.
    const code = res.status >= 500 ? 'server_error' : 'api_error';
    throw new ApiError(code, body || res.statusText || `HTTP ${res.status}`, res.status);
  }

  // Advisory header peek on a successful response (e.g. X-Pipeline-Pending).
  // Must never break the call — a throwing hook is swallowed.
  if (onResponse) {
    try {
      onResponse(res);
    } catch (_err) {
      /* advisory only */
    }
  }

  // Some endpoints may return 204 with no body
  if (res.status === 204) return null;

  // A 2xx with a malformed/empty JSON body must not crash the caller — fetch's
  // res.json() rejects with a SyntaxError. Normalise into an ApiError.
  try {
    return await res.json();
  } catch (_err) {
    throw new ApiError('bad_response', '伺服器回應格式錯誤', res.status);
  }
}

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

class ApiError extends Error {
  /**
   * @param {string} code
   * @param {string} message
   * @param {number} status
   */
  constructor(code, message, status) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }

  toJSON() {
    return { error: true, code: this.code, message: this.message, status: this.status };
  }
}

// ---------------------------------------------------------------------------
// Public API methods
// ---------------------------------------------------------------------------

/**
 * Translate a single word with optional surrounding context.
 * @param {string} word
 * @param {string} [context]
 */
async function translate(word, context) {
  return apiFetch('/api/translate/quick', {
    method: 'POST',
    body: JSON.stringify({ word, context }),
  });
}

/**
 * Translate a multi-word phrase/sentence with optional context.
 *
 * The backend `/api/translate/phrase` endpoint keys the translatable text on
 * `word` (shared `TranslateRequest` model) — see `buildPhraseTranslateBody`.
 * @param {string} text
 * @param {string} [context]
 */
async function translatePhrase(text, context) {
  return apiFetch('/api/translate/phrase', {
    method: 'POST',
    body: JSON.stringify(globalThis.KGPure.buildPhraseTranslateBody(text, context)),
  });
}

/**
 * Get an in-depth explanation for a word with optional context.
 * @param {string} word
 * @param {string} [context]
 */
async function explain(word, context) {
  return apiFetch('/api/translate/explain', {
    method: 'POST',
    body: JSON.stringify({ word, context }),
  });
}

/**
 * Add one or more vocabulary entries.
 *
 * Each entry must match the backend `VocabEntry` model: `word` + `translation`
 * are required, `context` optional, and `source` is a `VocabSource` object
 * `{type: 'web'|'book', title?, url?}` — NOT a flat `source_url` string.
 * @param {Array<{word: string, translation: string, context?: string,
 *   source?: {type: string, title?: string, url?: string}}>} entries
 */
async function addVocab(entries, notebookId = 'default') {
  const nb = encodeURIComponent(notebookId || 'default');
  return apiFetch(`/api/vocab?notebook_id=${nb}`, {
    method: 'POST',
    body: JSON.stringify(entries),
  });
}

/**
 * List vocabulary, optionally only items updated since a timestamp.
 * @param {string} [since] — ISO 8601 timestamp
 * @param {(res: Response) => void} [onResponse] — advisory header peek (e.g. to
 *   read X-Pipeline-Pending during enrich polling)
 */
async function listVocab(since, onResponse, notebookId) {
  const params = globalThis.KGPure.buildVocabQuery(since, notebookId);
  return apiFetch(`/api/vocab${params}`, onResponse ? { onResponse } : {});
}

/**
 * List notebooks, optionally only items updated since a timestamp.
 * @param {string} [since]
 */
async function listNotebooks(since) {
  const params = globalThis.KGPure.buildSinceQuery(since);
  return apiFetch(`/api/notebooks${params}`);
}

/**
 * Create a notebook.
 * @param {{name:string, color?:string|null, cover_pattern?:string|null}} notebook
 */
async function createNotebook(notebook) {
  return apiFetch('/api/notebooks', {
    method: 'POST',
    body: JSON.stringify(notebook),
  });
}

/**
 * Update a notebook.
 * @param {string} notebookId
 * @param {{name?:string, color?:string|null, cover_pattern?:string|null, sort_order?:number}} patch
 */
async function updateNotebook(notebookId, patch) {
  return apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

/**
 * Delete a notebook.
 * @param {string} notebookId
 */
async function deleteNotebook(notebookId) {
  return apiFetch(`/api/notebooks/${encodeURIComponent(notebookId)}`, { method: 'DELETE' });
}

/**
 * Trigger the server-side enrichment pipeline for a notebook (POST /api/pipeline).
 * No request body — notebook_id is a query param. The backend enriches "bare"
 * cards (no pos/note) in the background and returns a queue ack immediately;
 * results are observed by re-pulling GET /api/vocab. Mirrors iOS
 * `KGService.triggerPipeline`.
 * @param {string} [notebookId]
 */
async function triggerPipeline(notebookId = 'default') {
  const nb = encodeURIComponent(notebookId);
  return apiFetch(`/api/pipeline?notebook_id=${nb}`, { method: 'POST' });
}

/**
 * Look up a single word's vocabulary record.
 * @param {string} word
 */
async function lookupWord(word) {
  return apiFetch(`/api/vocab/${encodeURIComponent(word)}`);
}

/**
 * Read the current user's config (translation source/target language).
 * GET /api/user/config → { translation: { source_lang, target_lang } }.
 */
async function getUserConfig() {
  return apiFetch('/api/user/config');
}

/**
 * Update the user's config (partial patch). PUT /api/user/config with any subset
 * of config groups → the updated UserConfigResponse. The body is the patch object
 * itself, e.g. `{ translation: {source_lang, target_lang} }` or
 * `{ vocab_ui: {active_notebook_id, updated_at} }`; only the groups present are
 * updated server-side (kg/user_handlers.py `_merge_user_config`). Server validates
 * translation source_lang ∈ {en,ja,ko,fr,de,es} and target_lang ∈
 * {zh-Hant,zh-Hans,en,ja,ko} (kg/languages.py) — a bad pair 422s.
 * @param {{translation?: object, vocab_ui?: object}} config — the config patch
 */
async function updateUserConfig(config) {
  return apiFetch('/api/user/config', {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

/**
 * Read the user's entitlements (Pro subscription status).
 * GET /api/user/entitlements → { pro: { is_active, plan_name, status, … } }.
 */
async function getEntitlements() {
  return apiFetch('/api/user/entitlements');
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

// ES module exports (for background.js service worker)
export {
  translate,
  translatePhrase,
  explain,
  addVocab,
  listVocab,
  listNotebooks,
  createNotebook,
  updateNotebook,
  deleteNotebook,
  triggerPipeline,
  lookupWord,
  getUserConfig,
  updateUserConfig,
  getEntitlements,
  apiFetch,
  ApiError,
  getToken,
  API_BASE,
  TOKEN_KEY,
};
