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

import { execFile } from 'node:child_process';
import { mkdirSync, existsSync, readdirSync, writeFileSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { cpus } from 'node:os';
import { promisify } from 'node:util';

import { resolveCatalogRoot, resolveRef } from './ios-ref.mjs';

const pExecFile = promisify(execFile);

// async magick — every ImageMagick call is non-blocking so the per-case audit
// fans out across cores instead of serializing one `magick` at a time (the old
// execFileSync pinned the whole 193-case run to a single core). 64 MiB buffer
// covers the largest montage stdout; magick writes images to files, not stdout.
const magick = async (args) => {
  const { stdout } = await pExecFile('magick', args, { maxBuffer: 64 * 1024 * 1024 });
  return stdout;
};

// Default fan-out: leave 2 cores for the OS / node loop. PARITY_CONCURRENCY
// overrides (e.g. =1 to serialize for deterministic logs, or higher on big hosts).
const CONCURRENCY = Math.max(
  1,
  Number(process.env.PARITY_CONCURRENCY) || Math.max(1, cpus().length - 2),
);

/**
 * Bounded-concurrency parallel map with live progress. `fn(item, index)` runs
 * for every item with at most `concurrency` in flight; `onDone(completed, total,
 * item, result)` fires as each finishes (out of order). Results keep input order.
 */
async function pmap(items, concurrency, fn, onDone) {
  const results = new Array(items.length);
  let cursor = 0;
  let completed = 0;
  const worker = async () => {
    while (true) {
      const i = cursor++;
      if (i >= items.length) return;
      results[i] = await fn(items[i], i);
      completed += 1;
      if (onDone) onDone(completed, items.length, items[i], results[i]);
    }
  };
  const lanes = Math.max(1, Math.min(concurrency, items.length || 1));
  await Promise.all(Array.from({ length: lanes }, worker));
  return results;
}

/**
 * Live progress reporter — prints `[done/total] (elapsed · eta · rate) label`
 * to stderr on every completion, so a long fan-out is never silent. nowMs is
 * injected (Date.now is unavailable in some sandboxes); callers pass () => Date.now().
 */
function makeProgress(total, label, nowMs = () => Date.now()) {
  const start = nowMs();
  const fmt = (ms) => `${(ms / 1000).toFixed(0)}s`;
  return (done, _total, _item, line = '') => {
    const elapsed = nowMs() - start;
    const rate = done / Math.max(1, elapsed / 1000);
    const eta = rate > 0 ? (total - done) / rate * 1000 : 0;
    const head = `[${String(done).padStart(String(total).length)}/${total}] ` +
      `${fmt(elapsed)} elapsed · ~${fmt(eta)} left · ${rate.toFixed(1)}/s`;
    process.stderr.write(`${head}  ${label}${line ? ' ' + line : ''}\n`);
  };
}

// ---------------------------------------------------------------- compose --

/**
 * Pair every manifest case's shot with its Catalog reference and build one
 * contact sheet. Returns the sheet path; exits non-zero when there are no
 * shots or nothing composites (CLI tool semantics).
 *
 * @param {object} cfg
 * @param {Array}  cfg.parity     manifest entries {case, ref, note}
 * @param {string} cfg.shotsDir   dir holding <case>.png shots
 * @param {string} cfg.outDir     dir for per-case pairs + contact.png
 * @param {string} cfg.repoRoot   repo root for catalog auto-discovery
 * @param {string} cfg.shotLabel  name of the non-iOS side ('chrome' / 'web')
 */
export async function composeContactSheet({ parity, shotsDir, outDir, repoRoot, shotLabel, nowMs }) {
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

  const present = parity.filter((p) => {
    if (existsSync(join(shotsDir, `${p.case}.png`))) return true;
    console.error(`⚠ missing shot: ${p.case}`);
    return false;
  });

  // Pair montages are independent per case → fan out across cores with live
  // progress (was a silent serial loop). Results keep manifest order for the sheet.
  console.error(`pairing ${present.length} cases  (concurrency ${CONCURRENCY})`);
  const tick = makeProgress(present.length, 'paired', nowMs);
  const paired = await pmap(present, CONCURRENCY, async (p) => {
    const shot = join(shotsDir, `${p.case}.png`);
    const pairPng = join(outDir, `${p.case}.png`);
    const refPath = p.ref && catalogRoot ? await prepareRef(p, catalogRoot, outDir) : null;
    if (p.ref && catalogRoot && !refPath) {
      console.error(`⚠ catalog ref missing for ${p.case}: ${p.ref.surface} / ${p.ref.scenario} (${p.ref.appearance})`);
    }
    if (refPath) {
      await magick(['montage', shot, refPath, '-tile', '2x1', '-geometry', '+12+0',
        '-background', '#9aa0a6', pairPng]);
      return { pairPng, legend: `${p.case}  ⟷  iOS ${p.ref.surface} / ${p.ref.scenario} (${p.ref.appearance})   — ${p.note}` };
    }
    await magick(['convert', shot, '-bordercolor', '#9aa0a6', '-border', '6', pairPng]);
    return { pairPng, legend: `${p.case}  (no iOS ref)   — ${p.note}` };
  }, (done, total, _p, _r) => tick(done, total, _p));

  const cells = paired.map((r) => r.pairPng);
  const legend = paired.map((r, i) => `${i + 1}. ${r.legend}`);
  if (cells.length === 0) { console.error('nothing to composite'); process.exit(1); }

  // One contact sheet — equal-height cells (x760), 2 columns, grey gutter.
  const sheet = join(outDir, 'contact.png');
  console.error('tiling contact sheet …');
  await magick(['montage', ...cells, '-tile', '2x', '-geometry', 'x760+10+10',
    '-background', '#222222', sheet]);

  const dims = (await magick(['identify', '-format', '%wx%h', sheet])).toString();
  console.error('\nContact sheet:', sheet, `(${dims})`);
  console.error('Cell order (left→right, top→bottom):');
  for (const l of legend) console.error('  ' + l);
  console.error(`\nFull-res pairs in ${outDir}/<case>.png`);
  return sheet;
}

// ------------------------------------------------------------------ audit --

async function dims(path) {
  const [w, h] = (await magick(['identify', '-format', '%w %h', path])).trim().split(/\s+/).map(Number);
  return { w, h };
}

async function metric(ref, shot, name) {
  try {
    // `magick compare` exits non-zero when the images differ (the normal case)
    // and writes the metric to stderr — so a rejection here is expected, not an error.
    await pExecFile('magick', ['compare', '-metric', name, ref, shot, 'null:'], {
      maxBuffer: 16 * 1024 * 1024,
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

async function average(path) {
  return (await magick(['convert', path, '-scale', '1x1!', '-depth', '8', '-format', '%[pixel:p{0,0}]', 'info:'])).trim();
}

async function histogram(path) {
  return (await magick([
    'convert', path,
    '-resize', '160x',
    '-colors', '8',
    '-depth', '8',
    '-format', '%c',
    'histogram:info:-',
  ])).trim();
}

async function normalizedCopy(src, out, w, h) {
  // -alpha off: Catalog PNGs carry an alpha channel, Playwright shots don't.
  // `-compose difference` would difference alpha too (255−255=0 → a fully
  // transparent diff.png) and skew metrics; both sides flatten to opaque RGB.
  await magick(['convert', src, '-resize', `${w}x${h}!`, '-alpha', 'off', out]);
}

/**
 * Component bbox of a Catalog ref PNG: the opaque-content bounding box, found
 * by flattening on black, thresholding away the near-transparent scrim, and
 * trimming. Returns "WxH+X+Y" (ImageMagick geometry) or null when the whole
 * frame is opaque (no transparent margin → not a component scene).
 *
 * Why this exists — the black-floor honesty fix:
 *   Bottom-sheet / overlay Catalog scenes (Reader · Translation 6 態) render
 *   the component (a white panel) over a *transparent* backdrop carrying only a
 *   faint scrim (black α≈0.024). parity normalize does `-alpha off`, which turns
 *   that whole transparent void into near-black. A white panel measured against
 *   a frame that is ~70% black void inflates RMSE into a 0.20–0.27 *floor* that
 *   is a compositing artifact, not a visual diff (the void isn't even rendered
 *   in the real app — the live reader page sits there). Cropping ref + shot to
 *   the component removes the void from the denominator so the metric reflects
 *   the panel itself. Threshold 6% (of 255 ≈ 15) clears the α≈0.024 scrim
 *   (≈6 on black) while keeping the panel (≥40). Mirrors the iOS-side tight
 *   crop that selection-toolbar already ships (PR #958); here the Catalog refs
 *   are still full-frame, so the engine does the equivalent crop at audit time.
 */
async function refComponentBbox(refPng) {
  const geom = (await magick([
    'convert', refPng, '-alpha', 'off', '-colorspace', 'Gray',
    '-threshold', '6%', '-format', '%@', 'info:',
  ])).trim();
  const m = geom.match(/^(\d+)x(\d+)\+(\d+)\+(\d+)$/);
  if (!m) return null;
  const [, w, h] = m.map(Number);
  // A trim that returns the full canvas = no transparent margin = not a
  // component scene; treat as no-op so this stays safe to flag broadly.
  const [fw, fh] = (await magick(['identify', '-format', '%w %h', refPng])).trim().split(/\s+/).map(Number);
  if (w === fw && h === fh) return null;
  return geom;
}

/**
 * Resolve a ref to an absolute PNG, applying component cropping when the case
 * declares `refCrop: 'panel'`. The cropped PNG is written next to the audit
 * artifacts so downstream steps treat it like any other ref. Returns the path
 * to use (cropped or original), or null if the ref is missing.
 */
async function prepareRef(item, catalogRoot, outDir) {
  const ref = resolveRef(catalogRoot, item.ref);
  if (!ref) return null;
  if (item.refCrop !== 'panel') return ref;
  const bbox = await refComponentBbox(ref);
  if (!bbox) return ref; // no transparent margin — nothing to crop
  // Case-keyed name: composeContactSheet shares one outDir across cases, so a
  // fixed filename would collide; auditCase has a per-case outDir but the keyed
  // name is harmless there too.
  const cropped = join(outDir, `${item.case}.ios-component.png`);
  await magick(['convert', ref, '-crop', bbox, '+repage', cropped]);
  return cropped;
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

async function buildZoom(ref, shot, outDir, w, h, shotLabel) {
  const rows = cropRows(w, h);
  const tiles = await Promise.all(rows.map(async (row) => {
    const refCrop = join(outDir, `${row.name}-ios.png`);
    const shotCrop = join(outDir, `${row.name}-${shotLabel}.png`);
    const pair = join(outDir, `${row.name}-pair.png`);
    await magick(['convert', ref, '-crop', row.geometry, '+repage', '-resize', '200%', refCrop]);
    await magick(['convert', shot, '-crop', row.geometry, '+repage', '-resize', '200%', shotCrop]);
    await magick(['montage', shotCrop, refCrop, '-tile', '2x1', '-geometry', '+16+0', '-background', '#9aa0a6', pair]);
    return pair;
  }));
  await magick(['montage', ...tiles, '-tile', '1x', '-geometry', '+0+16', '-background', '#222222', join(outDir, 'zoom.png')]);
}

function refLabel(ref) {
  return `${ref.surface} / ${ref.scenario} (${ref.appearance})`;
}

async function auditCase(item, { shotsDir, outRoot, catalogRoot, shotLabel, metricsOnly = false }) {
  const shot = join(shotsDir, `${item.case}.png`);
  if (!existsSync(shot)) throw new Error(`missing shot: ${shot}`);

  const outDir = join(outRoot, item.case);
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  // prepareRef may write a component-cropped ref into outDir (refCrop cases).
  const ref = await prepareRef(item, catalogRoot, outDir);
  if (!ref) throw new Error(`missing catalog ref for ${item.case}: ${refLabel(item.ref)}`);

  const d = await dims(shot);
  const refNorm = join(outDir, 'ios-normalized.png');
  const shotNorm = join(outDir, `${shotLabel}-normalized.png`);
  // Both normalized copies are independent — produce them concurrently; every
  // downstream magick call (diff/zoom/metrics) depends on both, so we join first.
  await Promise.all([
    normalizedCopy(ref, refNorm, d.w, d.h),
    normalizedCopy(shot, shotNorm, d.w, d.h),
  ]);

  // metricsOnly: skip the diagnostic imagery (diff heatmap, zoom crop strips,
  // palette histogram) and phash — they are ~75% of the magick work and are
  // only needed for visual drill-down, not for the verdict gate (rmse/mae/ssim).
  // The MEASURED numbers are byte-identical to a full audit; this only drops
  // artifacts a human reads. Run full `--audit` (no --metrics-only) to get them.
  const artifacts = metricsOnly ? Promise.resolve() : Promise.all([
    magick(['convert', refNorm, shotNorm, '-compose', 'difference', '-composite', '-auto-level', join(outDir, 'diff.png')]),
    buildZoom(refNorm, shotNorm, outDir, d.w, d.h, shotLabel),
  ]);

  // The 3 gated metrics + phash + 2 averages all read the same two normalized
  // PNGs and are mutually independent → run them concurrently within the case.
  const [rmse, mae, ssim, phash, avgShot, avgIos] = await Promise.all([
    metric(refNorm, shotNorm, 'RMSE'),
    metric(refNorm, shotNorm, 'MAE'),
    metric(refNorm, shotNorm, 'SSIM'),
    metricsOnly ? Promise.resolve(null) : metric(refNorm, shotNorm, 'PHASH'),
    average(shotNorm),
    average(refNorm),
  ]);

  const metrics = {
    case: item.case,
    note: item.note,
    reference: refLabel(item.ref),
    dimensions: d,
    rmse: parseMetric(rmse),
    mae: parseMetric(mae),
    ssim: parseMetric(ssim),
    phash: phash === null ? null : parseMetric(phash),
    average: { [shotLabel]: avgShot, ios: avgIos },
  };
  writeFileSync(join(outDir, 'metrics.json'), JSON.stringify(metrics, null, 2) + '\n');
  if (!metricsOnly) {
    const [histShot, histIos] = await Promise.all([histogram(shotNorm), histogram(refNorm)]);
    writeFileSync(join(outDir, 'palette.txt'),
      `# ${item.case}\n\n## Average\n${shotLabel}: ${metrics.average[shotLabel]}\nios:    ${metrics.average.ios}\n\n` +
      `## ${shotLabel} dominant colors\n${histShot}\n\n## iOS dominant colors\n${histIos}\n`);
  }
  await artifacts;
  return metrics;
}

/**
 * Run the per-case parity audit for every ref-bearing manifest case
 * (optionally filtered by `only` substring). Writes per-case artifacts under
 * outDir/<case>/ and an aggregate outDir/summary.json.
 */
export async function runParityAudit({ parity, shotsDir, outDir, repoRoot, shotLabel, only = null, metricsOnly = false, nowMs }) {
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

  console.error(`auditing ${cases.length} cases  (concurrency ${CONCURRENCY}${metricsOnly ? ', metrics-only' : ''})`);
  const tick = makeProgress(cases.length, 'measured', nowMs);
  // Fan out across cores with bounded concurrency; results keep manifest order.
  // The progress tick (elapsed/eta/rate) fires on every completion so the run is
  // never silent. Per-case RMSE/MAE/SSIM is still printed for the audit record —
  // MEASURED, not judged; parity-verdict.mjs decides pass/fail vs the baseline.
  const summary = await pmap(
    cases,
    CONCURRENCY,
    (item) => auditCase(item, { shotsDir, outRoot: outDir, catalogRoot, shotLabel, metricsOnly }),
    (done, total, item, result) => {
      const r = result.rmse.normalized ?? result.rmse.value;
      const m = result.mae.normalized ?? result.mae.value;
      const s = result.ssim.normalized ?? result.ssim.value;
      tick(done, total, item, `· ${item.case}  RMSE=${r} MAE=${m} SSIM=${s}`);
    },
  );

  writeFileSync(join(outDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  console.error(`\nAudit artifacts: ${outDir}/<case>/{${metricsOnly ? 'metrics' : 'diff,zoom,palette,metrics'}}`);
  console.error(`Summary: ${outDir}/summary.json  (measured, not judged — run the verdict gate for pass/fail)`);
  return summary;
}
