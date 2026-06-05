/**
 * Regression guards for CSS-cascade invariants that JS unit tests can't catch.
 * Zero external deps — Node's built-in `node:test`. Run from chrome-extension/:
 *   node --test shared/css.test.js
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// Read a stylesheet with /* … */ comments stripped, so prose mentioning a
// selector (e.g. a comment explaining the UA `[hidden]` rule) can't be matched
// as if it were a real declaration.
const read = (rel) =>
  fs.readFileSync(path.join(__dirname, rel), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

// --- The `hidden` attribute must stay authoritative --------------------------
// Bug (shipped in the Phase 1 word-detail panel, never caught because Chrome was
// read-tier so the surface was never rendered): `.kg-detail-panel { display:flex }`
// is an author rule that beats the UA `[hidden] { display:none }`, so #stateDetail
// stayed visible despite the `hidden` attribute. Being position:fixed/inset:0/
// opaque, the empty panel covered the entire sidepanel and could never be closed
// (closeDetail's `hidden = true` was inert). The fix neutralises it once, globally,
// in the shared base. These guards keep that neutraliser in place AND keep the
// attribute as the only toggle the surfaces use.
test('shared base neutralises [hidden] with !important so the attribute always wins', () => {
  const css = read('kg-components.css');
  const m = css.match(/\[hidden\]\s*\{([^}]*)\}/);
  assert.ok(m, 'no `[hidden] { … }` rule in kg-components.css base/reset');
  const body = m[1].replace(/\s+/g, ' ').trim();
  assert.match(body, /display\s*:\s*none\s*!important/i,
    '`[hidden]` rule must declare `display: none !important` — without !important an ' +
    'author class that sets display (.kg-list / .kg-detail-panel) overrides it');
  // The neutraliser must be unscoped — scoping it (e.g. `.kg-surface [hidden]`)
  // would miss surfaces whose <body> lacks the class (the sidepanel body has none).
  assert.match(css, /(^|[\s}])\[hidden\]\s*\{/m,
    '`[hidden]` rule must be a bare global selector, not scoped to an ancestor');
});

// The detail panel is the element the bug manifested on: full-cover, opaque,
// top z-index. Pin the dangerous combination so a future edit that reintroduces
// a display-setting full-cover overlay is paired with the neutraliser above.
test('full-cover detail panel still relies on the [hidden] neutraliser', () => {
  const css = read('../sidepanel/styles.css');
  const m = css.match(/\.kg-detail-panel\s*\{([^}]*)\}/);
  assert.ok(m, '.kg-detail-panel rule not found in sidepanel/styles.css');
  const body = m[1].replace(/\s+/g, ' ');
  // If it sets display + fixed positioning, the attribute toggle is the ONLY thing
  // standing between "closed" and "an opaque panel eating the whole surface".
  assert.match(body, /display\s*:/, '.kg-detail-panel expected to set display');
  assert.match(body, /position\s*:\s*fixed/, '.kg-detail-panel expected position:fixed');
});
