/**
 * parity-core.mjs — surface-agnostic web ⟷ iOS visual-parity engine.
 *
 * Extracted from chrome-extension/tools/{compare,parity-audit}.mjs so every
 * web surface (chrome extension, web app pilot, future slices) runs the SAME
 * compositor + audit instead of growing hand-copied mirrors. Consumers stay
 * thin: a parity manifest (case list addressed by Catalog taxonomy — see
 * ios-ref.mjs), a shots dir, an out dir, and a `shotLabel` naming their side
 * of each pair ('chrome' / 'web').
 *
 * composeContactSheet: pairs each shot with its iOS Catalog reference and
 * tiles all pairs into one contact sheet (review-as-one-read; only an
 * off-looking case needs its full-res pair opened).
 *
 * runParityAudit: per-case drill-down — diff heatmap, zoomed crop strips,
 * palette summary, RMSE/MAE/SSIM/PHASH metrics + summary.json. Use whenever
 * precise parity matters; the sheet is only orientation.
 *
 * ImageMagick has no Freetype delegate here, so labels can't be burned in;
 * fixed layout order + printed legend instead.
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, existsSync, readdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';

import { resolveCatalogRoot, resolveRef } from './ios-ref.mjs';

const magick = (args, opts = {}) =>
  execFileSync('magick', args, { stdio: opts.stdio || 'pipe', encoding: opts.encoding || 'utf8' });

// ---------------------------------------------------------------- compose --

/**
 * Pair every manifest case's shot with its Catalog reference and build one
 * contact sheet. Returns the sheet path (null when nothing composited).
 *
 * @param {object} cfg
 * @param {Array}  cfg.parity     manifest entries {case, ref, note}
 * @param {string} cfg.shotsDir   dir holding <case>.png shots
 * @param {string} cfg.outDir     dir for per-case pairs + contact.png
 * @param {string} cfg.repoRoot   repo root for catalog auto-discovery
 * @param {string} cfg.shotLabel  name of the non-iOS side ('chrome' / 'web')
 */
export function composeContactSheet({ parity, shotsDir, outDir, repoRoot, shotLabel }) {
  if (!existsSync(shotsDir) || readdirSync(shotsDir).length === 0) {
    console.error(`no shots found in ${shotsDir} — run the shots step first`);
    process.exit(1);
  }
  mkdirSync(outDir, { recursive: true });
  const catalogRoot = resolveCatalogRoot({ repoRoot });
  if (!catalogRoot) {
    console.error(`⚠ no usable catalog snapshot root under build/snapshots — pairing ${shotLabel}-only`);
    console.error('  generate one: ./ops/ios_ops.sh catalog snapshots  (or set KG_CATALOG_ROOT)');
  }

  const cells = []; // pair PNGs feeding the contact sheet, in manifest order
  const legend = [];

  for (const p of parity) {
    const shot = join(shotsDir, `${p.case}.png`);
    if (!existsSync(shot)) { console.error(`⚠ missing shot: ${p.case}`); continue; }
    const pairPng = join(outDir, `${p.case}.png`);
    const refPath = p.ref && catalogRoot ? resolveRef(catalogRoot, p.ref) : null;
    if (p.ref && catalogRoot && !refPath) {
      console.error(`⚠ catalog ref missing for ${p.case}: ${p.ref.surface} / ${p.ref.scenario} (${p.ref.appearance})`);
    }

    if (refPath) {
      // shot | iOS, equal height, grey gutter between.
      magick(['montage', shot, refPath, '-tile', '2x1', '-geometry', '+12+0',
        '-background', '#9aa0a6', pairPng]);
      legend.push(`${cells.length + 1}. ${p.case}  ⟷  iOS ${p.ref.surface} / ${p.ref.scenario} (${p.ref.appearance})   — ${p.note}`);
    } else {
      // shot-only: single image, no pairing.
      magick(['convert', shot, '-bordercolor', '#9aa0a6', '-border', '6', pairPng]);
      legend.push(`${cells.length + 1}. ${p.case}  (no iOS ref)   — ${p.note}`);
    }
    cells.push(pairPng);
  }

  if (cells.length === 0) { console.error('nothing to composite'); process.exit(1); }

  // One contact sheet — equal-height cells (x760), 2 columns, grey gutter.
  const sheet = join(outDir, 'contact.png');
  magick(['montage', ...cells, '-tile', '2x', '-geometry', 'x760+10+10',
    '-background', '#222222', sheet]);

  const dims = magick(['identify', '-format', '%wx%h', sheet]).toString();
  console.error('\nContact sheet:', sheet, `(${dims})`);
  console.error('Cell order (left→right, top→bottom):');
  for (const l of legend) console.error('  ' + l);
  console.error(`\nFull-res pairs in ${outDir}/<case>.png`);
  return sheet;
}

// ------------------------------------------------------------------ audit --

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
  // -alpha off: Catalog PNGs carry an alpha channel, Playwright shots don't.
  // `-compose difference` would difference alpha too (255−255=0 → a fully
  // transparent diff.png) and skew metrics; both sides flatten to opaque RGB.
  magick(['convert', src, '-resize', `${w}x${h}!`, '-alpha', 'off', out]);
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

function buildZoom(ref, shot, outDir, w, h, shotLabel) {
  const tiles = [];
  for (const row of cropRows(w, h)) {
    const refCrop = join(outDir, `${row.name}-ios.png`);
    const shotCrop = join(outDir, `${row.name}-${shotLabel}.png`);
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

function auditCase(item, { shotsDir, outRoot, catalogRoot, shotLabel }) {
  const shot = join(shotsDir, `${item.case}.png`);
  const ref = resolveRef(catalogRoot, item.ref);
  if (!existsSync(shot)) throw new Error(`missing shot: ${shot}`);
  if (!ref) throw new Error(`missing catalog ref for ${item.case}: ${refLabel(item.ref)}`);

  const outDir = join(outRoot, item.case);
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  const d = dims(shot);
  const refNorm = join(outDir, 'ios-normalized.png');
  const shotNorm = join(outDir, `${shotLabel}-normalized.png`);
  normalizedCopy(ref, refNorm, d.w, d.h);
  normalizedCopy(shot, shotNorm, d.w, d.h);

  magick(['convert', refNorm, shotNorm, '-compose', 'difference', '-composite', '-auto-level', join(outDir, 'diff.png')]);
  buildZoom(refNorm, shotNorm, outDir, d.w, d.h, shotLabel);

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
      [shotLabel]: average(shotNorm),
      ios: average(refNorm),
    },
  };
  writeFileSync(join(outDir, 'metrics.json'), JSON.stringify(metrics, null, 2) + '\n');
  writeFileSync(join(outDir, 'palette.txt'),
    `# ${item.case}\n\n## Average\n${shotLabel}: ${metrics.average[shotLabel]}\nios:    ${metrics.average.ios}\n\n` +
    `## ${shotLabel} dominant colors\n${histogram(shotNorm)}\n\n## iOS dominant colors\n${histogram(refNorm)}\n`);
  return metrics;
}

/**
 * Run the per-case parity audit for every ref-bearing manifest case
 * (optionally filtered by `only` substring). Writes per-case artifacts under
 * outDir/<case>/ and an aggregate outDir/summary.json.
 */
export function runParityAudit({ parity, shotsDir, outDir, repoRoot, shotLabel, only = null }) {
  const catalogRoot = resolveCatalogRoot({ repoRoot });
  if (!catalogRoot) {
    console.error('no usable catalog snapshot root under build/snapshots');
    console.error('generate one: ./ops/ios_ops.sh catalog snapshots  (or set KG_CATALOG_ROOT)');
    process.exit(1);
  }
  mkdirSync(outDir, { recursive: true });
  const refCases = parity.filter((p) => p.ref);
  const cases = only ? refCases.filter((p) => p.case.includes(only)) : refCases;
  if (cases.length === 0) {
    console.error(`no parity case matches --only ${only}`);
    process.exit(1);
  }

  const summary = [];
  for (const item of cases) {
    const result = auditCase(item, { shotsDir, outRoot: outDir, catalogRoot, shotLabel });
    summary.push(result);
    const rmse = result.rmse.normalized ?? result.rmse.value;
    const mae = result.mae.normalized ?? result.mae.value;
    const ssim = result.ssim.normalized ?? result.ssim.value;
    console.error(`✓ ${item.case}  RMSE=${rmse}  MAE=${mae}  SSIM=${ssim}`);
  }
  writeFileSync(join(outDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  console.error(`\nAudit artifacts: ${outDir}/<case>/{diff,zoom,palette,metrics}`);
  console.error(`Summary: ${outDir}/summary.json`);
  return summary;
}
