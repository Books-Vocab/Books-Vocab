/**
 * Unit tests for shared/icons.js — the inline-SVG icon set that replaces emoji
 * so chrome surfaces match the iOS SF-Symbols visual language.
 *
 * Zero external deps — Node's built-in `node:test`. Run from chrome-extension/:
 *   node --test shared/icons.test.js
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const KGIcons = require('./icons.js');

// The icon names the chrome surfaces currently consume (header theme + settings,
// card source). Error-state icons are migrated in a later step.
const REQUIRED = [
  'theme-light', 'theme-dark', 'theme-sepia',
  'settings',
  'source-web', 'source-local',
  'search', 'clear', 'check', 'plus', 'pencil', 'trash',
  'books.vertical', 'magnifyingglass', 'sparkles', 'checkmark.seal', 'leaf',
  'line.3.horizontal.decrease.circle',
  'error-login', 'error-quota', 'error-network', 'error-server', 'error-generic',
  // word-detail + navigation + popup glyphs (Phase 0 — unblocks the detail panel,
  // back navigation, speaker TTS, link accessory, refresh, calendar/link footer).
  'speaker', 'chevron-left', 'arrow-up-right', 'square.and.arrow.up', 'doc.on.doc',
  'xmark', 'refresh', 'link', 'calendar',
  // word-detail section-label leading icons (mirror iOS CardSectionLabel)
  'detail-collocation', 'detail-forms',
  // settings grouped-list section-header leading icons
  'account', 'preferences', 'about',
];

test('every required icon yields a well-formed currentColor SVG', () => {
  for (const n of REQUIRED) {
    const s = KGIcons.svg(n);
    assert.ok(s.startsWith('<svg') && s.endsWith('</svg>'), `${n}: balanced <svg>`);
    assert.ok(s.includes('viewBox="0 0 24 24"'), `${n}: 24 grid`);
    assert.ok(s.includes('stroke="currentColor"'), `${n}: inherits color via currentColor`);
    assert.ok(s.includes('aria-hidden="true"'), `${n}: decorative (label lives on the button)`);
    assert.ok(!/<script/i.test(s), `${n}: no <script>`);
  }
});

test('NAMES enumerates exactly the defined icons', () => {
  assert.deepEqual([...KGIcons.NAMES].sort(), [...REQUIRED].sort());
});

test('unknown icon name returns empty string (never throws)', () => {
  assert.equal(KGIcons.svg('nonexistent'), '');
  assert.equal(KGIcons.svg(''), '');
  assert.equal(KGIcons.svg(undefined), '');
});

test('inline popup glyphs in content.js stay in sync with the registry', () => {
  // content/content.js runs in an isolated world and inlines SPEAKER_SVG /
  // XMARK_SVG rather than importing KGIcons. This pins those copies to the
  // registry so a future edit to icons.js cannot silently drift the popup
  // glyphs (the keep-in-sync comment alone is unenforced).
  const fs = require('node:fs');
  const path = require('node:path');
  const src = fs.readFileSync(path.join(__dirname, '../content/content.js'), 'utf8');

  // Inner path markup of a registry glyph (strip the <svg …> wrapper).
  const registryPaths = (name) =>
    KGIcons.svg(name).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '');

  // The single-quoted argument passed to iconSvg(...) for a given const.
  const inlinePaths = (constName) => {
    const m = src.match(new RegExp(constName + "\\s*=\\s*iconSvg\\(\\s*'([^']*)'"));
    assert.ok(m, `${constName} = iconSvg('…') not found in content.js`);
    return m[1];
  };

  assert.equal(inlinePaths('SPEAKER_SVG'), registryPaths('speaker'),
    'content.js SPEAKER_SVG drifted from icons.js speaker glyph');
  assert.equal(inlinePaths('XMARK_SVG'), registryPaths('xmark'),
    'content.js XMARK_SVG drifted from icons.js xmark glyph');
});

test('inline pickPreferredVoice in content.js stays in sync with pure.js', () => {
  // content/content.js inlines pickPreferredVoice (isolated world — no KGPure).
  // Pin it to the pure source so the popup speaker can never drift to a worse
  // voice-selection heuristic than the side panel's. Compares the function
  // bodies with comments + whitespace stripped (indentation differs: top-level
  // in pure.js vs nested in the content IIFE).
  const fs = require('node:fs');
  const path = require('node:path');
  const KGPure = require('./pure.js');

  const norm = (s) =>
    s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '').replace(/\s+/g, '');

  // Brace-match a named function definition out of source text.
  const extractFn = (src, name) => {
    const start = src.indexOf('function ' + name);
    if (start < 0) return null;
    let depth = 0;
    let seen = false;
    for (let i = start; i < src.length; i++) {
      if (src[i] === '{') { depth++; seen = true; }
      else if (src[i] === '}') { depth--; if (seen && depth === 0) return src.slice(start, i + 1); }
    }
    return null;
  };

  const content = fs.readFileSync(path.join(__dirname, '../content/content.js'), 'utf8');
  const inline = extractFn(content, 'pickPreferredVoice');
  assert.ok(inline, 'pickPreferredVoice not found in content.js');
  assert.equal(
    norm(inline),
    norm(KGPure.pickPreferredVoice.toString()),
    'content.js pickPreferredVoice drifted from shared/pure.js#pickPreferredVoice'
  );
});
