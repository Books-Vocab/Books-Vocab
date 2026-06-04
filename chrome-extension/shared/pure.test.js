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
  normalizeVocabItem,
  classifyError,
  ROUTABLE_MESSAGE_TYPES,
  routeMessage,
  isTrustedExternalOrigin,
  safeUrl,
  escapeHtml,
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

test('routeMessage does NOT route internal auth_token (token writes are onMessageExternal-only)', () => {
  // Token writes are gated by isTrustedExternalOrigin in onMessageExternal;
  // there is no internal auth_token sender, so the internal route is removed.
  assert.throws(
    () => routeMessage({ type: 'auth_token', token: 'abc' }),
    /unknown message type: auth_token/,
  );
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


// ---------------------------------------------------------------------------
// safeUrl
// ---------------------------------------------------------------------------

test('safeUrl passes http and https URLs through unchanged', () => {
  assert.equal(safeUrl('http://example.com/path'), 'http://example.com/path');
  assert.equal(safeUrl('https://wordnexus.lol/x?y=1#z'), 'https://wordnexus.lol/x?y=1#z');
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
  assert.equal(safeUrl('https://wordnexus.lol/a/b'), 'https://wordnexus.lol/a/b');
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
