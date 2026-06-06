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
 * Env:    IOS_REF_DIR  iOS reference PNG folder (default: ~/Desktop/IOS截圖參考)
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';

const EXT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = join(EXT_DIR, 'tools', 'shots');
const OUT = join(EXT_DIR, 'tools', 'compare');
const IOS_REF = process.env.IOS_REF_DIR || join(homedir(), 'Desktop', 'IOS截圖參考');

// case → iOS reference PNG it should mirror (null = Chrome-only state, no iOS
// counterpart: loading / empty / error are sidepanel-specific surfaces).
const PARITY = [
  { case: 'sidepanel-content-light', ref: 'IMG_8954.PNG', note: '單字本列表 (light)' },
  { case: 'content-popup-notebook-light', ref: null, note: '選詞 popup + 目標單字本 selector (Chrome content state)' },
  { case: 'sidepanel-outbox-failed-light', ref: null, note: '失敗暫存列 + 手動重試 (Chrome outbox state)' },
  { case: 'sidepanel-notebook-sheet-light', ref: null, note: '單字本編輯 sheet (Chrome-only until iOS ref exists)' },
  { case: 'sidepanel-content-dark', ref: 'IMG_8954.PNG', note: '單字本列表 (dark)' },
  { case: 'sidepanel-content-sepia', ref: 'IMG_8954.PNG', note: '單字本列表 (sepia)' },
  { case: 'sidepanel-detail-light', ref: 'IMG_8955.PNG', note: '單字詳情' },
  { case: 'options-settings-light', ref: 'IMG_8957.PNG', note: '設定頁（已登入/Pro）' },
  { case: 'sidepanel-empty-light', ref: null, note: '空狀態 (Chrome-only)' },
  { case: 'sidepanel-error-light', ref: null, note: '錯誤狀態 (Chrome-only)' },
];

const magick = (args) => execFileSync('magick', args, { stdio: 'pipe' });

function main() {
  if (!existsSync(SHOTS) || readdirSync(SHOTS).length === 0) {
    console.error('no shots found — run `node tools/shots.mjs` first');
    process.exit(1);
  }
  mkdirSync(OUT, { recursive: true });
  const haveRefDir = existsSync(IOS_REF);
  if (!haveRefDir) console.error(`⚠ iOS ref dir not found: ${IOS_REF} — pairing chrome-only`);

  const cells = []; // pair PNGs feeding the contact sheet, in PARITY order
  const legend = [];

  for (const p of PARITY) {
    const shot = join(SHOTS, `${p.case}.png`);
    if (!existsSync(shot)) { console.error(`⚠ missing shot: ${p.case}`); continue; }
    const pairPng = join(OUT, `${p.case}.png`);
    const refPath = p.ref && haveRefDir ? join(IOS_REF, p.ref) : null;

    if (refPath && existsSync(refPath)) {
      // chrome | iOS, equal height (both 2556), grey gutter between.
      magick(['montage', shot, refPath, '-tile', '2x1', '-geometry', '+12+0',
        '-background', '#9aa0a6', pairPng]);
      legend.push(`${cells.length + 1}. ${p.case}  ⟷  iOS ${p.ref}   — ${p.note}`);
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
