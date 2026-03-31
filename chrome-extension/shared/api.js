/**
 * KG API client for Chrome extension.
 * All methods return Promises. Auth token is read from chrome.storage.local.
 */

const API_BASE = 'https://wordnexus.lol';
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
 * - On 403 rejects with a quota-exceeded error.
 *
 * @param {string} path — relative to API_BASE (e.g. '/api/translate')
 * @param {RequestInit} [opts]
 * @returns {Promise<any>} parsed JSON body
 */
async function apiFetch(path, opts = {}) {
  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(opts.headers || {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers,
  });

  if (res.status === 401) {
    await chrome.storage.local.remove(TOKEN_KEY);
    chrome.runtime.sendMessage({ type: 'auth_expired' }).catch(() => {});
    throw new ApiError('auth_expired', '登入已過期，請重新登入', 401);
  }

  if (res.status === 403) {
    throw new ApiError('quota_exceeded', '已達使用上限', 403);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError('api_error', body || res.statusText, res.status);
  }

  // Some endpoints may return 204 with no body
  if (res.status === 204) return null;
  return res.json();
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
  return apiFetch('/api/translate', {
    method: 'POST',
    body: JSON.stringify({ word, context }),
  });
}

/**
 * Translate a multi-word phrase/sentence with optional context.
 * @param {string} text
 * @param {string} [context]
 */
async function translatePhrase(text, context) {
  return apiFetch('/api/translate/phrase', {
    method: 'POST',
    body: JSON.stringify({ text, context }),
  });
}

/**
 * Get an in-depth explanation for a word with optional context.
 * @param {string} word
 * @param {string} [context]
 */
async function explain(word, context) {
  return apiFetch('/api/explain', {
    method: 'POST',
    body: JSON.stringify({ word, context }),
  });
}

/**
 * Add one or more vocabulary entries.
 * @param {Array<{word: string, context?: string, source_url?: string}>} entries
 */
async function addVocab(entries) {
  return apiFetch('/api/vocabulary', {
    method: 'POST',
    body: JSON.stringify({ entries }),
  });
}

/**
 * List vocabulary, optionally only items updated since a timestamp.
 * @param {string} [since] — ISO 8601 timestamp
 */
async function listVocab(since) {
  const params = since ? `?since=${encodeURIComponent(since)}` : '';
  return apiFetch(`/api/vocabulary${params}`);
}

/**
 * Look up a single word's vocabulary record.
 * @param {string} word
 */
async function lookupWord(word) {
  return apiFetch(`/api/vocabulary/${encodeURIComponent(word)}`);
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

if (typeof globalThis !== 'undefined') {
  globalThis.KGApi = {
    translate,
    translatePhrase,
    explain,
    addVocab,
    listVocab,
    lookupWord,
    apiFetch,
    ApiError,
    getToken,
    API_BASE,
    TOKEN_KEY,
  };
}
