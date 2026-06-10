/**
 * ios-ref.test.mjs — catalog-backed iOS reference resolution for parity tooling.
 *
 * Run: node --test chrome-extension/tools/ios-ref.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

import { slugify, resolveCatalogRoot, resolveRef } from './ios-ref.mjs';
import { PARITY } from './parity-manifest.mjs';

test('every PARITY ref is null or fully addressed {surface, scenario, appearance}', () => {
  assert.ok(PARITY.length > 0);
  const ids = new Set();
  for (const p of PARITY) {
    assert.ok(p.case && !ids.has(p.case), `duplicate or missing case: ${p.case}`);
    ids.add(p.case);
    if (p.ref === null) continue;
    assert.equal(typeof p.ref.surface, 'string', `${p.case}: ref.surface`);
    assert.equal(typeof p.ref.scenario, 'string', `${p.case}: ref.scenario`);
    assert.ok(['light', 'dark'].includes(p.ref.appearance), `${p.case}: ref.appearance`);
  }
});

function makeRoot(base, name, { totalImages = 1 } = {}) {
  const root = join(base, name);
  mkdirSync(root, { recursive: true });
  writeFileSync(join(root, 'review_manifest.json'), JSON.stringify({ totalImages }));
  return root;
}

function makeShot(root, deviceDir, surface, scenario) {
  const dir = join(root, deviceDir, slugify(surface));
  mkdirSync(dir, { recursive: true });
  const png = join(dir, `${slugify(scenario)}.png`);
  writeFileSync(png, 'PNG');
  return png;
}

test('slugify mirrors playbook Snapshot normalization', () => {
  assert.equal(slugify('Populated · mixed sync states'), 'Populated_·_mixed_sync_states');
  assert.equal(slugify('Edit · empty name (save disabled)'), 'Edit_·_empty_name_(save_disabled)');
  // `.`/`:`/`/` normalize to `_` like whitespace does.
  assert.equal(slugify('Bare card (no links / progress)'), 'Bare_card_(no_links___progress)');
  assert.equal(slugify('Run v1.2: a/b'), 'Run_v1_2__a_b');
});

test('KG_CATALOG_ROOT env override wins', () => {
  const base = mkdtempSync(join(tmpdir(), 'kg-iosref-'));
  try {
    const root = makeRoot(base, 'catalog-full-20260101-000000');
    const resolved = resolveCatalogRoot({ env: { KG_CATALOG_ROOT: root }, repoRoot: '/nonexistent' });
    assert.equal(resolved, root);
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
});

test('auto-discovery picks newest usable root, skipping totalImages=0', () => {
  const repo = mkdtempSync(join(tmpdir(), 'kg-iosref-repo-'));
  try {
    const snaps = join(repo, 'build', 'snapshots');
    makeRoot(snaps, 'catalog-full-20260101-000000');
    const newest = makeRoot(snaps, 'catalog-full-20260301-000000');
    makeRoot(snaps, 'catalog-full-20260601-000000', { totalImages: 0 });
    const resolved = resolveCatalogRoot({ env: {}, repoRoot: repo });
    assert.equal(resolved, newest);
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test('no usable root resolves to null', () => {
  const repo = mkdtempSync(join(tmpdir(), 'kg-iosref-empty-'));
  try {
    assert.equal(resolveCatalogRoot({ env: {}, repoRoot: repo }), null);
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test('resolveRef builds light and dark paths from device dirs', () => {
  const base = mkdtempSync(join(tmpdir(), 'kg-iosref-ref-'));
  try {
    const root = makeRoot(base, 'catalog-full-20260101-000000');
    const light = makeShot(root, 'iPhone 15 Pro portrait', 'Vocabulary List View', 'Populated · mixed sync states');
    const dark = makeShot(root, 'iPhone 15 Pro portrait (dark)', 'Vocabulary List View', 'Populated · mixed sync states');
    const ref = { surface: 'Vocabulary List View', scenario: 'Populated · mixed sync states' };
    assert.equal(resolveRef(root, { ...ref, appearance: 'light' }), light);
    assert.equal(resolveRef(root, { ...ref, appearance: 'dark' }), dark);
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
});

test('resolveRef returns null for missing surface/scenario png', () => {
  const base = mkdtempSync(join(tmpdir(), 'kg-iosref-miss-'));
  try {
    const root = makeRoot(base, 'catalog-full-20260101-000000');
    makeShot(root, 'iPhone 15 Pro portrait', 'Settings', 'Subscribed Active');
    assert.equal(
      resolveRef(root, { surface: 'Settings', scenario: 'No Such Scenario', appearance: 'light' }),
      null,
    );
    assert.equal(
      resolveRef(root, { surface: 'Settings', scenario: 'Subscribed Active', appearance: 'dark' }),
      null,
    );
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
});
