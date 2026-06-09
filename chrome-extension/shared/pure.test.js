/**
 * Unit tests for shared/pure.js.
 *
 * Zero external dependencies — uses only Node's built-in `node:test` runner.
 * Run from the chrome-extension/ directory:
 *
 *   node --test
 *
 * or target this file directly:
 *
 *   node --test shared/pure.test.js
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  resolveTheme,
  buildPhraseTranslateBody,
  buildSinceQuery,
  buildVocabQuery,
  normalizeVocabList,
  normalizeVocabItem,
  normalizeNotebookList,
  normalizeNotebookItem,
  validateNotebookName,
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
  optionsTranslationPresentation,
  optionsProPresentation,
  classifyError,
  pickPreferredVoice,
  ROUTABLE_MESSAGE_TYPES,
  routeMessage,
  isVocabMutatingKind,
  VOCAB_DIRTY_KEY,
  isTrustedExternalOrigin,
  safeUrl,
  escapeHtml,
  markWordInExample,
  parseInlineMarks,
  VALID_THEMES,
  DEFAULT_THEME,
  PUBLIC_WEB_ORIGIN,
  LOGIN_PATH,
  NOTEBOOK_PALETTE,
  NOTEBOOK_COVER_PATTERNS,
  ACTIVE_NOTEBOOK_KEY,
  ACTIVE_NOTEBOOK_UPDATED_KEY,
  resolveActiveNotebook,
  buildVocabUiConfigPatch,
} = require('./pure.js');

// ---------------------------------------------------------------------------
// resolveTheme
// ---------------------------------------------------------------------------

test('resolveTheme keeps valid theme names', () => {
  for (const t of VALID_THEMES) {
    assert.equal(resolveTheme(t), t);
  }
});

test('resolveTheme falls back to default for invalid input', () => {
  assert.equal(resolveTheme('neon'), DEFAULT_THEME);
  assert.equal(resolveTheme(undefined), DEFAULT_THEME);
  assert.equal(resolveTheme(null), DEFAULT_THEME);
  assert.equal(resolveTheme(''), DEFAULT_THEME);
  assert.equal(resolveTheme(42), DEFAULT_THEME);
});

// ---------------------------------------------------------------------------
// buildPhraseTranslateBody
// ---------------------------------------------------------------------------

test('buildPhraseTranslateBody keys the text on `word` (backend contract)', () => {
  // The backend TranslateRequest model requires `word` (min_length=1); a body
  // shaped { text, context } is rejected with HTTP 422.
  const body = buildPhraseTranslateBody('a long phrase to translate', 'ctx');
  assert.deepEqual(body, { word: 'a long phrase to translate', context: 'ctx' });
  assert.equal('text' in body, false);
});

test('buildPhraseTranslateBody defaults a missing context to empty string', () => {
  assert.deepEqual(buildPhraseTranslateBody('phrase'), { word: 'phrase', context: '' });
  assert.deepEqual(buildPhraseTranslateBody('phrase', undefined), { word: 'phrase', context: '' });
  assert.deepEqual(buildPhraseTranslateBody('phrase', null), { word: 'phrase', context: '' });
});

// ---------------------------------------------------------------------------
// buildVocabQuery
// ---------------------------------------------------------------------------

test('buildVocabQuery returns empty string when since is absent', () => {
  assert.equal(buildVocabQuery(undefined), '');
  assert.equal(buildVocabQuery(null), '');
  assert.equal(buildVocabQuery(''), '');
  assert.equal(buildVocabQuery('   '), '');
});

test('buildVocabQuery URL-encodes the since timestamp', () => {
  assert.equal(
    buildVocabQuery('2024-01-01T00:00:00Z'),
    '?since=2024-01-01T00%3A00%3A00Z',
  );
});

test('buildVocabQuery trims surrounding whitespace before encoding', () => {
  assert.equal(buildVocabQuery('  2024-01-01  '), '?since=2024-01-01');
});

test('buildVocabQuery encodes characters that would break the query', () => {
  assert.equal(buildVocabQuery('a&b=c'), '?since=a%26b%3Dc');
});

test('buildSinceQuery builds a since-only query for non-vocab endpoints', () => {
  assert.equal(buildSinceQuery(undefined), '');
  assert.equal(buildSinceQuery(' 2024-01-01T00:00:00Z '), '?since=2024-01-01T00%3A00%3A00Z');
});

test('buildVocabQuery can scope to a notebook_id', () => {
  assert.equal(buildVocabQuery(undefined, 'nb-reading'), '?notebook_id=nb-reading');
  assert.equal(
    buildVocabQuery('2024-01-01T00:00:00Z', 'nb reading'),
    '?since=2024-01-01T00%3A00%3A00Z&notebook_id=nb%20reading',
  );
});

test('content script ACTIVE_NOTEBOOK_KEY inline mirror stays in sync', () => {
  const src = fs.readFileSync(path.join(__dirname, '../content/content.js'), 'utf8');
  assert.match(src, new RegExp(`const ACTIVE_NOTEBOOK_KEY = '${ACTIVE_NOTEBOOK_KEY}'`));
});

test('content script ACTIVE_NOTEBOOK_UPDATED_KEY inline mirror stays in sync', () => {
  const src = fs.readFileSync(path.join(__dirname, '../content/content.js'), 'utf8');
  assert.match(src, new RegExp(`const ACTIVE_NOTEBOOK_UPDATED_KEY = '${ACTIVE_NOTEBOOK_UPDATED_KEY}'`));
});

// ---------------------------------------------------------------------------
// normalizeVocabList
// ---------------------------------------------------------------------------

test('normalizeVocabList passes a bare array through', () => {
  const arr = [{ content: 'apple' }];
  assert.equal(normalizeVocabList(arr), arr);
});

test('normalizeVocabList unwraps an { items } envelope', () => {
  const items = [{ content: 'banana' }];
  assert.deepEqual(normalizeVocabList({ items }), items);
});

test('normalizeVocabList unwraps a { data } envelope', () => {
  const data = [{ content: 'cherry' }];
  assert.deepEqual(normalizeVocabList({ data }), data);
});

test('normalizeVocabList collapses unexpected shapes to []', () => {
  assert.deepEqual(normalizeVocabList(null), []);
  assert.deepEqual(normalizeVocabList(undefined), []);
  assert.deepEqual(normalizeVocabList('oops'), []);
  assert.deepEqual(normalizeVocabList(42), []);
  assert.deepEqual(normalizeVocabList({ items: 'not-array' }), []);
  assert.deepEqual(normalizeVocabList({}), []);
});

test('normalizeNotebookList unwraps arrays/envelopes and collapses invalid shapes', () => {
  const items = [{ id: 'default', name: '我的單字本' }];
  assert.deepEqual(normalizeNotebookList(items), items.map(normalizeNotebookItem));
  assert.deepEqual(normalizeNotebookList({ items }), items.map(normalizeNotebookItem));
  assert.deepEqual(normalizeNotebookList({ data: items }), items.map(normalizeNotebookItem));
  assert.deepEqual(normalizeNotebookList(null), []);
});

test('normalizeNotebookItem canonicalizes notebook API fields', () => {
  assert.deepEqual(
    normalizeNotebookItem({
      id: 'nb1',
      name: '閱讀',
      color: '#AABBCC',
      coverPattern: 'grid',
      sortOrder: 2,
      isDefault: false,
      isDeleted: true,
      cardCount: 7,
      updatedAt: '2026-06-06T00:00:00Z',
    }),
    {
      id: 'nb1',
      name: '閱讀',
      color: '#AABBCC',
      coverPattern: 'grid',
      sortOrder: 2,
      isDefault: false,
      isDeleted: true,
      cardCount: 7,
      updatedAt: '2026-06-06T00:00:00Z',
    },
  );
  assert.equal(normalizeNotebookItem({}).id, 'default');
  assert.equal(normalizeNotebookItem({}).name, '我的單字本');
});

test('validateNotebookName mirrors backend bounds and trims input', () => {
  assert.deepEqual(validateNotebookName(' 閱讀 '), { ok: true, value: '閱讀', error: null });
  assert.equal(validateNotebookName('   ').ok, false);
  assert.equal(validateNotebookName('x'.repeat(101)).ok, false);
  assert.equal(validateNotebookName(null).ok, false);
});

test('buildNotebookCreatePayload / update payload use backend field names', () => {
  assert.deepEqual(buildNotebookCreatePayload(' 閱讀 '), { name: '閱讀' });
  assert.deepEqual(buildNotebookUpdatePayload(' 新名字 '), { name: '新名字' });
  assert.equal(buildNotebookCreatePayload('  '), null);
  assert.equal(buildNotebookUpdatePayload('x'.repeat(101)), null);
});

test('notebook appearance constants mirror the iOS/backend contract', () => {
  assert.deepEqual(
    NOTEBOOK_COVER_PATTERNS.map((p) => p.id),
    ['dots', 'lines', 'grid', 'waves', 'circles', 'noise'],
  );
  assert.equal(NOTEBOOK_PALETTE.length, 12);
  assert.ok(NOTEBOOK_PALETTE.every((c) => /^#[0-9A-F]{6}$/.test(c.hex)));
});

test('notebook payloads carry validated cover color and pattern', () => {
  assert.deepEqual(buildNotebookCreatePayload(' 閱讀 ', '#AFC2D3', 'grid'), {
    name: '閱讀',
    color: '#AFC2D3',
    cover_pattern: 'grid',
  });
  assert.deepEqual(buildNotebookUpdatePayload(' 新名字 ', '#afc2d3', null), {
    name: '新名字',
    color: '#AFC2D3',
    cover_pattern: '',
  });
  assert.equal(buildNotebookCreatePayload('閱讀', 'blue', 'grid'), null);
  assert.equal(buildNotebookCreatePayload('閱讀', '#AFC2D3', 'stripes'), null);
});

test('canDeleteNotebook blocks default/deleted/missing notebooks', () => {
  assert.equal(canDeleteNotebook({ id: 'default', isDefault: true, isDeleted: false }), false);
  assert.equal(canDeleteNotebook({ id: 'nb1', isDefault: false, isDeleted: false }), true);
  assert.equal(canDeleteNotebook({ id: 'nb1', isDefault: false, isDeleted: true }), false);
  assert.equal(canDeleteNotebook(null), false);
});

test('pendingItemsForNotebook keeps only the active notebook optimistic rows', () => {
  const items = [
    { word: 'alpha', notebookId: 'default' },
    { word: 'beta', notebookId: 'nb-reading' },
    { word: 'gamma' },
  ];
  assert.deepEqual(pendingItemsForNotebook(items, 'nb-reading'), [{ word: 'beta', notebookId: 'nb-reading' }]);
  assert.deepEqual(pendingItemsForNotebook(items, 'default').map((i) => i.word), ['alpha', 'gamma']);
});

// ---------------------------------------------------------------------------
// Review state — classify / count / compactReviewLabel / reviewProgress
// (mirrors iOS VocabularyReview + WordRowPresentation)
// ---------------------------------------------------------------------------

const NOW = Date.parse('2024-06-01T12:00:00Z');
const HOUR_MS = 3600 * 1000;
const DAY_MS = 86400 * 1000;

test('classifyReviewState: reviewCount 0 → unlearned (even if nextReviewAt past)', () => {
  assert.equal(
    classifyReviewState({ reviewCount: 0, nextReviewAt: '2000-01-01T00:00:00Z' }, NOW),
    'unlearned'
  );
});

test('classifyReviewState: reviewed once, nextReviewAt in past → due', () => {
  const item = { reviewCount: 2, nextReviewAt: new Date(NOW - HOUR_MS).toISOString() };
  assert.equal(classifyReviewState(item, NOW), 'due');
});

test('classifyReviewState: nextReviewAt exactly now → due (<=)', () => {
  const item = { reviewCount: 1, nextReviewAt: new Date(NOW).toISOString() };
  assert.equal(classifyReviewState(item, NOW), 'due');
});

test('classifyReviewState: reviewed, nextReviewAt in future → reviewed', () => {
  const item = { reviewCount: 1, nextReviewAt: new Date(NOW + DAY_MS).toISOString() };
  assert.equal(classifyReviewState(item, NOW), 'reviewed');
});

test('classifyReviewState: reviewed but missing schedule → reviewed (not due)', () => {
  assert.equal(classifyReviewState({ reviewCount: 3, nextReviewAt: null }, NOW), 'reviewed');
});

test('countReviewStates tallies the three buckets; non-array → all zero', () => {
  const items = [
    { reviewCount: 0 },
    { reviewCount: 1, nextReviewAt: new Date(NOW - HOUR_MS).toISOString() },
    { reviewCount: 1, nextReviewAt: new Date(NOW - HOUR_MS).toISOString() },
    { reviewCount: 5, nextReviewAt: new Date(NOW + DAY_MS).toISOString() },
  ];
  assert.deepEqual(countReviewStates(items, NOW), { unlearned: 1, due: 2, reviewed: 1 });
  assert.deepEqual(countReviewStates(null, NOW), { unlearned: 0, due: 0, reviewed: 0 });
});

test('compactReviewLabel matches iOS thresholds', () => {
  assert.equal(compactReviewLabel(0), '1m');          // floor at 1m
  assert.equal(compactReviewLabel(90), '2m');         // 1.5m → round 2
  assert.equal(compactReviewLabel(3600), '1h');       // exactly 1h → "1h"
  assert.equal(compactReviewLabel(5400), '1.5h');     // 1.5h
  assert.equal(compactReviewLabel(36 * 3600), '1.5d'); // 1.5d
  assert.equal(compactReviewLabel(15 * 86400), '15d'); // ≥10d → integer
  assert.equal(compactReviewLabel(86400), '1d');      // exactly 1d → "1d"
  assert.equal(compactReviewLabel(-5), '1m');         // negative clamps
});

test('reviewProgress: unlearned → ratio null, no interval', () => {
  const p = reviewProgress({ reviewCount: 0, reviewIntervalHours: 12 }, NOW);
  assert.equal(p.state, 'unlearned');
  assert.equal(p.ratio, null);
  assert.equal(p.intervalHours, 12);
});

test('reviewProgress: due card halfway through its interval → ratio ~0.5', () => {
  const start = NOW - DAY_MS;               // lastReviewed 1d ago
  const next = NOW + DAY_MS;                // due in 1d → 2d interval, 1d elapsed
  const p = reviewProgress({
    reviewCount: 2,
    lastReviewedAt: new Date(start).toISOString(),
    nextReviewAt: new Date(next).toISOString(),
  }, NOW);
  assert.equal(p.state, 'reviewed'); // next in future
  assert.ok(Math.abs(p.ratio - 0.5) < 1e-9, `ratio ${p.ratio}`);
  assert.equal(p.intervalSec, 2 * 86400);
  assert.equal(p.elapsedSec, 86400);
});

test('reviewProgress: missing lastReviewedAt derives start from nextReviewAt − interval', () => {
  const next = NOW + 6 * HOUR_MS;
  const p = reviewProgress({
    reviewCount: 1,
    reviewIntervalHours: 12,
    nextReviewAt: new Date(next).toISOString(),
  }, NOW);
  // start = next − 12h; interval = 12h; elapsed = 12h − 6h = 6h → ratio 0.5
  assert.equal(p.intervalSec, 12 * 3600);
  assert.ok(Math.abs(p.ratio - 0.5) < 1e-9, `ratio ${p.ratio}`);
});

test('reviewProgress: reviewed but missing nextReviewAt derives interval from intervalHours', () => {
  // classifyReviewState → reviewed (no schedule); start derived = now (no last/next),
  // nextMs = start + max(interval,60s). elapsed 0 → ratio 0, intervalSec = 8h.
  const p = reviewProgress({ reviewCount: 2, reviewIntervalHours: 8, nextReviewAt: null }, NOW);
  assert.equal(p.state, 'reviewed');
  assert.equal(p.intervalSec, 8 * 3600);
  assert.equal(p.ratio, 0);
});

test('reviewProgress: overdue card yields ratio > 1 (bar caller clamps)', () => {
  const start = NOW - 3 * DAY_MS;
  const next = NOW - DAY_MS;                 // overdue: elapsed 3d, interval 2d
  const p = reviewProgress({
    reviewCount: 4,
    lastReviewedAt: new Date(start).toISOString(),
    nextReviewAt: new Date(next).toISOString(),
  }, NOW);
  assert.equal(p.state, 'due');
  assert.ok(p.ratio > 1, `ratio ${p.ratio}`);
});

test('normalizeVocabItem preserves review-state fields for classification', () => {
  const out = normalizeVocabItem({
    content: 'apple', meaning: '蘋果',
    reviewCount: 3, reviewIntervalHours: 24,
    nextReviewAt: '2024-06-02T00:00:00Z', lastReviewedAt: '2024-06-01T00:00:00Z',
  });
  assert.equal(out.reviewCount, 3);
  assert.equal(out.reviewIntervalHours, 24);
  assert.equal(out.nextReviewAt, '2024-06-02T00:00:00Z');
  assert.equal(out.lastReviewedAt, '2024-06-01T00:00:00Z');
});

test('normalizeVocabItem review-state fields default safely when absent', () => {
  const out = normalizeVocabItem({ content: 'x' });
  assert.equal(out.reviewCount, 0);
  assert.equal(out.reviewIntervalHours, 0);
  assert.equal(out.nextReviewAt, null);
  assert.equal(out.lastReviewedAt, null);
});

// ---------------------------------------------------------------------------
// filterVocab / sortVocab (mirrors iOS VocabularyEntryPresentation)
// ---------------------------------------------------------------------------

const due1 = { word: 'banana', meaning: '香蕉', reviewCount: 1, nextReviewAt: new Date(NOW - HOUR_MS).toISOString(), difficultyTier: 'advanced', updatedAt: '2024-05-01T00:00:00Z' };
const due2 = { word: 'apple', meaning: '蘋果', reviewCount: 2, nextReviewAt: new Date(NOW - 2 * HOUR_MS).toISOString(), difficultyTier: 'core', updatedAt: '2024-05-10T00:00:00Z' };
const unl = { word: 'cherry', meaning: '櫻桃', reviewCount: 0, difficultyTier: 'intermediate', updatedAt: '2024-05-20T00:00:00Z' };
const rev = { word: 'date', meaning: '椰棗', reviewCount: 3, nextReviewAt: new Date(NOW + DAY_MS).toISOString(), difficultyTier: 'rare', updatedAt: '2024-05-05T00:00:00Z' };
const CORPUS = [due1, due2, unl, rev];

test('VOCAB_SORT_OPTIONS matches iOS KGVocabSortOption order', () => {
  assert.deepEqual([...VOCAB_SORT_OPTIONS], ['default', 'alphabetical', 'dateAdded', 'difficulty']);
});

test('filterVocab: empty states = all; query filters word OR meaning', () => {
  assert.equal(filterVocab(CORPUS, {}, NOW).length, 4);
  assert.deepEqual(filterVocab(CORPUS, { query: 'app' }, NOW).map((i) => i.word), ['apple']);
  // meaning match (Chinese)
  assert.deepEqual(filterVocab(CORPUS, { query: '櫻桃' }, NOW).map((i) => i.word), ['cherry']);
});

test('filterVocab: state set keeps only selected states (empty = all)', () => {
  const due = filterVocab(CORPUS, { states: new Set(['due']) }, NOW).map((i) => i.word).sort();
  assert.deepEqual(due, ['apple', 'banana']);
  assert.deepEqual(filterVocab(CORPUS, { states: ['unlearned'] }, NOW).map((i) => i.word), ['cherry']);
  assert.equal(filterVocab(CORPUS, { states: new Set() }, NOW).length, 4);
});

test('filterVocab: query + state compose (AND)', () => {
  const r = filterVocab(CORPUS, { query: 'a', states: new Set(['due']) }, NOW).map((i) => i.word).sort();
  assert.deepEqual(r, ['apple', 'banana']); // both due, both contain 'a'
});

test('sortVocab default: due before unlearned before reviewed, then nextReviewAt asc', () => {
  const order = sortVocab(CORPUS, 'default', NOW).map((i) => i.word);
  // due2 (next −2h) < due1 (next −1h) → apple, banana; then unlearned cherry; then reviewed date
  assert.deepEqual(order, ['apple', 'banana', 'cherry', 'date']);
});

test('sortVocab alphabetical: case-insensitive A→Z by word', () => {
  assert.deepEqual(sortVocab(CORPUS, 'alphabetical', NOW).map((i) => i.word),
    ['apple', 'banana', 'cherry', 'date']);
});

test('sortVocab dateAdded: updatedAt descending (proxy for creation)', () => {
  // updatedAt: cherry 05-20, apple 05-10, date 05-05, banana 05-01 → desc
  assert.deepEqual(sortVocab(CORPUS, 'dateAdded', NOW).map((i) => i.word),
    ['cherry', 'apple', 'date', 'banana']);
});

test('sortVocab difficulty: tier core<intermediate<advanced<rare, then word', () => {
  assert.deepEqual(sortVocab(CORPUS, 'difficulty', NOW).map((i) => i.word),
    ['apple', 'cherry', 'banana', 'date']); // core, intermediate, advanced, rare
});

test('sortVocab default: null nextReviewAt within same state group falls through to tier→word', () => {
  // Two unlearned cards (reviewCount 0 → nextReviewAt irrelevant/null): tie-break
  // is tier (core<advanced) then word.
  const a = { word: 'zebra', reviewCount: 0, difficultyTier: 'core' };
  const b = { word: 'ant', reviewCount: 0, difficultyTier: 'advanced' };
  assert.deepEqual(sortVocab([b, a], 'default', NOW).map((i) => i.word), ['zebra', 'ant']);
});

test('sortVocab dateAdded: missing updatedAt sinks to the end (|| 0 fallback)', () => {
  const withDate = { word: 'a', updatedAt: '2024-05-10T00:00:00Z' };
  const noDate = { word: 'b', updatedAt: null };
  assert.deepEqual(sortVocab([noDate, withDate], 'dateAdded', NOW).map((i) => i.word), ['a', 'b']);
});

test('filterVocab returns a new array and preserves input order', () => {
  const out = filterVocab(CORPUS, {}, NOW);
  assert.notEqual(out, CORPUS);
  assert.deepEqual(out.map((i) => i.word), CORPUS.map((i) => i.word));
});

test('sortVocab does not mutate input; unknown option → default', () => {
  const copy = CORPUS.slice();
  const out = sortVocab(CORPUS, 'nonsense', NOW);
  assert.deepEqual(CORPUS, copy);            // untouched
  assert.deepEqual(out.map((i) => i.word), ['apple', 'banana', 'cherry', 'date']);
});

// ---------------------------------------------------------------------------
// vocabEmptyState (mirrors iOS KGVocabEmptyState)
// ---------------------------------------------------------------------------

test('vocabEmptyState prioritizes whole-empty over search and filters', () => {
  assert.deepEqual(
    vocabEmptyState({ hasNoEntries: true, searchText: 'cat', filters: ['due'] }),
    {
      kind: 'empty',
      titleKey: 'emptyCollectedTitle',
      descriptionKey: 'emptyCollectedSubtitle',
      systemImage: 'books.vertical',
    },
  );
});

test('vocabEmptyState returns search copy before filter copy', () => {
  assert.deepEqual(
    vocabEmptyState({ hasNoEntries: false, searchText: 'cat', filters: ['due'] }),
    {
      kind: 'search',
      titleKey: 'emptySearchTitle',
      descriptionKey: 'emptySearchSubtitle',
      systemImage: 'magnifyingglass',
    },
  );
});

test('vocabEmptyState uses single-filter iOS system-image branches', () => {
  assert.equal(vocabEmptyState({ filters: ['unlearned'] }).systemImage, 'sparkles');
  assert.equal(vocabEmptyState({ filters: ['due'] }).systemImage, 'checkmark.seal');
  assert.equal(vocabEmptyState({ filters: ['reviewed'] }).systemImage, 'leaf');
  assert.equal(
    vocabEmptyState({ filters: ['due', 'reviewed'] }).systemImage,
    'line.3.horizontal.decrease.circle',
  );
  assert.deepEqual(
    vocabEmptyState({ filters: [] }),
    {
      kind: 'default',
      titleKey: 'emptyCollectedTitle',
      descriptionKey: 'emptySyncedSubtitle',
      systemImage: 'line.3.horizontal.decrease.circle',
    },
  );
});

// ---------------------------------------------------------------------------
// vocabPlainTextExport (mirrors iOS CardDocument.plainTextExport)
// ---------------------------------------------------------------------------

test('vocabPlainTextExport orders word, example, meaning, collocations, source like iOS', () => {
  const text = vocabPlainTextExport({
    word: 'lascivious',
    pos: 'adj.',
    examples: [{ sentence: 'He cast a lascivious glance.' }],
    meaning: '好色的；淫蕩的',
    note: '帶有明顯性意味的。\n\n多用於描述眼神。',
    collocations: [{ word: 'lascivious glance' }, { word: 'lascivious smile' }],
    source: { type: 'book', title: 'Moby Dick', chapter: 'Chapter 1' },
  });
  assert.equal(text, [
    'lascivious (adj.)',
    'He cast a lascivious glance.',
    '好色的；淫蕩的',
    '帶有明顯性意味的。',
    '多用於描述眼神。',
    'lascivious glance, lascivious smile',
    '— Moby Dick · Chapter 1',
  ].join('\n\n'));
});

test('vocabPlainTextExport trims blanks and omits absent sections', () => {
  assert.equal(vocabPlainTextExport({
    word: '  daft  ',
    pos: '',
    meaning: '愚蠢的',
    note: '   ',
    examples: [],
    collocations: [],
    source: null,
  }), 'daft\n\n愚蠢的');
});

test('vocabPlainTextExport keeps single newlines inside iOS meaning paragraphs', () => {
  assert.equal(vocabPlainTextExport({
    word: 'cadence',
    meaning: '節奏',
    note: '第一行解釋\n第二行仍是同一段\n\n第三行才是新段落',
  }), 'cadence\n\n節奏\n\n第一行解釋\n第二行仍是同一段\n\n第三行才是新段落');
});

// ---------------------------------------------------------------------------
// Options presentation (mirrors iOS SettingsPresenter state shaping)
// ---------------------------------------------------------------------------

test('optionsTranslationPresentation disables language controls while logged out', () => {
  assert.deepEqual(
    optionsTranslationPresentation({ isLoggedIn: false }),
    {
      translation: { source_lang: 'en', target_lang: 'zh-Hant' },
      disabled: true,
      hintKey: 'translateLangLoginHint',
    },
  );
});

test('optionsTranslationPresentation returns server translation when logged in', () => {
  assert.deepEqual(
    optionsTranslationPresentation({
      isLoggedIn: true,
      translation: { source_lang: 'ja', target_lang: 'en' },
      fallbackTranslation: { source_lang: 'en', target_lang: 'zh-Hant' },
    }),
    {
      translation: { source_lang: 'ja', target_lang: 'en' },
      disabled: false,
      hintKey: null,
    },
  );
});

test('optionsTranslationPresentation keeps fallback and maps load errors to hints', () => {
  assert.deepEqual(
    optionsTranslationPresentation({
      isLoggedIn: true,
      fallbackTranslation: { source_lang: 'ko', target_lang: 'ja' },
      errorStatus: 500,
    }),
    {
      translation: { source_lang: 'ko', target_lang: 'ja' },
      disabled: true,
      hintKey: 'translateLangLoadError',
    },
  );
  assert.equal(
    optionsTranslationPresentation({ isLoggedIn: true, errorStatus: 401 }).hintKey,
    'translateLangLoginHint',
  );
  assert.deepEqual(
    optionsTranslationPresentation({
      isLoggedIn: true,
      fallbackTranslation: { source_lang: 'fr', target_lang: 'zh-Hant' },
      errorStatus: 0,
    }),
    {
      translation: { source_lang: 'fr', target_lang: 'zh-Hant' },
      disabled: true,
      hintKey: 'translateLangLoadError',
    },
  );
});

test('optionsProPresentation shapes active/free/unknown entitlement rows', () => {
  assert.deepEqual(optionsProPresentation({ is_active: true, plan_name: 'Monthly' }), {
    hidden: false,
    badge: 'PRO',
    labelKey: 'proActive',
    planName: 'Monthly',
    isFree: false,
  });
  assert.deepEqual(optionsProPresentation({ is_active: false }), {
    hidden: false,
    badge: null,
    labelKey: 'proFree',
    planName: '',
    isFree: true,
  });
  assert.deepEqual(optionsProPresentation(null), {
    hidden: true,
    badge: null,
    labelKey: null,
    planName: '',
    isFree: false,
  });
});

// ---------------------------------------------------------------------------
// normalizeVocabItem
// ---------------------------------------------------------------------------

test('normalizeVocabItem maps word from content, falling back to word', () => {
  assert.equal(normalizeVocabItem({ content: 'apple' }).word, 'apple');
  assert.equal(normalizeVocabItem({ word: 'banana' }).word, 'banana');
  // content wins when both present (legacy primary key)
  assert.equal(normalizeVocabItem({ content: 'apple', word: 'banana' }).word, 'apple');
  assert.equal(normalizeVocabItem({}).word, '');
});

test('normalizeVocabItem maps meaning from meaning, falling back to translation', () => {
  assert.equal(normalizeVocabItem({ meaning: 'M' }).meaning, 'M');
  assert.equal(normalizeVocabItem({ translation: 'T' }).meaning, 'T');
  assert.equal(normalizeVocabItem({ meaning: 'M', translation: 'T' }).meaning, 'M');
  assert.equal(normalizeVocabItem({}).meaning, '');
});

test('normalizeVocabItem maps context from context_sentence, falling back to context', () => {
  assert.equal(normalizeVocabItem({ context_sentence: 'S' }).context, 'S');
  assert.equal(normalizeVocabItem({ context: 'C' }).context, 'C');
  assert.equal(normalizeVocabItem({ context_sentence: 'S', context: 'C' }).context, 'S');
  assert.equal(normalizeVocabItem({}).context, '');
});

test('normalizeVocabItem defaults pos / note to empty string', () => {
  assert.equal(normalizeVocabItem({}).pos, '');
  assert.equal(normalizeVocabItem({}).note, '');
  assert.equal(normalizeVocabItem({ pos: 'n.', note: 'hi' }).pos, 'n.');
  assert.equal(normalizeVocabItem({ pos: 'n.', note: 'hi' }).note, 'hi');
});

test('normalizeVocabItem coerces examples / collocations to arrays', () => {
  const ex = [{ sentence: 'x' }];
  const co = ['big'];
  assert.deepEqual(normalizeVocabItem({ examples: ex, collocations: co }).examples, ex);
  assert.deepEqual(normalizeVocabItem({ examples: ex, collocations: co }).collocations, co);
  // non-array / missing → []
  assert.deepEqual(normalizeVocabItem({}).examples, []);
  assert.deepEqual(normalizeVocabItem({ examples: 'oops' }).examples, []);
  assert.deepEqual(normalizeVocabItem({ collocations: null }).collocations, []);
});

test('normalizeVocabItem passes source through, defaulting to null', () => {
  const src = { type: 'web', url: 'https://x.com', title: 'X' };
  assert.equal(normalizeVocabItem({ source: src }).source, src);
  assert.equal(normalizeVocabItem({}).source, null);
});

test('normalizeVocabItem tolerates nullish / non-object input', () => {
  assert.deepEqual(normalizeVocabItem(null), {
    word: '', meaning: '', pos: '', note: '', context: '',
    examples: [], collocations: [], source: null,
    reviewCount: 0, reviewIntervalHours: 0, nextReviewAt: null, lastReviewedAt: null,
    difficultyTier: null, updatedAt: null,
    linksByKind: {}, inflections: [], cardId: '',
  });
  assert.deepEqual(normalizeVocabItem(undefined).word, '');
  assert.deepEqual(normalizeVocabItem('oops').word, '');
});

// ---------------------------------------------------------------------------
// classifyError
// ---------------------------------------------------------------------------

test('classifyError maps auth_expired / 401 to the login flow', () => {
  assert.equal(classifyError({ code: 'auth_expired' }).action, 'login');
  assert.equal(classifyError({ status: 401 }).action, 'login');
  assert.equal(classifyError({ status: 401 }).icon, 'error-login');
});

test('classifyError maps quota_exceeded / 429 to the settings flow', () => {
  // Backend raises QuotaExceededError with HTTP 429 (not 403).
  assert.equal(classifyError({ code: 'quota_exceeded' }).action, 'settings');
  assert.equal(classifyError({ status: 429 }).action, 'settings');
  // A genuine 403 (ForbiddenError, e.g. another user's notebook) is NOT a quota
  // hit and must not surface the quota UI.
  assert.notEqual(classifyError({ status: 403 }).action, 'settings');
});

test('classifyError maps network_error / status 0 to a reloadable state', () => {
  const r = classifyError({ code: 'network_error' });
  assert.equal(r.action, 'reload');
  assert.equal(r.icon, 'error-network');
  assert.equal(classifyError({ status: 0 }).icon, 'error-network');
});

test('classifyError treats 5xx and server-side codes as "server busy"', () => {
  assert.equal(classifyError({ status: 500 }).title, '伺服器忙碌中');
  assert.equal(classifyError({ status: 503 }).title, '伺服器忙碌中');
  assert.equal(classifyError({ code: 'server_error' }).title, '伺服器忙碌中');
  assert.equal(classifyError({ code: 'bad_response' }).title, '伺服器忙碌中');
});

test('classifyError falls back to a generic error, surfacing the message', () => {
  const r = classifyError({ message: 'something odd' });
  assert.equal(r.action, 'reload');
  assert.equal(r.title, '載入失敗');
  assert.equal(r.subtitle, 'something odd');
});

test('classifyError tolerates an empty / missing response object', () => {
  const r = classifyError({});
  assert.equal(r.action, 'reload');
  assert.equal(r.subtitle, '');
});

// ---------------------------------------------------------------------------
// routeMessage
// ---------------------------------------------------------------------------

test('routeMessage maps translate to KGApi.translate(word, context)', () => {
  assert.deepEqual(
    routeMessage({ type: 'translate', word: 'cat', context: 'ctx' }),
    { kind: 'translate', args: ['cat', 'ctx'] },
  );
});

test('routeMessage maps translatePhrase keyed on `text`', () => {
  assert.deepEqual(
    routeMessage({ type: 'translatePhrase', text: 'a phrase', context: 'ctx' }),
    { kind: 'translatePhrase', args: ['a phrase', 'ctx'] },
  );
});

test('routeMessage maps explain / addVocab / listVocab / lookupWord', () => {
  assert.deepEqual(
    routeMessage({ type: 'explain', word: 'w', context: 'c' }),
    { kind: 'explain', args: ['w', 'c'] },
  );
  assert.deepEqual(
    routeMessage({ type: 'addVocab', entries: [{ word: 'w' }], notebookId: 'nb-reading' }),
    { kind: 'addVocab', args: [[{ word: 'w' }], 'nb-reading'] },
  );
  assert.deepEqual(
    routeMessage({ type: 'listVocab', since: '2024-01-01', notebookId: 'nb-reading' }),
    { kind: 'listVocab', args: ['2024-01-01', undefined, 'nb-reading'] },
  );
  assert.deepEqual(
    routeMessage({ type: 'lookupWord', word: 'w' }),
    { kind: 'lookupWord', args: ['w'] },
  );
});

test('routeMessage does NOT route internal auth_token (token writes are onMessageExternal-only)', () => {
  // Token writes are gated by isTrustedExternalOrigin in onMessageExternal;
  // there is no internal auth_token sender, so the internal route is removed.
  assert.throws(
    () => routeMessage({ type: 'auth_token', token: 'abc' }),
    /unknown message type: auth_token/,
  );
});

test('routeMessage maps user config / entitlements kinds', () => {
  assert.deepEqual(routeMessage({ type: 'getUserConfig' }), {
    kind: 'getUserConfig',
    args: [],
  });
  assert.deepEqual(routeMessage({ type: 'getEntitlements' }), {
    kind: 'getEntitlements',
    args: [],
  });
  // updateUserConfig is a generic user-config patch route: it forwards the whole
  // `config` object (translation / vocab_ui / …) positionally so any group can be
  // PUT without adding a per-group message type.
  const config = { translation: { source_lang: 'en', target_lang: 'zh-Hant' } };
  assert.deepEqual(routeMessage({ type: 'updateUserConfig', config }), {
    kind: 'updateUserConfig',
    args: [config],
  });
  const vuConfig = { vocab_ui: { active_notebook_id: 'nb-7', updated_at: 42 } };
  assert.deepEqual(routeMessage({ type: 'updateUserConfig', config: vuConfig }), {
    kind: 'updateUserConfig',
    args: [vuConfig],
  });
});

// ---------------------------------------------------------------------------
// resolveActiveNotebook — two-layer LWW (chrome.storage.local vs backend vocab_ui)
// ---------------------------------------------------------------------------

test('resolveActiveNotebook picks the side with the newer updatedAt', () => {
  const local = { id: 'a', updatedAt: 100 };
  const remote = { id: 'b', updatedAt: 200 };
  assert.deepEqual(resolveActiveNotebook(local, remote), { id: 'b', updatedAt: 200 });
  assert.deepEqual(
    resolveActiveNotebook({ id: 'a', updatedAt: 300 }, { id: 'b', updatedAt: 200 }),
    { id: 'a', updatedAt: 300 },
  );
});

test('resolveActiveNotebook takes remote when local has no timestamp', () => {
  assert.deepEqual(
    resolveActiveNotebook({ id: 'a', updatedAt: null }, { id: 'b', updatedAt: 1 }),
    { id: 'b', updatedAt: 1 },
  );
});

test('resolveActiveNotebook keeps local when remote has no timestamp', () => {
  assert.deepEqual(
    resolveActiveNotebook({ id: 'a', updatedAt: 1 }, { id: 'b', updatedAt: null }),
    { id: 'a', updatedAt: 1 },
  );
});

test('resolveActiveNotebook keeps local when both lack a timestamp', () => {
  // Mirrors iOS ActiveNotebookLWW: double-nil → local (avoids clobbering a never-set
  // local cursor with a stale-but-also-never-set remote default).
  assert.deepEqual(
    resolveActiveNotebook({ id: 'a', updatedAt: null }, { id: 'b', updatedAt: null }),
    { id: 'a', updatedAt: null },
  );
});

test('resolveActiveNotebook keeps local on a timestamp tie', () => {
  // iOS resolves `c > l ? cloud : local`, so an exact tie keeps local.
  assert.deepEqual(
    resolveActiveNotebook({ id: 'a', updatedAt: 5 }, { id: 'b', updatedAt: 5 }),
    { id: 'a', updatedAt: 5 },
  );
});

// ---------------------------------------------------------------------------
// buildVocabUiConfigPatch — backend vocab_ui wire shape (snake_case)
// ---------------------------------------------------------------------------

test('buildVocabUiConfigPatch shapes the snake_case vocab_ui group', () => {
  assert.deepEqual(buildVocabUiConfigPatch('nb-7', 42), {
    vocab_ui: { active_notebook_id: 'nb-7', updated_at: 42 },
  });
});

test('buildVocabUiConfigPatch forwards a null timestamp verbatim', () => {
  assert.deepEqual(buildVocabUiConfigPatch('default', null), {
    vocab_ui: { active_notebook_id: 'default', updated_at: null },
  });
});

test('routeMessage maps notebook CRUD kinds', () => {
  assert.deepEqual(routeMessage({ type: 'listNotebooks', since: '2024-01-01' }), {
    kind: 'listNotebooks',
    args: ['2024-01-01'],
  });
  assert.deepEqual(routeMessage({ type: 'createNotebook', notebook: { name: '閱讀' } }), {
    kind: 'createNotebook',
    args: [{ name: '閱讀' }],
  });
  assert.deepEqual(routeMessage({ type: 'updateNotebook', notebookId: 'nb1', patch: { name: '新名' } }), {
    kind: 'updateNotebook',
    args: ['nb1', { name: '新名' }],
  });
  assert.deepEqual(routeMessage({ type: 'deleteNotebook', notebookId: 'nb1' }), {
    kind: 'deleteNotebook',
    args: ['nb1'],
  });
  assert.deepEqual(routeMessage({ type: 'retryOutbox' }), {
    kind: 'retryOutbox',
    args: [],
  });
});

test('routeMessage maps get_auth_status / logout to argument-free ops', () => {
  assert.deepEqual(routeMessage({ type: 'get_auth_status' }), {
    kind: 'getAuthStatus',
    args: [],
  });
  assert.deepEqual(routeMessage({ type: 'logout' }), { kind: 'logout', args: [] });
});

test('routeMessage throws on an unknown / missing message type', () => {
  assert.throws(() => routeMessage({ type: 'frobnicate' }), /unknown message type: frobnicate/);
  assert.throws(() => routeMessage({}), /unknown message type: undefined/);
  // `null` / `undefined` messages are tolerated without a TypeError — they
  // fall through to the default branch (mirrors `msg && msg.type`).
  assert.throws(() => routeMessage(null), /unknown message type: null/);
  assert.throws(() => routeMessage(undefined), /unknown message type: undefined/);
});

test('ROUTABLE_MESSAGE_TYPES — every listed type routes without throwing', () => {
  // A representative well-formed message per type; ensures the exported type
  // list and the routeMessage switch never drift apart.
  const sample = {
    translate: { type: 'translate', word: 'w', context: 'c' },
    translatePhrase: { type: 'translatePhrase', text: 't', context: 'c' },
    explain: { type: 'explain', word: 'w', context: 'c' },
    addVocab: { type: 'addVocab', entries: [] },
    listVocab: { type: 'listVocab', since: '' },
    listNotebooks: { type: 'listNotebooks', since: '' },
    createNotebook: { type: 'createNotebook', notebook: { name: 'n' } },
    updateNotebook: { type: 'updateNotebook', notebookId: 'n', patch: { name: 'm' } },
    deleteNotebook: { type: 'deleteNotebook', notebookId: 'n' },
    retryOutbox: { type: 'retryOutbox' },
    lookupWord: { type: 'lookupWord', word: 'w' },
    getUserConfig: { type: 'getUserConfig' },
    updateUserConfig: { type: 'updateUserConfig', config: {} },
    getEntitlements: { type: 'getEntitlements' },
    get_auth_status: { type: 'get_auth_status' },
    logout: { type: 'logout' },
  };
  for (const t of ROUTABLE_MESSAGE_TYPES) {
    assert.ok(sample[t], `missing sample message for routable type "${t}"`);
    assert.doesNotThrow(() => routeMessage(sample[t]), `type "${t}" should route`);
  }
});

// ---------------------------------------------------------------------------
// isVocabMutatingKind / VOCAB_DIRTY_KEY — cross-context refresh contract
// ---------------------------------------------------------------------------

test('VOCAB_DIRTY_KEY is the stable storage key the side panel watches', () => {
  assert.equal(VOCAB_DIRTY_KEY, 'vocab_dirty');
});

test('isVocabMutatingKind is true only for kinds that change the vocab list', () => {
  // `addVocab` mutates the list → background bumps VOCAB_DIRTY_KEY so an open
  // side panel refreshes. Read-only / non-vocab kinds must NOT trigger a refresh.
  assert.equal(isVocabMutatingKind('addVocab'), true);
  assert.equal(isVocabMutatingKind('listVocab'), false);
  assert.equal(isVocabMutatingKind('lookupWord'), false);
  assert.equal(isVocabMutatingKind('translate'), false);
  assert.equal(isVocabMutatingKind('getAuthStatus'), false);
  assert.equal(isVocabMutatingKind('logout'), false);
});

test('isVocabMutatingKind tolerates non-string / unknown input', () => {
  assert.equal(isVocabMutatingKind(undefined), false);
  assert.equal(isVocabMutatingKind(null), false);
  assert.equal(isVocabMutatingKind(''), false);
  assert.equal(isVocabMutatingKind('frobnicate'), false);
});

// ---------------------------------------------------------------------------
// isTrustedExternalOrigin
// ---------------------------------------------------------------------------

test('isTrustedExternalOrigin accepts the KG https origin', () => {
  assert.equal(
    isTrustedExternalOrigin(`${PUBLIC_WEB_ORIGIN}${LOGIN_PATH}`),
    true,
  );
  assert.equal(isTrustedExternalOrigin(`${PUBLIC_WEB_ORIGIN}/`), true);
});

test('isTrustedExternalOrigin rejects look-alike and insecure origins', () => {
  assert.equal(isTrustedExternalOrigin('http://wordnexus.lol/'), false);
  assert.equal(
    isTrustedExternalOrigin('https://evil.com/wordnexus.lol'),
    false,
  );
  assert.equal(isTrustedExternalOrigin(''), false);
  assert.equal(isTrustedExternalOrigin(undefined), false);
  assert.equal(isTrustedExternalOrigin(null), false);
  assert.equal(isTrustedExternalOrigin('not a url'), false);
});

test('isTrustedExternalOrigin rejects subdomain phishing look-alikes', () => {
  // exact-host match — these must NOT pass.
  assert.equal(
    isTrustedExternalOrigin('https://wordnexus.lol.evil.com/'),
    false,
  );
  assert.equal(
    isTrustedExternalOrigin('https://evil.wordnexus.lol/'),
    false,
  );
});


// ---------------------------------------------------------------------------
// safeUrl
// ---------------------------------------------------------------------------

test('safeUrl passes http and https URLs through unchanged', () => {
  assert.equal(safeUrl('http://example.com/path'), 'http://example.com/path');
  assert.equal(safeUrl(`${PUBLIC_WEB_ORIGIN}/x?y=1#z`), `${PUBLIC_WEB_ORIGIN}/x?y=1#z`);
});

test('safeUrl passes chrome-extension:// URLs through unchanged', () => {
  const url = 'chrome-extension://abcdef/options/options.html';
  assert.equal(safeUrl(url), url);
});

test('safeUrl rejects javascript: scheme', () => {
  assert.equal(safeUrl('javascript:alert(1)'), '#');
  assert.equal(safeUrl('JavaScript:alert(1)'), '#');
  // Leading whitespace + tab that browsers ignore — must still be rejected.
  assert.equal(safeUrl(' \tjavascript:alert(1)'), '#');
  // Leading NUL / control chars.
  assert.equal(safeUrl('\x00javascript:alert(1)'), '#');
});

test('safeUrl rejects other dangerous schemes', () => {
  assert.equal(safeUrl('data:text/html,<script>alert(1)</script>'), '#');
  assert.equal(safeUrl('vbscript:msgbox(1)'), '#');
  assert.equal(safeUrl('file:///etc/passwd'), '#');
  assert.equal(safeUrl('blob:https://example.com/abc'), '#');
});

test('safeUrl handles nullish / non-string / empty input', () => {
  assert.equal(safeUrl(null), '#');
  assert.equal(safeUrl(undefined), '#');
  assert.equal(safeUrl(''), '#');
  assert.equal(safeUrl('   '), '#');
  assert.equal(safeUrl(42), '#');
  assert.equal(safeUrl({}), '#');
});

test('safeUrl respects custom fallback', () => {
  assert.equal(safeUrl('javascript:alert(1)', 'about:blank'), 'about:blank');
  assert.equal(safeUrl(null, ''), '');
});

test('safeUrl treats scheme-relative URLs as http(s) via base', () => {
  // `//evil.example/x` resolves against the https base → normalized to https — safe.
  // This is acceptable: the destination is a regular network URL, not a script.
  assert.equal(safeUrl('//evil.example/x'), 'https://evil.example/x');
});

test('safeUrl normalizes (percent-encodes) the returned URL — no raw quotes survive', () => {
  // Attribute-breakout XSS guard: a captured source.url with a raw `"` must be
  // percent-encoded in the returned href, not passed through verbatim.
  assert.equal(
    safeUrl('https://x.com/"onmouseover=alert(1)'),
    'https://x.com/%22onmouseover=alert(1)',
  );
  // Clean URLs are unaffected (normalize to themselves).
  assert.equal(safeUrl(`${PUBLIC_WEB_ORIGIN}/a/b`), `${PUBLIC_WEB_ORIGIN}/a/b`);
});

// ---------------------------------------------------------------------------
// escapeHtml
// ---------------------------------------------------------------------------

test('escapeHtml encodes the markup-significant trio &<>', () => {
  // Matches the prior detached-<span> + textContent → innerHTML round-trip:
  // browsers only encode these three characters in that round-trip, so we do
  // the same to keep rendered output byte-identical to the previous helper.
  assert.equal(escapeHtml('Tom & Jerry'), 'Tom &amp; Jerry');
  assert.equal(escapeHtml('<script>x</script>'), '&lt;script&gt;x&lt;/script&gt;');
  assert.equal(escapeHtml('a < b && b > c'), 'a &lt; b &amp;&amp; b &gt; c');
});

test('escapeHtml encodes quotes so attribute interpolation cannot break out', () => {
  // Security: call sites interpolate escaped values into `"`-wrapped attributes
  // (e.g. `href="${esc(url)}"`). A raw `"` would break out of the attribute and
  // inject markup — so we encode both `"` and `'`.
  assert.equal(escapeHtml(`he said "hi"`), 'he said &quot;hi&quot;');
  assert.equal(escapeHtml("it's fine"), 'it&#39;s fine');
  assert.equal(
    escapeHtml('"onmouseover="alert(1)'),
    '&quot;onmouseover=&quot;alert(1)',
  );
});

test('escapeHtml escapes & first so subsequent entities are not double-encoded', () => {
  // Naively replacing `<` before `&` would turn `&lt;` into `&amp;lt;` on a
  // pre-encoded input. The replacement order in pure.js prevents that.
  assert.equal(escapeHtml('&amp;'), '&amp;amp;'); // pre-encoded input round-trips faithfully
  assert.equal(escapeHtml('&<>'), '&amp;&lt;&gt;');
});

test('escapeHtml coerces null/undefined/numbers to a safe string', () => {
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
  assert.equal(escapeHtml(42), '42');
  assert.equal(escapeHtml(0), '0');
});

// ---------------------------------------------------------------------------
// normalizeVocabItem — knowledge-graph fields (Phase 1)
// ---------------------------------------------------------------------------

test('normalizeVocabItem preserves linksByKind / inflections / cardId', () => {
  const raw = {
    id: 'card-123',
    content: 'lascivious',
    meaning: '色情的',
    inflections: ['lasciviously', 'lasciviousness'],
    linksByKind: {
      contrasts_with: [{ id: 'l1', cardId: 'card-9', word: 'chaste', kind: 'contrasts_with', label: '對比', reason: '相反' }],
      shares_usage: [{ id: 'l2', cardId: 'card-8', word: 'lusciously', kind: 'shares_usage', label: '相關', reason: '近似' }],
    },
  };
  const n = normalizeVocabItem(raw);
  assert.equal(n.cardId, 'card-123');
  assert.deepEqual(n.inflections, ['lasciviously', 'lasciviousness']);
  assert.equal(n.linksByKind.contrasts_with[0].word, 'chaste');
  assert.equal(n.linksByKind.shares_usage[0].reason, '近似');
});

test('normalizeVocabItem guards malformed link/inflection payloads', () => {
  // Array / string linksByKind, non-array inflections → safe defaults, never throws.
  assert.deepEqual(normalizeVocabItem({ linksByKind: [] }).linksByKind, {});
  assert.deepEqual(normalizeVocabItem({ linksByKind: 'x' }).linksByKind, {});
  assert.deepEqual(normalizeVocabItem({ inflections: 'x' }).inflections, []);
  assert.deepEqual(normalizeVocabItem({}).linksByKind, {});
  assert.deepEqual(normalizeVocabItem({}).inflections, []);
  assert.equal(normalizeVocabItem({}).cardId, '');
  assert.equal(normalizeVocabItem({ cardId: 'c' }).cardId, 'c'); // cardId alias when no id
});

// ---------------------------------------------------------------------------
// markWordInExample — port of iOS VocabularyEntry.markWordInContext
// ---------------------------------------------------------------------------

test('markWordInExample wraps the first verbatim occurrence (case-insensitive, original case kept)', () => {
  assert.equal(
    markWordInExample('She was Lascivious and proud.', 'lascivious'),
    'She was **Lascivious** and proud.',
  );
  assert.equal(
    markWordInExample('a lascivious lascivious cat', 'lascivious'),
    'a **lascivious** lascivious cat', // first occurrence only
  );
});

test('markWordInExample falls back to a stem match when the word is inflected', () => {
  // The stored form ("lasciviously") is NOT a verbatim substring of the example
  // (which has the shorter "lascivious"), so step 1 misses and the 6-char stem
  // "lasciv" matches via the boundary-anchored fallback. Mirrors iOS behaviour
  // where a longer lemma falls back to its stem.
  assert.equal(
    markWordInExample('She acted lascivious today.', 'lasciviously'),
    'She acted **lascivious** today.',
  );
});

test('markWordInExample step 1 matches a verbatim substring (no word boundary, mirrors iOS)', () => {
  // iOS step 1 has no word boundary: a lemma that is a substring of the inflected
  // form is wrapped in place (e.g. "forestall" inside "forestalling").
  assert.equal(
    markWordInExample('He was forestalling the move.', 'forestall'),
    'He was **forestall**ing the move.',
  );
});

test('markWordInExample returns the text unchanged when nothing matches / inputs empty', () => {
  assert.equal(markWordInExample('totally unrelated', 'lascivious'), 'totally unrelated');
  assert.equal(markWordInExample('', 'x'), '');
  assert.equal(markWordInExample('text', ''), 'text');
  assert.equal(markWordInExample('text', '   '), 'text');
});

test('markWordInExample treats the word as a literal, not a regex pattern', () => {
  assert.equal(markWordInExample('the a.b token', 'a.b'), 'the **a.b** token');
  assert.equal(markWordInExample('the axb token', 'a.b'), 'the axb token'); // '.' is literal, not wildcard
});

// ---------------------------------------------------------------------------
// parseInlineMarks — port of iOS CardMarkdownInlineParser (mark cases)
// ---------------------------------------------------------------------------

test('parseInlineMarks splits ** and == spans into typed segments', () => {
  assert.deepEqual(parseInlineMarks('a **b** c'), [
    { type: 'text', value: 'a ' },
    { type: 'mark', value: 'b' },
    { type: 'text', value: ' c' },
  ]);
  assert.deepEqual(parseInlineMarks('==hi=='), [{ type: 'mark', value: 'hi' }]);
});

test('parseInlineMarks treats unclosed markers as literal text', () => {
  assert.deepEqual(parseInlineMarks('a **b c'), [{ type: 'text', value: 'a **b c' }]);
});

test('parseInlineMarks drops empty spans and handles plain/empty text', () => {
  assert.deepEqual(parseInlineMarks('****'), []);
  assert.deepEqual(parseInlineMarks('plain'), [{ type: 'text', value: 'plain' }]);
  assert.deepEqual(parseInlineMarks(''), []);
});

// ---------------------------------------------------------------------------
// pickPreferredVoice — choose the most natural TTS voice for a target lang.
// Web Speech defaults to whatever the OS hands back for `lang`, which on
// desktop is often a robotic compact system voice. This picks the best
// available so the speaker button sounds like a person, mirroring the iOS
// AVSpeechSynthesisVoice quality. Shared by app.js + content.js (inlined).
// ---------------------------------------------------------------------------

// Minimal SpeechSynthesisVoice stand-ins (only the fields the picker reads).
const voice = (name, lang, opts = {}) => ({
  name, lang, localService: opts.localService ?? true, default: opts.default ?? false,
});

test('pickPreferredVoice returns null for empty / non-array input', () => {
  assert.equal(pickPreferredVoice([]), null);
  assert.equal(pickPreferredVoice(null), null);
  assert.equal(pickPreferredVoice(undefined), null);
});

test('pickPreferredVoice prefers a Google natural voice over the default system one', () => {
  const voices = [
    voice('Fred', 'en-US', { default: true }),         // robotic system default
    voice('Samantha', 'en-US'),
    voice('Google US English', 'en-US', { localService: false }),
  ];
  assert.equal(pickPreferredVoice(voices, 'en-US').name, 'Google US English');
});

test('pickPreferredVoice favours an exact lang match over a same-base regional one', () => {
  const voices = [
    voice('Daniel', 'en-GB'),
    voice('Samantha', 'en-US'),
  ];
  assert.equal(pickPreferredVoice(voices, 'en-US').name, 'Samantha');
});

test('pickPreferredVoice falls back to a same-base voice when no exact match exists', () => {
  const voices = [voice('Daniel', 'en-GB'), voice('Karen', 'en-AU')];
  // en-* are all acceptable for English; first same-base wins on a score tie.
  assert.equal(pickPreferredVoice(voices, 'en-US').name, 'Daniel');
});

test('pickPreferredVoice returns null rather than read English in a foreign voice', () => {
  const voices = [voice('Mei-Jia', 'zh-TW'), voice('Kyoko', 'ja-JP')];
  assert.equal(pickPreferredVoice(voices, 'en-US'), null);
});

test('pickPreferredVoice ranks explicit natural/neural names above plain system voices', () => {
  const voices = [
    voice('Samantha', 'en-US'),
    voice('Ava (Enhanced)', 'en-US', { localService: false }),
  ];
  assert.equal(pickPreferredVoice(voices, 'en-US').name, 'Ava (Enhanced)');
});
