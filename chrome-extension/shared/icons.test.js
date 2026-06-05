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
  'search', 'clear', 'check',
  'error-login', 'error-quota', 'error-network', 'error-server', 'error-generic',
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
