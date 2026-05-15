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

const {
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
  VALID_THEMES,
  DEFAULT_THEME,
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

// ---------------------------------------------------------------------------
// classifyError
// ---------------------------------------------------------------------------

test('classifyError maps auth_expired / 401 to the login flow', () => {
  assert.equal(classifyError({ code: 'auth_expired' }).action, 'login');
  assert.equal(classifyError({ status: 401 }).action, 'login');
  assert.equal(classifyError({ status: 401 }).icon, '🔒');
});

test('classifyError maps quota_exceeded / 403 to the settings flow', () => {
  assert.equal(classifyError({ code: 'quota_exceeded' }).action, 'settings');
  assert.equal(classifyError({ status: 403 }).action, 'settings');
});

test('classifyError maps network_error / status 0 to a reloadable state', () => {
  const r = classifyError({ code: 'network_error' });
  assert.equal(r.action, 'reload');
  assert.equal(r.icon, '📡');
  assert.equal(classifyError({ status: 0 }).icon, '📡');
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
// isSelectable
// ---------------------------------------------------------------------------

test('isSelectable accepts text within the 1..200 char bounds', () => {
  assert.equal(isSelectable('a'), true);
  assert.equal(isSelectable('hello'), true);
  assert.equal(isSelectable('x'.repeat(200)), true);
});

test('isSelectable rejects empty, whitespace-only and over-long text', () => {
  assert.equal(isSelectable(''), false);
  assert.equal(isSelectable('   '), false);
  assert.equal(isSelectable('x'.repeat(201)), false);
});

test('isSelectable rejects non-string input', () => {
  assert.equal(isSelectable(null), false);
  assert.equal(isSelectable(undefined), false);
  assert.equal(isSelectable(123), false);
});

// ---------------------------------------------------------------------------
// isPhrase
// ---------------------------------------------------------------------------

test('isPhrase is true only beyond 50 characters', () => {
  assert.equal(isPhrase('short word'), false);
  assert.equal(isPhrase('x'.repeat(50)), false);
  assert.equal(isPhrase('x'.repeat(51)), true);
});

test('isPhrase rejects non-string input', () => {
  assert.equal(isPhrase(null), false);
  assert.equal(isPhrase(undefined), false);
});

// ---------------------------------------------------------------------------
// extractSentence
// ---------------------------------------------------------------------------

test('extractSentence returns the sentence around the caret', () => {
  const text = 'Hello world. Second sentence here. Third.';
  // offset 20 falls inside "Second sentence here."
  assert.equal(extractSentence(text, 20), 'Second sentence here');
});

test('extractSentence handles the first sentence (caret near start)', () => {
  assert.equal(extractSentence('First. Second.', 2), 'First');
});

test('extractSentence respects CJK terminal punctuation', () => {
  const text = '第一句。第二句！第三句';
  assert.equal(extractSentence(text, 4), '第二句');
});

test('extractSentence treats newlines as boundaries', () => {
  assert.equal(extractSentence('line one\nline two', 12), 'line two');
});

test('extractSentence caps the result at 500 characters', () => {
  const long = 'a'.repeat(900);
  assert.equal(extractSentence(long, 0).length, 500);
});

test('extractSentence clamps out-of-range offsets', () => {
  const text = 'only sentence';
  assert.equal(extractSentence(text, -5), 'only sentence');
  assert.equal(extractSentence(text, 9999), 'only sentence');
  assert.equal(extractSentence(text, NaN), 'only sentence');
});

test('extractSentence returns empty for empty / non-string input', () => {
  assert.equal(extractSentence('', 0), '');
  assert.equal(extractSentence(null, 0), '');
  assert.equal(extractSentence(undefined, 3), '');
});

// ---------------------------------------------------------------------------
// buildSelectionMessage
// ---------------------------------------------------------------------------

test('buildSelectionMessage routes a short selection to the quick translate', () => {
  const msg = buildSelectionMessage('serendipity', 'a sentence');
  assert.deepEqual(msg, {
    type: 'translate',
    word: 'serendipity',
    context: 'a sentence',
  });
});

test('buildSelectionMessage routes a long selection (>50 chars) to phrase', () => {
  const long = 'x'.repeat(51);
  const msg = buildSelectionMessage(long, 'ctx');
  assert.deepEqual(msg, { type: 'translatePhrase', text: long, context: 'ctx' });
});

test('buildSelectionMessage uses the isPhrase 50-char boundary exactly', () => {
  // 50 chars → still a word; 51 → phrase. Pins the threshold parity.
  assert.equal(buildSelectionMessage('x'.repeat(50), '').type, 'translate');
  assert.equal(buildSelectionMessage('x'.repeat(51), '').type, 'translatePhrase');
});

test('buildSelectionMessage defaults a missing/null context to empty string', () => {
  assert.equal(buildSelectionMessage('word').context, '');
  assert.equal(buildSelectionMessage('word', undefined).context, '');
  assert.equal(buildSelectionMessage('word', null).context, '');
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
    routeMessage({ type: 'addVocab', entries: [{ word: 'w' }] }),
    { kind: 'addVocab', args: [[{ word: 'w' }]] },
  );
  assert.deepEqual(
    routeMessage({ type: 'listVocab', since: '2024-01-01' }),
    { kind: 'listVocab', args: ['2024-01-01'] },
  );
  assert.deepEqual(
    routeMessage({ type: 'lookupWord', word: 'w' }),
    { kind: 'lookupWord', args: ['w'] },
  );
});

test('routeMessage maps auth_token to a token store op', () => {
  assert.deepEqual(
    routeMessage({ type: 'auth_token', token: 'abc' }),
    { kind: 'setToken', args: ['abc'] },
  );
});

test('routeMessage rejects auth_token without a string token', () => {
  assert.throws(() => routeMessage({ type: 'auth_token' }), /missing token/);
  assert.throws(() => routeMessage({ type: 'auth_token', token: 42 }), /missing token/);
  assert.throws(() => routeMessage({ type: 'auth_token', token: null }), /missing token/);
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
    lookupWord: { type: 'lookupWord', word: 'w' },
    auth_token: { type: 'auth_token', token: 't' },
    get_auth_status: { type: 'get_auth_status' },
    logout: { type: 'logout' },
  };
  for (const t of ROUTABLE_MESSAGE_TYPES) {
    assert.ok(sample[t], `missing sample message for routable type "${t}"`);
    assert.doesNotThrow(() => routeMessage(sample[t]), `type "${t}" should route`);
  }
});

// ---------------------------------------------------------------------------
// isTrustedExternalOrigin
// ---------------------------------------------------------------------------

test('isTrustedExternalOrigin accepts the KG https origin', () => {
  assert.equal(
    isTrustedExternalOrigin('https://wordnexus.lol/login'),
    true,
  );
  assert.equal(isTrustedExternalOrigin('https://wordnexus.lol/'), true);
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
