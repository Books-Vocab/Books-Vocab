/**
 * Visual-parity compositor — pairs each Chrome shot (from shots.mjs) with the
 * iOS reference it should mirror, then tiles all pairs into ONE contact sheet.
 *
 * Why one sheet: reviewing parity is a vision task (colour / type / spacing /
 * component shape), and loading N image pairs separately is the exact token
 * waste this tool exists to kill. The single sheet lets a reviewer (human or
 * model) eyeball every case's alignment in one read; only a case that looks off
 * needs its full-resolution pair (tools/compare/<case>.png) opened.
 *
 * ImageMagick here has no Freetype delegate, so labels can't be burned in.
 * Instead the layout order is fixed and printed as a text legend — zero-vision
 * annotation that maps each sheet cell back to its case + iOS reference.
 *
 * Usage:  node tools/compare.mjs
 * Env:    KG_CATALOG_ROOT  catalog snapshot root override (default: newest
 *         usable build/snapshots/catalog-full-<UTC> — see ios-ref.mjs)
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PARITY } from './parity-manifest.mjs';
import { resolveCatalogRoot, resolveRef } from './ios-ref.mjs';

const EXT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = resolve(EXT_DIR, '..');
const SHOTS = join(EXT_DIR, 'tools', 'shots');
const OUT = join(EXT_DIR, 'tools', 'compare');

const magick = (args) => execFileSync('magick', args, { stdio: 'pipe' });

function main() {
  if (!existsSync(SHOTS) || readdirSync(SHOTS).length === 0) {
    console.error('no shots found — run `node tools/shots.mjs` first');
    process.exit(1);
  }
  mkdirSync(OUT, { recursive: true });
  const catalogRoot = resolveCatalogRoot({ repoRoot: REPO_ROOT });
  if (!catalogRoot) {
    console.error('⚠ no usable catalog snapshot root under build/snapshots — pairing chrome-only');
    console.error('  generate one: ./ops/ios_ops.sh catalog snapshots  (or set KG_CATALOG_ROOT)');
  }

  const cells = []; // pair PNGs feeding the contact sheet, in PARITY order
  const legend = [];

  for (const p of PARITY) {
    const shot = join(SHOTS, `${p.case}.png`);
    if (!existsSync(shot)) { console.error(`⚠ missing shot: ${p.case}`); continue; }
    const pairPng = join(OUT, `${p.case}.png`);
    const refPath = p.ref && catalogRoot ? resolveRef(catalogRoot, p.ref) : null;
    if (p.ref && catalogRoot && !refPath) {
      console.error(`⚠ catalog ref missing for ${p.case}: ${p.ref.surface} / ${p.ref.scenario} (${p.ref.appearance})`);
    }

    if (refPath) {
      // chrome | iOS, equal height (both 2556), grey gutter between.
      magick(['montage', shot, refPath, '-tile', '2x1', '-geometry', '+12+0',
        '-background', '#9aa0a6', pairPng]);
      legend.push(`${cells.length + 1}. ${p.case}  ⟷  iOS ${p.ref.surface} / ${p.ref.scenario} (${p.ref.appearance})   — ${p.note}`);
    } else {
      // chrome-only: single shot, no pairing.
      magick(['convert', shot, '-bordercolor', '#9aa0a6', '-border', '6', pairPng]);
      legend.push(`${cells.length + 1}. ${p.case}  (no iOS ref)   — ${p.note}`);
    }
    cells.push(pairPng);
  }

  if (cells.length === 0) { console.error('nothing to composite'); process.exit(1); }

  // One contact sheet — equal-height cells (x760), 2 columns, grey gutter.
  const sheet = join(OUT, 'contact.png');
  magick(['montage', ...cells, '-tile', '2x', '-geometry', 'x760+10+10',
    '-background', '#222222', sheet]);

  const dims = magick(['identify', '-format', '%wx%h', sheet]).toString();
  console.error('\nContact sheet:', join('chrome-extension', 'tools', 'compare', 'contact.png'), `(${dims})`);
  console.error('Cell order (left→right, top→bottom):');
  for (const l of legend) console.error('  ' + l);
  console.error('\nFull-res pairs in chrome-extension/tools/compare/<case>.png');
}

main();
