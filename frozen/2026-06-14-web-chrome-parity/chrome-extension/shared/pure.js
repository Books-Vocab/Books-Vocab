/**
 * Pure logic for the Books & Vocab Chrome extension.
 *
 * Everything here is free of `chrome.*`, DOM and network side effects so it can
 * be unit-tested with Node's built-in `node:test` runner (zero dependencies).
 *
 * Consumed by the extension via the global `KGPure` (classic-script pattern,
 * same as `shared/theme.js`) and by `shared/pure.test.js` via CommonJS require.
 */

const VALID_THEMES = ['light', 'dark', 'sepia'];
const DEFAULT_THEME = 'light';
const PUBLIC_WEB_ORIGIN = 'https://wordnexus.lol';
const LOGIN_PATH = '/login';
const NOTEBOOK_PALETTE = [
  { name: '森林', hex: '#B1C5AE' },
  { name: '海洋', hex: '#AFC2D3' },
  { name: '琥珀', hex: '#DEC69C' },
  { name: '紫藤', hex: '#C5B2D0' },
  { name: '珊瑚', hex: '#DCABA4' },
  { name: '石墨', hex: '#AFB2B7' },
  { name: '薄荷', hex: '#B7D2C9' },
  { name: '靛藍', hex: '#ADABCB' },
  { name: '玫瑰', hex: '#DEBAC2' },
  { name: '焦糖', hex: '#D2B69D' },
  { name: '天空', hex: '#C5DAE2' },
  { name: '薰衣草', hex: '#C3BCCF' },
];
const NOTEBOOK_COVER_PATTERNS = [
  { id: 'dots', label: '圓點' },
  { id: 'lines', label: '條紋' },
  { id: 'grid', label: '格線' },
  { id: 'waves', label: '波浪' },
  { id: 'circles', label: '同心圓' },
  { id: 'noise', label: '噪點' },
];
const NOTEBOOK_DEFAULT_COLOR = '#AFC2D3';

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
function buildSinceQuery(since) {
  if (since === undefined || since === null) return '';
  const s = String(since).trim();
  if (!s) return '';
  return `?since=${encodeURIComponent(s)}`;
}

/**
 * Build the query string for `/api/vocab`, optionally filtering by `since` and
 * notebook. `notebook_id` mirrors backend/iOS naming; absence means all notebooks.
 * @param {*} since — ISO 8601 timestamp or falsy
 * @param {*} notebookId — notebook id or falsy
 * @returns {string}
 */
function buildVocabQuery(since, notebookId) {
  const params = [];
  const s = since === undefined || since === null ? '' : String(since).trim();
  if (s) params.push(['since', s]);
  const nb = notebookId === undefined || notebookId === null ? '' : String(notebookId).trim();
  if (nb) params.push(['notebook_id', nb]);
  if (params.length === 0) return '';
  return `?${params.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')}`;
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

function normalizeNotebookList(response) {
  const raw = normalizeVocabList(response);
  return raw.map(normalizeNotebookItem);
}

function normalizeNotebookItem(item) {
  const raw = item && typeof item === 'object' ? item : {};
  return {
    id: raw.id || 'default',
    name: raw.name || '我的單字本',
    color: raw.color || null,
    coverPattern: raw.coverPattern || raw.cover_pattern || null,
    sortOrder: Number(raw.sortOrder ?? raw.sort_order) || 0,
    isDefault: !!(raw.isDefault ?? raw.is_default),
    isDeleted: !!(raw.isDeleted ?? raw.is_deleted),
    cardCount: Number(raw.cardCount ?? raw.card_count) || 0,
    updatedAt: raw.updatedAt || raw.updated_at || null,
  };
}

function validateNotebookName(value) {
  const name = String(value == null ? '' : value).trim();
  if (!name) return { ok: false, value: '', error: 'empty' };
  if (name.length > 100) return { ok: false, value: name, error: 'too_long' };
  return { ok: true, value: name, error: null };
}

function normalizeNotebookColor(value) {
  if (value === undefined) return undefined;
  if (value === null || value === '') return null;
  const color = String(value).trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(color) ? color : undefined;
}

function normalizeNotebookCoverPattern(value) {
  if (value === undefined) return undefined;
  if (value === null || value === '') return null;
  const pattern = String(value).trim();
  return NOTEBOOK_COVER_PATTERNS.some((p) => p.id === pattern) ? pattern : undefined;
}

function buildNotebookPayload(name, color, coverPattern, { includeClears = false } = {}) {
  const valid = validateNotebookName(name);
  if (!valid.ok) return null;
  const payload = { name: valid.value };
  const normalizedColor = normalizeNotebookColor(color);
  const normalizedPattern = normalizeNotebookCoverPattern(coverPattern);
  if (normalizedColor === undefined && color !== undefined) return null;
  if (normalizedPattern === undefined && coverPattern !== undefined) return null;
  if (normalizedColor !== undefined) payload.color = normalizedColor;
  if (normalizedPattern !== undefined) {
    payload.cover_pattern = normalizedPattern === null && includeClears ? '' : normalizedPattern;
  }
  return payload;
}

function buildNotebookCreatePayload(name, color, coverPattern) {
  return buildNotebookPayload(name, color, coverPattern);
}

function buildNotebookUpdatePayload(name, color, coverPattern) {
  return buildNotebookPayload(name, color, coverPattern, { includeClears: true });
}

function canDeleteNotebook(notebook) {
  const nb = notebook && typeof notebook === 'object' ? notebook : null;
  return !!(nb && nb.id && nb.id !== 'default' && !nb.isDefault && !nb.isDeleted);
}

function pendingItemsForNotebook(items, notebookId = 'default') {
  const active = notebookId || 'default';
  return (items || []).filter((item) => ((item && item.notebookId) || 'default') === active);
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
    // filter chips / row progress / sort can mirror iOS's real classification
    // instead of a mock. These feed classifyReviewState / reviewProgress / sortVocab.
    reviewCount: Number(raw.reviewCount) || 0,
    reviewIntervalHours: Number(raw.reviewIntervalHours) || 0,
    nextReviewAt: raw.nextReviewAt || raw.next_review_at || null,
    lastReviewedAt: raw.lastReviewedAt || raw.last_reviewed_at || null,
    // difficultyTier feeds the 'difficulty' sort; updatedAt is the 'dateAdded'
    // sort proxy (CardResponse omits a true creation timestamp).
    difficultyTier: raw.difficultyTier || raw.difficulty_tier || null,
    updatedAt: raw.updatedAt || raw.updated_at || null,
    // Knowledge-graph links + word forms — the data is ALREADY in the list
    // payload (list_vocab_response attaches linksByKind with reason/label/cardId,
    // plus inflections); previously discarded here, now preserved so the detail
    // panel can render KG's knowledge links (對比/相關) and inflected forms.
    // `cardId` (= this card's id) lets link navigation match a link's target
    // cardId against the loaded corpus. Guards: linksByKind must be a plain
    // object (not array/string), inflections must be an array.
    linksByKind:
      raw.linksByKind && typeof raw.linksByKind === 'object' && !Array.isArray(raw.linksByKind)
        ? raw.linksByKind
        : {},
    inflections: Array.isArray(raw.inflections) ? raw.inflections : [],
    cardId: raw.id || raw.cardId || '',
  };
}

// ---------------------------------------------------------------------------
// Example highlighting — port of iOS so the detail panel marks the target word
// in its example sentence identically to the app.
// ---------------------------------------------------------------------------

/**
 * Wrap the first occurrence of `word` in `example` with `**…**` markers,
 * mirroring iOS `VocabularyEntry.markWordInContext` (which mimics the server's
 * `_build_example`). Case-insensitive; the matched substring keeps its original
 * casing. If the word is not found verbatim, falls back to a stem match (the
 * first space-delimited token, 4–6 leading chars, anchored at word edges). When
 * neither matches — or inputs are empty — returns `example` unchanged.
 *
 * Output is PLAIN TEXT carrying inline `**…**` marks — pass it through
 * `parseInlineMarks` to get safely-escapable segments. No HTML is produced here,
 * so this stays injection-free; `word` is treated as a literal (regex-escaped),
 * not a pattern.
 *
 * @param {string} example
 * @param {string} word
 * @returns {string}
 */
function markWordInExample(example, word) {
  const text = typeof example === 'string' ? example : '';
  const w = typeof word === 'string' ? word.trim() : '';
  if (!text || !w) return text;

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  // 1. Verbatim, case-insensitive, first occurrence (original case preserved).
  const direct = text.match(new RegExp(escapeRe(w), 'i'));
  if (direct) {
    const i = direct.index;
    return text.slice(0, i) + '**' + direct[0] + '**' + text.slice(i + direct[0].length);
  }

  // 2. Stem fallback — first token, 4–6 leading chars, word-boundary-anchored
  //    (mirrors iOS `(?<![\w\p{L}])stem\w*(?![\w\p{L}])`). Lookbehind / \p{L}
  //    are modern-V8 features (chrome target); guard in case the engine lacks them.
  const firstWord = w.split(' ')[0] || w;
  if (firstWord.length >= 4) {
    const stem = firstWord.slice(0, Math.min(firstWord.length, 6));
    let stemRe = null;
    try {
      stemRe = new RegExp('(?<![\\w\\p{L}])' + escapeRe(stem) + '\\w*(?![\\w\\p{L}])', 'iu');
    } catch (_err) {
      stemRe = null;
    }
    const m = stemRe && text.match(stemRe);
    if (m) {
      const i = m.index;
      return text.slice(0, i) + '**' + m[0] + '**' + text.slice(i + m[0].length);
    }
  }
  return text;
}

/**
 * Split text containing inline `**…**` / `==…==` marks into typed segments,
 * porting the two highlight cases of iOS `CardMarkdownInlineParser`. Text outside
 * a mark is a `'text'` segment; a non-empty `**x**` or `==x==` span is a `'mark'`
 * segment. Empty spans (`****`) are dropped (matching iOS `if !value.isEmpty`).
 * Unclosed markers are kept as literal text. Other markdown (`` ` ``, `_`) is
 * left literal — examples only ever carry the two highlight syntaxes.
 *
 * Render by escaping each segment's `value`; only `'mark'` segments get a
 * `<mark>` wrapper. No HTML is produced here, so rendering stays injection-safe.
 *
 * @param {string} text
 * @returns {Array<{type:'text'|'mark', value:string}>}
 */
function parseInlineMarks(text) {
  const raw = typeof text === 'string' ? text : '';
  const out = [];
  let buf = '';
  let i = 0;
  const flush = () => {
    if (buf) {
      out.push({ type: 'text', value: buf });
      buf = '';
    }
  };
  while (i < raw.length) {
    const marker = raw.slice(i, i + 2);
    if (marker === '**' || marker === '==') {
      const end = raw.indexOf(marker, i + 2);
      if (end !== -1) {
        flush();
        const value = raw.slice(i + 2, end);
        if (value) out.push({ type: 'mark', value });
        i = end + 2;
        continue;
      }
    }
    buf += raw[i];
    i += 1;
  }
  flush();
  return out;
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

// ---------------------------------------------------------------------------
// Filter + sort — faithful port of iOS VocabularyEntryPresentation so the
// sidepanel's chip multi-select and sort pill behave like KGVocabView.
// ---------------------------------------------------------------------------

/** The 4 sort options in iOS KGVocabSortOption declaration order. */
const VOCAB_SORT_OPTIONS = ['default', 'alphabetical', 'dateAdded', 'difficulty'];

// iOS VocabularyEntryPresentation.tierPriority / reviewPriority.
const _TIER_PRIORITY = { core: 0, intermediate: 1, advanced: 2, rare: 3 };
const _REVIEW_PRIORITY = { due: 0, unlearned: 1, reviewed: 2 };
function _tierPriority(tier) {
  return tier != null && tier in _TIER_PRIORITY ? _TIER_PRIORITY[tier] : 4;
}
function _wordCompare(a, b) {
  return String((a && a.word) || '').localeCompare(
    String((b && b.word) || ''), undefined, { sensitivity: 'accent' });
}

/**
 * Filter a vocab list by search query + selected review states. Mirrors iOS
 * mergedBucket(for:) (empty selection = all states) combined with sortAndFilter's
 * search predicate (case-insensitive substring over word OR meaning/translation).
 * @param {Array<object>} items
 * @param {{query?: string, states?: (Set<string>|Array<string>|null)}} opts
 * @param {number} [nowMs]
 * @returns {Array<object>}
 */
function filterVocab(items, { query = '', states = null } = {}, nowMs = Date.now()) {
  const list = Array.isArray(items) ? items : [];
  const q = String(query || '').trim().toLowerCase();
  const stateSet = states && typeof states.has === 'function'
    ? states
    : new Set(Array.isArray(states) ? states : []);
  const filterByState = stateSet.size > 0;
  return list.filter((item) => {
    if (filterByState && !stateSet.has(classifyReviewState(item, nowMs))) return false;
    if (!q) return true;
    const word = String((item && item.word) || '').toLowerCase();
    const meaning = String((item && item.meaning) || '').toLowerCase();
    return word.includes(q) || meaning.includes(q);
  });
}

/**
 * Sort a vocab list by KGVocabSortOption, mirroring VocabularyEntryPresentation:
 *   default      → reviewPriority(due<unlearned<reviewed) → nextReviewAt asc → tier → word
 *   alphabetical → word A→Z (case-insensitive)
 *   dateAdded    → updatedAt desc (CardResponse lacks dateAdded; updatedAt is the proxy)
 *   difficulty   → tierPriority asc → word
 * Returns a NEW array (input untouched); unknown option falls back to default.
 * Array.sort is stable (Node/V8), so ties preserve input order like iOS.
 */
function sortVocab(items, sortOption = 'default', nowMs = Date.now()) {
  const list = Array.isArray(items) ? items.slice() : [];
  switch (sortOption) {
    case 'alphabetical':
      return list.sort(_wordCompare);
    case 'dateAdded':
      return list.sort((a, b) => (_reviewMs(b.updatedAt) || 0) - (_reviewMs(a.updatedAt) || 0));
    case 'difficulty':
      return list.sort((a, b) => {
        const d = _tierPriority(a.difficultyTier) - _tierPriority(b.difficultyTier);
        return d !== 0 ? d : _wordCompare(a, b);
      });
    case 'default':
    default:
      return list.sort((a, b) => {
        const pa = _REVIEW_PRIORITY[classifyReviewState(a, nowMs)];
        const pb = _REVIEW_PRIORITY[classifyReviewState(b, nowMs)];
        if (pa !== pb) return pa - pb;
        const na = _reviewMs(a.nextReviewAt);
        const nb = _reviewMs(b.nextReviewAt);
        const naSort = na == null ? Infinity : na;
        const nbSort = nb == null ? Infinity : nb;
        if (naSort !== nbSort) return naSort - nbSort;
        const ta = _tierPriority(a.difficultyTier);
        const tb = _tierPriority(b.difficultyTier);
        if (ta !== tb) return ta - tb;
        return _wordCompare(a, b);
      });
  }
}

/**
 * Resolve the vocabulary empty state using the same branch priority as iOS
 * KGVocabEmptyState: whole notebook empty > search > filters > default.
 *
 * @param {{hasNoEntries?: boolean, searchText?: string,
 *          filters?: Set<string>|Array<string>|null}} opts
 * @returns {{kind:string,titleKey:string,descriptionKey:string,systemImage:string}}
 */
function vocabEmptyState({ hasNoEntries = false, searchText = '', filters = null } = {}) {
  const q = String(searchText || '');
  const stateSet = filters && typeof filters.has === 'function'
    ? filters
    : new Set(Array.isArray(filters) ? filters : []);

  if (hasNoEntries) {
    return {
      kind: 'empty',
      titleKey: 'emptyCollectedTitle',
      descriptionKey: 'emptyCollectedSubtitle',
      systemImage: 'books.vertical',
    };
  }

  if (q.length > 0) {
    return {
      kind: 'search',
      titleKey: 'emptySearchTitle',
      descriptionKey: 'emptySearchSubtitle',
      systemImage: 'magnifyingglass',
    };
  }

  if (stateSet.size > 0) {
    let systemImage = 'line.3.horizontal.decrease.circle';
    if (stateSet.size === 1) {
      const state = stateSet.values().next().value;
      if (state === 'unlearned') systemImage = 'sparkles';
      else if (state === 'due') systemImage = 'checkmark.seal';
      else if (state === 'reviewed') systemImage = 'leaf';
    }
    return {
      kind: 'filter',
      titleKey: 'emptyFilterTitle',
      descriptionKey: 'emptyFilterSubtitle',
      systemImage,
    };
  }

  return {
    kind: 'default',
    titleKey: 'emptyCollectedTitle',
    descriptionKey: 'emptySyncedSubtitle',
    systemImage: 'line.3.horizontal.decrease.circle',
  };
}

function _trimmed(str) {
  return String(str == null ? '' : str).trim();
}

function _inlinePlainText(str) {
  return parseInlineMarks(String(str == null ? '' : str))
    .map((seg) => seg.value)
    .join('')
    .trim();
}

/**
 * Build the word-detail share/copy payload, mirroring iOS
 * CardDocument.plainTextExport(): hero, first example, meaning title +
 * paragraphs, collocations, and source, separated by blank lines.
 *
 * @param {object} item — normalized/enriched vocab item
 * @returns {string}
 */
function vocabPlainTextExport(item) {
  const raw = item && typeof item === 'object' ? item : {};
  const lines = [];

  const word = _trimmed(raw.word);
  if (word) {
    const pos = _trimmed(raw.pos);
    lines.push(pos ? `${word} (${pos})` : word);
  }

  const ex0 = Array.isArray(raw.examples) && raw.examples.length ? raw.examples[0] : null;
  const example = typeof ex0 === 'string' ? ex0 : (ex0 && (ex0.sentence || ex0.text)) || '';
  const exampleText = _inlinePlainText(example);
  if (exampleText) lines.push(exampleText);

  const meaning = _trimmed(raw.meaning);
  if (meaning) lines.push(meaning);

  const note = String(raw.note == null ? '' : raw.note)
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map(_inlinePlainText)
    .filter(Boolean);
  lines.push(...note);

  const collocations = Array.isArray(raw.collocations)
    ? raw.collocations
        .map((c) => _trimmed(typeof c === 'string' ? c : (c && c.word) || ''))
        .filter(Boolean)
    : [];
  if (collocations.length) lines.push(collocations.join(', '));

  const source = raw.source && typeof raw.source === 'object' ? raw.source : null;
  if (source) {
    const title = _trimmed(source.title || source.book || source.bookTitle || source.url);
    const chapter = _trimmed(source.chapter || source.chapterTitle);
    const sourceParts = [title, chapter].filter(Boolean);
    if (sourceParts.length) lines.push(`— ${sourceParts.join(' · ')}`);
  }

  return lines.join('\n\n');
}

const DEFAULT_TRANSLATION_CONFIG = { source_lang: 'en', target_lang: 'zh-Hant' };

function _translationValue(raw, fallback) {
  const fb = fallback && typeof fallback === 'object' ? fallback : DEFAULT_TRANSLATION_CONFIG;
  const src = raw && typeof raw === 'object' ? raw : {};
  return {
    source_lang: src.source_lang || fb.source_lang || DEFAULT_TRANSLATION_CONFIG.source_lang,
    target_lang: src.target_lang || fb.target_lang || DEFAULT_TRANSLATION_CONFIG.target_lang,
  };
}

/**
 * Shape options-page translation language state before DOM rendering, mirroring
 * iOS SettingsPresenter: API/storage state in, stable UI state out.
 *
 * @param {{isLoggedIn?:boolean, translation?:object, fallbackTranslation?:object, errorStatus?:number}} input
 * @returns {{translation:{source_lang:string,target_lang:string}, disabled:boolean, hintKey:string|null}}
 */
function optionsTranslationPresentation(input = {}) {
  const fallback = _translationValue(input.fallbackTranslation, DEFAULT_TRANSLATION_CONFIG);
  if (!input.isLoggedIn) {
    return { translation: fallback, disabled: true, hintKey: 'translateLangLoginHint' };
  }
  if (Object.prototype.hasOwnProperty.call(input, 'errorStatus')) {
    return {
      translation: fallback,
      disabled: true,
      hintKey: input.errorStatus === 401 ? 'translateLangLoginHint' : 'translateLangLoadError',
    };
  }
  return {
    translation: _translationValue(input.translation, fallback),
    disabled: false,
    hintKey: null,
  };
}

/**
 * Shape the Pro entitlement row for the options account section.
 * @param {object|null|undefined} pro
 * @returns {{hidden:boolean,badge:string|null,labelKey:string|null,planName:string,isFree:boolean}}
 */
function optionsProPresentation(pro) {
  if (!pro || typeof pro !== 'object') {
    return { hidden: true, badge: null, labelKey: null, planName: '', isFree: false };
  }
  if (pro.is_active) {
    return {
      hidden: false,
      badge: 'PRO',
      labelKey: 'proActive',
      planName: _trimmed(pro.plan_name),
      isFree: false,
    };
  }
  return { hidden: false, badge: null, labelKey: 'proFree', planName: '', isFree: true };
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
  'listNotebooks',
  'createNotebook',
  'updateNotebook',
  'deleteNotebook',
  'retryOutbox',
  'lookupWord',
  'getUserConfig',
  'updateUserConfig',
  'getEntitlements',
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
      return { kind: 'addVocab', args: [msg.entries, msg.notebookId] };
    case 'listVocab':
      return { kind: 'listVocab', args: [msg.since, undefined, msg.notebookId] };
    case 'listNotebooks':
      return { kind: 'listNotebooks', args: [msg.since] };
    case 'createNotebook':
      return { kind: 'createNotebook', args: [msg.notebook] };
    case 'updateNotebook':
      return { kind: 'updateNotebook', args: [msg.notebookId, msg.patch] };
    case 'deleteNotebook':
      return { kind: 'deleteNotebook', args: [msg.notebookId] };
    case 'retryOutbox':
      return { kind: 'retryOutbox', args: [] };
    case 'lookupWord':
      return { kind: 'lookupWord', args: [msg.word] };
    case 'getUserConfig':
      return { kind: 'getUserConfig', args: [] };
    case 'updateUserConfig':
      // Generic user-config patch: forward the whole `config` object (translation
      // / vocab_ui / …) so any group can be PUT without a per-group message type.
      return { kind: 'updateUserConfig', args: [msg.config] };
    case 'getEntitlements':
      return { kind: 'getEntitlements', args: [] };
    case 'get_auth_status':
      return { kind: 'getAuthStatus', args: [] };
    case 'logout':
      return { kind: 'logout', args: [] };
    default:
      throw new Error(`unknown message type: ${type}`);
  }
}

/**
 * Storage key the background worker bumps (to a fresh timestamp) after a
 * vocab-mutating API call succeeds; the side panel watches it via
 * `chrome.storage.onChanged` and silently refreshes its list. Centralised here
 * so the producer (background.js) and consumer (sidepanel/app.js) cannot drift,
 * and the contract is pinned by pure.test.js.
 */
const VOCAB_DIRTY_KEY = 'vocab_dirty';
const ACTIVE_NOTEBOOK_KEY = 'active_notebook_id';

/**
 * Companion key to `ACTIVE_NOTEBOOK_KEY` holding the LWW timestamp (epoch seconds)
 * of the last active-notebook write. Drives the two-layer last-write-wins between
 * chrome.storage.local and the backend `vocab_ui` group (chrome has no iCloud KVS,
 * so backend is the cross-platform bridge to iOS / web). Mirrors the iOS
 * `active_notebook_updated_at` UserDefaults key.
 */
const ACTIVE_NOTEBOOK_UPDATED_KEY = 'active_notebook_updated_at';

/**
 * Two-layer last-write-wins for the active-notebook cursor: chrome.storage.local
 * (local) vs the backend `vocab_ui` group (remote). Picks whichever side carries
 * the newer `updatedAt`; a side with a nil timestamp loses to one that has it;
 * when both lack a timestamp (or tie) local wins. Byte-for-byte aligned with iOS
 * `ActiveNotebookLWW.resolve` so chrome / iOS converge on the same cursor.
 *
 * @param {{id: string, updatedAt: number|null}} local
 * @param {{id: string, updatedAt: number|null}} remote
 * @returns {{id: string, updatedAt: number|null}}
 */
function resolveActiveNotebook(local, remote) {
  const l = local && typeof local.updatedAt === 'number' ? local.updatedAt : null;
  const r = remote && typeof remote.updatedAt === 'number' ? remote.updatedAt : null;
  if (l != null && r != null) return r > l ? remote : local;
  if (l == null && r != null) return remote;
  return local;
}

/**
 * Shape the backend `vocab_ui` config patch (snake_case wire contract, matching
 * `kg.api_models.notebook.VocabUIConfig`). The active-notebook id and its LWW
 * timestamp are written as one atomic group via PUT /api/user/config.
 *
 * @param {string} activeNotebookId
 * @param {number|null} updatedAt — epoch seconds, or null when never set
 * @returns {{vocab_ui: {active_notebook_id: string, updated_at: number|null}}}
 */
function buildVocabUiConfigPatch(activeNotebookId, updatedAt) {
  return {
    vocab_ui: {
      active_notebook_id: activeNotebookId,
      updated_at: updatedAt == null ? null : updatedAt,
    },
  };
}

/**
 * Routed `kind`s whose success means the user's vocab list changed, so any open
 * side panel is now stale. The background worker consults this to decide whether
 * to bump `VOCAB_DIRTY_KEY`. Read-only kinds (listVocab / lookupWord / translate
 * / auth ops) return false — they never invalidate the list. Add future mutating
 * kinds (deleteVocab / updateVocab) to the set as they land.
 *
 * @param {*} kind — a routed kind from `routeMessage().kind`
 * @returns {boolean}
 */
const VOCAB_MUTATING_KINDS = new Set(['addVocab']);
function isVocabMutatingKind(kind) {
  return typeof kind === 'string' && VOCAB_MUTATING_KINDS.has(kind);
}

/**
 * Pick the most natural-sounding TTS voice for `lang` from a `getVoices()` list.
 *
 * Web Speech, given only `utterance.lang`, lets the OS hand back whatever voice
 * it likes — on desktop that is frequently a robotic compact system voice
 * ("Fred"), which is what made the speaker button sound non-human. This ranks
 * the available voices so the speaker matches the iOS AVSpeechSynthesisVoice
 * quality bar.
 *
 * Ranking (high → low): Google cloud voices → names tagged natural/neural/
 * premium/enhanced → exact lang match over a same-base regional one → cloud
 * (`localService === false`) over local → the browser default. Only voices in
 * the SAME base language are eligible — never read English aloud in a Mandarin
 * voice; if none match, returns null so the caller leaves the OS default alone.
 *
 * Pure: no `window` / `speechSynthesis` access — callers pass `getVoices()` in.
 * INLINE-MIRRORED in content/content.js (isolated world, no KGPure) — keep both
 * copies behaviourally in sync (guarded by shared/pure.test.js + a content-script
 * drift check).
 *
 * @param {Array<{name?: string, lang?: string, localService?: boolean, default?: boolean}>} voices
 * @param {string} [lang='en-US']
 * @returns {object|null} the chosen voice, or null when no same-language voice exists
 */
function pickPreferredVoice(voices, lang = 'en-US') {
  if (!Array.isArray(voices) || voices.length === 0) return null;
  const norm = (s) => String(s == null ? '' : s).toLowerCase().replace(/_/g, '-');
  const target = norm(lang);
  const base = target.split('-')[0];
  if (!base) return null;
  const eligible = voices.filter((v) => norm(v && v.lang).split('-')[0] === base);
  if (eligible.length === 0) return null;
  const score = (v) => {
    const name = String((v && v.name) || '');
    let s = 0;
    if (/\bgoogle\b/i.test(name)) s += 100;
    if (/natural|neural|premium|enhanced/i.test(name)) s += 80;
    s += norm(v && v.lang) === target ? 40 : 20;
    if (v && v.localService === false) s += 10;
    if (v && v.default) s += 1;
    return s;
  };
  // Linear max keeps a score tie on the first-listed voice (stable, predictable).
  let best = eligible[0];
  let bestScore = score(best);
  for (let i = 1; i < eligible.length; i++) {
    const s = score(eligible[i]);
    if (s > bestScore) {
      best = eligible[i];
      bestScore = s;
    }
  }
  return best;
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
    const trusted = new URL(PUBLIC_WEB_ORIGIN);
    return parsed.protocol === trusted.protocol && parsed.hostname === trusted.hostname;
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
  PUBLIC_WEB_ORIGIN,
  LOGIN_PATH,
  NOTEBOOK_PALETTE,
  NOTEBOOK_COVER_PATTERNS,
  NOTEBOOK_DEFAULT_COLOR,
  resolveTheme,
  buildPhraseTranslateBody,
  buildSinceQuery,
  buildVocabQuery,
  normalizeVocabList,
  normalizeVocabItem,
  normalizeNotebookList,
  normalizeNotebookItem,
  validateNotebookName,
  normalizeNotebookColor,
  normalizeNotebookCoverPattern,
  buildNotebookCreatePayload,
  buildNotebookUpdatePayload,
  canDeleteNotebook,
  pendingItemsForNotebook,
  classifyReviewState,
  countReviewStates,
  compactReviewLabel,
  reviewProgress,
  VOCAB_SORT_OPTIONS,
  filterVocab,
  sortVocab,
  vocabEmptyState,
  vocabPlainTextExport,
  DEFAULT_TRANSLATION_CONFIG,
  optionsTranslationPresentation,
  optionsProPresentation,
  classifyError,
  pickPreferredVoice,
  ROUTABLE_MESSAGE_TYPES,
  routeMessage,
  VOCAB_DIRTY_KEY,
  ACTIVE_NOTEBOOK_KEY,
  ACTIVE_NOTEBOOK_UPDATED_KEY,
  resolveActiveNotebook,
  buildVocabUiConfigPatch,
  isVocabMutatingKind,
  isTrustedExternalOrigin,
  safeUrl,
  escapeHtml,
  markWordInExample,
  parseInlineMarks,
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
