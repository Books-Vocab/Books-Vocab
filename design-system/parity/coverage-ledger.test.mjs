// Coverage-ledger core: catalog scenes ⟷ parity refs pairing, layered tally,
// orphan-ref detection. The honest-completeness meter for the web design system
// (analogue of lab's catalog_coverage loss meter — no inflation vectors).
//
// Run: node --test design-system/parity/coverage-ledger.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { computeCoverage } from './coverage-ledger.mjs';

const scenes = [
  { surface: 'Bookshelf View', scenario: 'Populated · mixed formats', feature: 'Bookshelf', assetKind: 'screen', eligibility: 'marketing' },
  { surface: 'Bookshelf View', scenario: 'Empty shelf', feature: 'Bookshelf', assetKind: 'screen', eligibility: 'marketing' },
  { surface: 'Reader · Translation', scenario: 'Reading · Overlay', feature: 'Reader', assetKind: 'overlay', eligibility: 'engineering' },
];

test('pairs by slug, counts covered/missing, layers by feature', () => {
  const refs = [
    { surface: 'Bookshelf View', scenario: 'Populated · mixed formats' }, // exact
    { surface: 'Reader · Translation', scenario: 'Reading · Overlay' },    // slug match (· → _)
  ];
  const r = computeCoverage(scenes, refs);
  assert.equal(r.total, 3);
  assert.equal(r.covered, 2);
  assert.equal(r.missing.length, 1);
  assert.equal(r.missing[0].scenario, 'Empty shelf');
  assert.equal(r.byFeature.Bookshelf.covered, 1);
  assert.equal(r.byFeature.Bookshelf.total, 2);
  assert.equal(r.byFeature.Reader.covered, 1);
  assert.equal(r.byAssetKind.overlay.covered, 1);
  assert.equal(r.byEligibility.engineering.covered, 1);
});

test('flags orphan refs that match no catalog scene (stale/typo manifest)', () => {
  const refs = [
    { surface: 'Ghost Surface', scenario: 'Nope' },
    { surface: 'Bookshelf View', scenario: 'Empty shelf' },
  ];
  const r = computeCoverage(scenes, refs);
  assert.equal(r.orphanRefs.length, 1);
  assert.equal(r.orphanRefs[0].surface, 'Ghost Surface');
  assert.equal(r.covered, 1); // only Empty shelf
});

test('dedupes appearance variants of the same ref into one scene hit', () => {
  // light+dark of the same scene must not double-count coverage.
  const refs = [
    { surface: 'Bookshelf View', scenario: 'Empty shelf', appearance: 'light' },
    { surface: 'Bookshelf View', scenario: 'Empty shelf', appearance: 'dark' },
  ];
  const r = computeCoverage(scenes, refs);
  assert.equal(r.covered, 1);
  assert.equal(r.byFeature.Bookshelf.covered, 1);
});

test('invariant: covered + missing == total (no scene lost or double-counted)', () => {
  const refs = [{ surface: 'Bookshelf View', scenario: 'Populated · mixed formats' }];
  const r = computeCoverage(scenes, refs);
  assert.equal(r.covered + r.missing.length, r.total);
});

test('a ref hitting an engineering scene is NOT an orphan; headline excludes engineering', () => {
  const withEng = [
    ...scenes,
    { surface: 'Selection Toolbar', scenario: 'Multiple selected', feature: 'Vocabulary', assetKind: 'component', eligibility: 'engineering' },
  ];
  const refs = [{ surface: 'Selection Toolbar', scenario: 'Multiple selected' }]; // valid, targets engineering
  const r = computeCoverage(withEng, refs);
  assert.equal(r.orphanRefs.length, 0);          // engineering scene exists in catalog → not orphan
  assert.equal(r.byEligibility.engineering.covered, 1);
  assert.equal(r.headline.total, 2);             // 2 non-engineering scenes (Reader·Translation is engineering)
  assert.equal(r.headline.covered, 0);           // none of the non-eng scenes covered
  assert.equal(r.total, 4);                       // full catalog incl engineering
});
