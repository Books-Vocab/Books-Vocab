/**
 * Per-case Chrome ⟷ iOS visual parity audit.
 *
 * This is the drill-down companion to compare.mjs. The contact sheet is useful
 * for orientation; this tool creates artifacts that make detailed review
 * repeatable:
 *
 *   tools/audit/<case>/diff.png       absolute pixel-difference heatmap
 *   tools/audit/<case>/zoom.png       enlarged crop strips for close reading
 *   tools/audit/<case>/palette.txt    dominant colors + average color
 *   tools/audit/<case>/metrics.json   RMSE/MAE/SSIM/PHASH metrics
 *   tools/audit/summary.json          all cases in one file
 *
 * Usage:  node tools/parity-audit.mjs [--only <case-substring>]
 * Env:    KG_CATALOG_ROOT  catalog snapshot root override (default: newest
 *         usable build/snapshots/catalog-full-<UTC> — see ios-ref.mjs)
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, writeFileSync, rmSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PARITY } from './parity-manifest.mjs';
import { resolveCatalogRoot, resolveRef } from './ios-ref.mjs';

const EXT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = resolve(EXT_DIR, '..');
const SHOTS = join(EXT_DIR, 'tools', 'shots');
const OUT = join(EXT_DIR, 'tools', 'audit');
const CATALOG_ROOT = resolveCatalogRoot({ repoRoot: REPO_ROOT });
const onlyIdx = process.argv.indexOf('--only');
const ONLY = onlyIdx >= 0 ? process.argv[onlyIdx + 1] : null;

const magick = (args, opts = {}) =>
  execFileSync('magick', args, { stdio: opts.stdio || 'pipe', encoding: opts.encoding || 'utf8' });

function dims(path) {
  const [w, h] = magick(['identify', '-format', '%w %h', path]).trim().split(/\s+/).map(Number);
  return { w, h };
}

function metric(ref, shot, name) {
  try {
    execFileSync('magick', ['compare', '-metric', name, ref, shot, 'null:'], {
      stdio: ['ignore', 'ignore', 'pipe'],
      encoding: 'utf8',
    });
    return '0';
  } catch (err) {
    return String(err.stderr || '').trim();
  }
}

function parseMetric(raw) {
  const first = String(raw).match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/i);
  const normalized = String(raw).match(/\(([-+]?\d*\.?\d+(?:e[-+]?\d+)?)\)/i);
  return {
    raw,
    value: first ? Number(first[0]) : null,
    normalized: normalized ? Number(normalized[1]) : null,
  };
}

function average(path) {
  return magick(['convert', path, '-scale', '1x1!', '-depth', '8', '-format', '%[pixel:p{0,0}]', 'info:']).trim();
}

function histogram(path) {
  return magick([
    'convert', path,
    '-resize', '160x',
    '-colors', '8',
    '-depth', '8',
    '-format', '%c',
    'histogram:info:-',
  ]).trim();
}

function normalizedCopy(src, out, w, h) {
  magick(['convert', src, '-resize', `${w}x${h}!`, out]);
}

function cropRows(w, h) {
  const rows = [
    { name: 'top-chrome', y: 0, height: Math.min(360, h) },
    { name: 'controls', y: Math.min(300, Math.max(0, h - 1)), height: Math.min(420, h) },
    { name: 'body', y: Math.min(660, Math.max(0, h - 1)), height: Math.min(760, h) },
    { name: 'lower', y: Math.min(1380, Math.max(0, h - 1)), height: Math.min(760, h) },
  ];
  return rows
    .map((r) => ({ ...r, y: Math.min(r.y, Math.max(0, h - r.height)) }))
    .filter((r, idx, arr) => r.height > 0 && arr.findIndex((x) => x.y === r.y && x.height === r.height) === idx)
    .map((r) => ({ ...r, geometry: `${w}x${r.height}+0+${r.y}` }));
}

function buildZoom(ref, shot, outDir, w, h) {
  const tiles = [];
  for (const row of cropRows(w, h)) {
    const refCrop = join(outDir, `${row.name}-ios.png`);
    const shotCrop = join(outDir, `${row.name}-chrome.png`);
    const pair = join(outDir, `${row.name}-pair.png`);
    magick(['convert', ref, '-crop', row.geometry, '+repage', '-resize', '200%', refCrop]);
    magick(['convert', shot, '-crop', row.geometry, '+repage', '-resize', '200%', shotCrop]);
    magick(['montage', shotCrop, refCrop, '-tile', '2x1', '-geometry', '+16+0', '-background', '#9aa0a6', pair]);
    tiles.push(pair);
  }
  magick(['montage', ...tiles, '-tile', '1x', '-geometry', '+0+16', '-background', '#222222', join(outDir, 'zoom.png')]);
}

function refLabel(ref) {
  return `${ref.surface} / ${ref.scenario} (${ref.appearance})`;
}

function auditCase(item) {
  const shot = join(SHOTS, `${item.case}.png`);
  const ref = resolveRef(CATALOG_ROOT, item.ref);
  if (!existsSync(shot)) throw new Error(`missing shot: ${shot}`);
  if (!ref) throw new Error(`missing catalog ref for ${item.case}: ${refLabel(item.ref)}`);

  const outDir = join(OUT, item.case);
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  const d = dims(shot);
  const refNorm = join(outDir, 'ios-normalized.png');
  const shotNorm = join(outDir, 'chrome-normalized.png');
  normalizedCopy(ref, refNorm, d.w, d.h);
  normalizedCopy(shot, shotNorm, d.w, d.h);

  magick(['convert', refNorm, shotNorm, '-compose', 'difference', '-composite', '-auto-level', join(outDir, 'diff.png')]);
  buildZoom(refNorm, shotNorm, outDir, d.w, d.h);

  const metrics = {
    case: item.case,
    note: item.note,
    reference: refLabel(item.ref),
    dimensions: d,
    rmse: parseMetric(metric(refNorm, shotNorm, 'RMSE')),
    mae: parseMetric(metric(refNorm, shotNorm, 'MAE')),
    ssim: parseMetric(metric(refNorm, shotNorm, 'SSIM')),
    phash: parseMetric(metric(refNorm, shotNorm, 'PHASH')),
    average: {
      chrome: average(shotNorm),
      ios: average(refNorm),
    },
  };
  writeFileSync(join(outDir, 'metrics.json'), JSON.stringify(metrics, null, 2) + '\n');
  writeFileSync(join(outDir, 'palette.txt'),
    `# ${item.case}\n\n## Average\nchrome: ${metrics.average.chrome}\nios:    ${metrics.average.ios}\n\n` +
    `## Chrome dominant colors\n${histogram(shotNorm)}\n\n## iOS dominant colors\n${histogram(refNorm)}\n`);
  return metrics;
}

function main() {
  if (!CATALOG_ROOT) {
    console.error('no usable catalog snapshot root under build/snapshots');
    console.error('generate one: ./ops/ios_ops.sh catalog snapshots  (or set KG_CATALOG_ROOT)');
    process.exit(1);
  }
  mkdirSync(OUT, { recursive: true });
  const refCases = PARITY.filter((p) => p.ref);
  const cases = ONLY ? refCases.filter((p) => p.case.includes(ONLY)) : refCases;
  if (cases.length === 0) {
    console.error(`no parity case matches --only ${ONLY}`);
    process.exit(1);
  }

  const summary = [];
  for (const item of cases) {
    const result = auditCase(item);
    summary.push(result);
    const rmse = result.rmse.normalized ?? result.rmse.value;
    const mae = result.mae.normalized ?? result.mae.value;
    const ssim = result.ssim.normalized ?? result.ssim.value;
    console.error(`✓ ${item.case}  RMSE=${rmse}  MAE=${mae}  SSIM=${ssim}`);
  }
  writeFileSync(join(OUT, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  console.error(`\nAudit artifacts: chrome-extension/tools/audit/<case>/{diff,zoom,palette,metrics}`);
  console.error(`Summary: chrome-extension/tools/audit/summary.json`);
}

main();
