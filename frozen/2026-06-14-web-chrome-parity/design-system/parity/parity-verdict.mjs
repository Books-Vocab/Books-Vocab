/**
 * parity-verdict.mjs — the honest PASS/FAIL layer over the measurement engine.
 *
 * parity-core.runParityAudit MEASURES (RMSE/MAE/SSIM/PHASH) and writes
 * summary.json. Its per-case "·" line means "an artifact was produced" — NOT
 * "this case passed". There was no verdict at all: 67 numbers, no threshold,
 * exit 0 regardless. That is fake-green. This module supplies the verdict.
 *
 * Model — per-case baseline regression + an absolute admission ceiling, the
 * standard visual-regression contract (reg-suit / snapshot-accept), chosen over
 * a single global threshold because each case has its own legitimate floor
 * (a dense list vs a sparse sheet diff at different RMSE and both are "right"):
 *
 *   - A case WITH a committed baseline is judged against ITSELF: it REGRESSES
 *     only if a metric drifts worse than baseline ± tolerance (tolerance
 *     absorbs run-to-run antialiasing jitter). Improvement is always a pass.
 *   - A case WITHOUT a baseline (brand new) must clear an absolute CEILING to
 *     be admissible (`new-ok`, flagged for blessing). Above the ceiling it is
 *     `new-fail` — you cannot bless garbage into the baseline. The ceiling is
 *     deliberately loose ("not garbage", not "good"); the baseline does the
 *     fine-grained work once a case is blessed.
 *   - A baseline case ABSENT from the run is `missing` — a silent drop is a
 *     fail, not a pass.
 *
 * Anti-Goodhart: the two gates pull opposite ways. Baseline-regression stops
 * quality from sliding; the ceiling stops a bad first capture from setting a
 * permanently-lax baseline. Neither can be satisfied by gaming the other.
 *
 * Pure core (computeVerdict) + thin CLI. Run via ops/web_parity.sh --check, or:
 *   node design-system/parity/parity-verdict.mjs [--summary P] [--baseline P]
 *        [--check] [--update] [--json]
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_BASELINE = join(HERE, 'parity-baseline.json');

// NOTE on the "ssim" field: ImageMagick 7.1.2's `compare -metric SSIM` reports
// 0 for identical images and grows with difference (white-vs-black ≈ 0.5) — it
// is effectively a structural DISTANCE (DSSIM), NOT classic SSIM (1=identical).
// So all three metrics here point the SAME way: 0 = identical, higher = worse.
// The verdict logic treats ssim as a distance accordingly (verified empirically,
// 2026-06-12; see the magick calibration in the commit message).

// Run-to-run jitter band (normalized 0..1). A change inside the band is noise,
// not a regression. RMSE/MAE jitter from antialiasing is small; ssim noisier.
export const DEFAULT_TOLERANCE = { rmse: 0.005, mae: 0.005, ssim: 0.01 };
// Admission ceiling for brand-new cases — a gross-failure floor, not a quality
// bar. All three are distances now, so "over ceiling" = too far from the iOS
// ref. Calibrated 2026-06-12 from the real distribution of the 67 human-accepted
// cases (worst accepted: RMSE 0.181, MAE 0.058, ssim 0.127) — each ceiling sits
// at ~1.5× the worst accepted value, leaving headroom for a legitimately
// imperfect new render while staying far below a wrong-layout case (white-vs-
// black benchmarks RMSE≈1.0 / ssim≈0.5, so garbage clears these by 2-4×). rmse
// and ssim are REQUIRED to be measured for a new case to be admissible (an
// unreadable metric is not "within ceiling"); mae gated only when present.
export const DEFAULT_CEILINGS = { rmse: 0.25, mae: 0.12, ssim: 0.2 };
const GATEABLE = ['rmse', 'ssim']; // must be present for a new case to be admissible

/** Normalized metric value, mirroring runParityAudit's `.normalized ?? .value`. */
function val(m) {
  if (m == null) return null;
  return m.normalized ?? m.value ?? null;
}

/**
 * Judge a freshly-measured summary against a committed baseline.
 *
 * @param {object}  cfg
 * @param {Array}   cfg.summary    parity-core summary.json entries (per case)
 * @param {object}  cfg.baseline   { cases: { <case>: {rmse,mae,ssim} } }
 * @param {object} [cfg.tolerance] regression band (default DEFAULT_TOLERANCE)
 * @param {object} [cfg.ceilings]  new-case admission ceiling (default DEFAULT_CEILINGS)
 * @returns {{ok, cases, counts, toBless}}
 */
export function computeVerdict({ summary, baseline, tolerance = DEFAULT_TOLERANCE, ceilings = DEFAULT_CEILINGS }) {
  const baseCases = (baseline && baseline.cases) || {};
  const seen = new Set();
  const cases = [];
  const toBless = [];

  for (const entry of summary) {
    const name = entry.case;
    seen.add(name);
    const cur = { rmse: val(entry.rmse), mae: val(entry.mae), ssim: val(entry.ssim) };
    const b = baseCases[name];

    if (b) {
      const reasons = [];
      // A metric present in the baseline but absent (unparsed/failed) in this run
      // is a fail, not a pass — a measurement that didn't happen must never read
      // green. This is the null-cur hole the regression guards would silently skip.
      for (const k of ['rmse', 'mae', 'ssim']) {
        if (b[k] != null && cur[k] == null) reasons.push(`${k} missing in this run (baseline ${b[k]})`);
      }
      if (cur.rmse != null && b.rmse != null && cur.rmse > b.rmse + tolerance.rmse)
        reasons.push(`rmse ${cur.rmse} > baseline ${b.rmse} + ${tolerance.rmse}`);
      if (cur.mae != null && b.mae != null && cur.mae > b.mae + tolerance.mae)
        reasons.push(`mae ${cur.mae} > baseline ${b.mae} + ${tolerance.mae}`);
      if (cur.ssim != null && b.ssim != null && cur.ssim > b.ssim + tolerance.ssim)
        reasons.push(`ssim ${cur.ssim} > baseline ${b.ssim} + ${tolerance.ssim}`);
      cases.push({ case: name, status: reasons.length ? 'regressed' : 'pass', cur, baseline: b, reasons });
    } else {
      const reasons = [];
      // Gateable metrics must be MEASURED to admit a new case — "couldn't read it"
      // is not "within ceiling". Without this, a case with null rmse/ssim and a
      // huge mae would slip in as new-ok and be blessed with null metrics, which
      // then passes every future check forever.
      for (const k of GATEABLE) {
        if (cur[k] == null) reasons.push(`${k} not measured`);
      }
      if (cur.rmse != null && cur.rmse > ceilings.rmse)
        reasons.push(`rmse ${cur.rmse} > ceiling ${ceilings.rmse}`);
      if (cur.mae != null && cur.mae > ceilings.mae)
        reasons.push(`mae ${cur.mae} > ceiling ${ceilings.mae}`);
      if (cur.ssim != null && cur.ssim > ceilings.ssim)
        reasons.push(`ssim ${cur.ssim} > ceiling ${ceilings.ssim}`);
      if (reasons.length) {
        cases.push({ case: name, status: 'new-fail', cur, baseline: null, reasons });
      } else {
        cases.push({ case: name, status: 'new-ok', cur, baseline: null, reasons: [] });
        toBless.push(name);
      }
    }
  }

  // Baseline cases the run never produced — silent drop is a fail.
  for (const name of Object.keys(baseCases)) {
    if (!seen.has(name)) {
      cases.push({ case: name, status: 'missing', cur: null, baseline: baseCases[name], reasons: ['absent from this run'] });
    }
  }

  const counts = {};
  for (const c of cases) counts[c.status] = (counts[c.status] || 0) + 1;
  const ok = !cases.some((c) => c.status === 'regressed' || c.status === 'new-fail' || c.status === 'missing');
  return { ok, cases, counts, toBless };
}

/**
 * Build a baseline from a summary (the "bless current state" action) — but
 * ceiling-gated: an over-ceiling (garbage) case is REFUSED, never written. If
 * bless ignored the ceiling it would be the laundering path that defeats it —
 * capture garbage once, bless it, and the now-permissive baseline passes it
 * forever. So the same absolute floor that admits new cases also bounds what a
 * human can bless. Returns { cases, refused }.
 */
export function baselineFromSummary(summary, ceilings = DEFAULT_CEILINGS) {
  const cases = {};
  const refused = [];
  for (const e of summary) {
    const m = { rmse: val(e.rmse), mae: val(e.mae), ssim: val(e.ssim) };
    // Refuse the same things the new-case gate refuses: unmeasured gateable
    // metrics (a null baseline value would pass every future check) and
    // over-ceiling garbage. bless cannot be a path past the ceiling.
    const unmeasured = GATEABLE.some((k) => m[k] == null);
    const overCeiling =
      (m.rmse != null && m.rmse > ceilings.rmse) ||
      (m.mae != null && m.mae > ceilings.mae) ||
      (m.ssim != null && m.ssim > ceilings.ssim);
    if (unmeasured || overCeiling) { refused.push(e.case); continue; }
    cases[e.case] = m;
  }
  return { cases, refused };
}

// ----------------------------------------------------------------- CLI -----

function arg(flag) {
  const i = process.argv.indexOf(flag);
  return i >= 0 ? process.argv[i + 1] : null;
}
function has(flag) { return process.argv.includes(flag); }

function statusMark(s) {
  return { pass: '✓', 'new-ok': '＋', regressed: '✗', 'new-fail': '✗', missing: '∅' }[s] || '?';
}

function main() {
  const summaryPath = resolve(arg('--summary') || join(HERE, '..', '..', 'web', 'tools', 'audit', 'summary.json'));
  const baselinePath = resolve(arg('--baseline') || DEFAULT_BASELINE);

  if (!existsSync(summaryPath)) {
    console.error(`no summary at ${summaryPath} — run: ops/web_parity.sh --audit`);
    process.exit(2);
  }
  const summary = JSON.parse(readFileSync(summaryPath, 'utf8'));

  // --update (bless) rewrites the baseline check verifies, so running it with
  // --check in one invocation would launder any regression (check would verify
  // against the just-written baseline → always green). Refuse the combination.
  if (has('--update') && has('--check')) {
    console.error('--update and --check are mutually exclusive: bless rewrites the very baseline check verifies');
    process.exit(2);
  }

  if (has('--update')) {
    const { cases, refused } = baselineFromSummary(summary);
    writeFileSync(baselinePath, JSON.stringify({ cases }, null, 2) + '\n');
    console.error(`baseline blessed: ${Object.keys(cases).length} cases → ${baselinePath}`);
    if (refused.length) {
      console.error(`REFUSED ${refused.length} unmeasured/over-ceiling case(s) — not written: ${refused.join(', ')}`);
      console.error('(fix the render until it clears the ceiling with measurable metrics, then re-bless)');
      process.exit(3); // distinct from hard error (2) and clean bless (0): partial refusal
    }
    return;
  }

  const baseline = existsSync(baselinePath) ? JSON.parse(readFileSync(baselinePath, 'utf8')) : { cases: {} };
  const verdict = computeVerdict({ summary, baseline });

  if (has('--json')) { console.log(JSON.stringify(verdict, null, 2)); }
  else {
    for (const c of verdict.cases) {
      const tail = c.reasons.length ? `  — ${c.reasons.join('; ')}` : '';
      console.error(`${statusMark(c.status)} ${c.status.padEnd(9)} ${c.case}${tail}`);
    }
    const order = ['pass', 'new-ok', 'regressed', 'new-fail', 'missing'];
    const parts = order.filter((s) => verdict.counts[s]).map((s) => `${verdict.counts[s]} ${s}`);
    console.error(`\n${verdict.ok ? 'PASS' : 'FAIL'} — ${parts.join(', ')}`);
    if (verdict.toBless.length) console.error(`(${verdict.toBless.length} new case(s) within ceiling; bless with --update once reviewed)`);
  }

  if (has('--check') && !verdict.ok) process.exit(1);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
