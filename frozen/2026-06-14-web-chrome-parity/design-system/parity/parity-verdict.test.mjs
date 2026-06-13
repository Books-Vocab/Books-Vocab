/**
 * TDD for parity-verdict.mjs — the honest pass/fail layer over the measurement
 * engine. Run: node design-system/parity/parity-verdict.test.mjs
 *
 * The audit (parity-core.runParityAudit) only MEASURES (RMSE/MAE/SSIM); its "✓"
 * means "produced an artifact", not "passed". These tests pin the verdict model:
 *   - a case is judged against its OWN committed baseline (regression model),
 *     so the gate is per-case honest, not one brittle global threshold;
 *   - a brand-new case (no baseline) must clear an absolute CEILING to be
 *     admissible — you cannot bless garbage into the baseline;
 *   - a baseline case absent from the run is MISSING (a silent drop is a fail,
 *     not a pass).
 */

import { computeVerdict, baselineFromSummary } from './parity-verdict.mjs';

let passed = 0;
let failed = 0;
function check(name, cond) {
  if (cond) { passed++; console.log(`  ok  ${name}`); }
  else { failed++; console.error(`FAIL  ${name}`); }
}

// summary entries mirror parity-core's auditCase output shape (subset we read).
// NOTE: all three metrics are DISTANCES here (0=identical, higher=worse) — this
// magick's "SSIM" is really DSSIM. Tests use realistic distances (good ssim ≈
// 0.02, garbage ≈ 0.4).
const mk = (name, rmse, mae, ssim) => ({
  case: name,
  rmse: { value: rmse, normalized: rmse },
  mae: { value: mae, normalized: mae },
  ssim: { value: ssim, normalized: ssim },
});
const base = (rmse, mae, ssim) => ({ rmse, mae, ssim });

const TOL = { rmse: 0.005, mae: 0.005, ssim: 0.01 };
const CEIL = { rmse: 0.15, mae: 0.15, ssim: 0.15 };
const opts = { tolerance: TOL, ceilings: CEIL };

// 1. within tolerance → pass, aggregate ok
{
  const v = computeVerdict({
    summary: [mk('a', 0.02, 0.01, 0.02)],
    baseline: { cases: { a: base(0.018, 0.009, 0.018) } },
    ...opts,
  });
  const a = v.cases.find((c) => c.case === 'a');
  check('within-tolerance is pass', a.status === 'pass');
  check('within-tolerance aggregate ok', v.ok === true);
}

// 2. rmse regression beyond tolerance → regressed, not ok
{
  const v = computeVerdict({
    summary: [mk('a', 0.05, 0.01, 0.02)],
    baseline: { cases: { a: base(0.02, 0.009, 0.018) } },
    ...opts,
  });
  const a = v.cases.find((c) => c.case === 'a');
  check('rmse regression flagged', a.status === 'regressed');
  check('rmse regression names rmse', a.reasons.some((r) => r.includes('rmse')));
  check('rmse regression aggregate not ok', v.ok === false);
}

// 3. ssim distance grows beyond tolerance → regressed (higher distance = worse)
{
  const v = computeVerdict({
    summary: [mk('a', 0.02, 0.01, 0.06)],
    baseline: { cases: { a: base(0.02, 0.01, 0.02) } },
    ...opts,
  });
  const a = v.cases.find((c) => c.case === 'a');
  check('ssim distance growth flagged as regression', a.status === 'regressed');
  check('ssim regression names ssim', a.reasons.some((r) => r.includes('ssim')));
}

// 4. new case (no baseline) within ceiling → new-ok, aggregate still ok
{
  const v = computeVerdict({
    summary: [mk('fresh', 0.10, 0.05, 0.05)],
    baseline: { cases: {} },
    ...opts,
  });
  const f = v.cases.find((c) => c.case === 'fresh');
  check('new case within ceiling is new-ok', f.status === 'new-ok');
  check('new-ok keeps aggregate ok', v.ok === true);
  check('new-ok is flagged for blessing', v.toBless.includes('fresh'));
}

// 5. new case above ceiling → new-fail, not ok (can't bless garbage)
{
  const v = computeVerdict({
    summary: [mk('garbage', 0.30, 0.20, 0.40)],
    baseline: { cases: {} },
    ...opts,
  });
  const g = v.cases.find((c) => c.case === 'garbage');
  check('new case above ceiling is new-fail', g.status === 'new-fail');
  check('new-fail aggregate not ok', v.ok === false);
  check('new-fail NOT offered for blessing', !v.toBless.includes('garbage'));
}

// 6. baseline case absent from run → missing, not ok
{
  const v = computeVerdict({
    summary: [mk('a', 0.02, 0.01, 0.02)],
    baseline: { cases: { a: base(0.02, 0.01, 0.02), gone: base(0.01, 0.01, 0.01) } },
    ...opts,
  });
  const g = v.cases.find((c) => c.case === 'gone');
  check('missing baseline case detected', g && g.status === 'missing');
  check('missing aggregate not ok', v.ok === false);
}

// 7. improvement (metrics better than baseline) → pass, never regressed
{
  const v = computeVerdict({
    summary: [mk('a', 0.005, 0.002, 0.005)],
    baseline: { cases: { a: base(0.02, 0.01, 0.02) } },
    ...opts,
  });
  const a = v.cases.find((c) => c.case === 'a');
  check('improvement is pass', a.status === 'pass');
}

// 8. counts + summary shape are coherent
{
  const v = computeVerdict({
    summary: [mk('p', 0.02, 0.01, 0.02), mk('r', 0.09, 0.01, 0.02), mk('n', 0.10, 0.05, 0.05)],
    baseline: { cases: { p: base(0.02, 0.01, 0.02), r: base(0.02, 0.01, 0.02) } },
    ...opts,
  });
  check('counts.pass', v.counts.pass === 1);
  check('counts.regressed', v.counts.regressed === 1);
  check('counts.newOk', v.counts['new-ok'] === 1);
  check('total cases counted', v.cases.length === 3);
}

// 9. bless is ceiling-gated — over-ceiling garbage is REFUSED, never written.
//    Otherwise --bless would launder garbage past the ceiling, defeating it.
{
  const summary = [mk('good', 0.02, 0.01, 0.02), mk('garbage', 0.42, 0.2, 0.3)];
  const { cases, refused } = baselineFromSummary(summary, CEIL);
  check('bless writes admissible case', cases.good != null);
  check('bless refuses over-ceiling case', cases.garbage == null);
  check('bless reports refusal', refused.includes('garbage'));
}

// 10. CRITICAL-2: null current metric against a present baseline → fail, not pass.
//     A measurement that failed to parse must never report green.
{
  const v = computeVerdict({
    summary: [{ case: 'a', rmse: { value: null, normalized: null }, mae: { value: null, normalized: null }, ssim: { value: null, normalized: null } }],
    baseline: { cases: { a: base(0.02, 0.01, 0.98) } },
    ...opts,
  });
  const a = v.cases.find((c) => c.case === 'a');
  check('null cur vs present baseline is NOT pass', a.status !== 'pass');
  check('null cur vs present baseline aggregate not ok', v.ok === false);
}

// 11. CRITICAL-2b: new case with unmeasured gateable metric → new-fail, never blessable.
{
  const v = computeVerdict({
    summary: [{ case: 'n', rmse: { value: null, normalized: null }, mae: { value: 0.9, normalized: 0.9 }, ssim: { value: null, normalized: null } }],
    baseline: { cases: {} },
    ...opts,
  });
  const n = v.cases.find((c) => c.case === 'n');
  check('null-metric new case is new-fail', n.status === 'new-fail');
  check('null-metric new case not blessable', !v.toBless.includes('n'));
}

// 12. baselineFromSummary refuses null-metric case (would otherwise pass forever).
{
  const summary = [mk('good', 0.02, 0.01, 0.98), { case: 'null', rmse: { value: null, normalized: null }, mae: { value: null, normalized: null }, ssim: { value: null, normalized: null } }];
  const { cases, refused } = baselineFromSummary(summary, CEIL);
  check('bless refuses null-metric case', cases['null'] == null);
  check('bless reports null refusal', refused.includes('null'));
}

// 13. IMPORTANT-3: mae-only garbage new case (rmse/ssim absent, mae huge) → new-fail.
{
  const v = computeVerdict({
    summary: [{ case: 'm', rmse: { value: null, normalized: null }, mae: { value: 0.9, normalized: 0.9 }, ssim: { value: null, normalized: null } }],
    baseline: { cases: {} },
    ...opts,
  });
  check('mae-only garbage not admissible', v.cases.find((c) => c.case === 'm').status === 'new-fail');
}

// 14. mae regression direction is actually asserted (was implemented but untested).
{
  const v = computeVerdict({
    summary: [mk('a', 0.02, 0.09, 0.98)],
    baseline: { cases: { a: base(0.02, 0.01, 0.98) } },
    ...opts,
  });
  const a = v.cases.find((c) => c.case === 'a');
  check('mae regression flagged', a.status === 'regressed');
  check('mae regression names mae', a.reasons.some((r) => r.includes('mae')));
}

console.log(`\nparity-verdict: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
