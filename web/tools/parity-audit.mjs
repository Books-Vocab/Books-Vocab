/**
 * Per-case web ⟷ iOS visual parity audit — web-app wrapper around the shared
 * parity engine (design-system/parity/parity-core.mjs).
 *
 * Drill-down companion to compare.mjs; artifacts per case under tools/audit/:
 * diff.png (pixel-difference heatmap), zoom.png (enlarged crop strips),
 * palette.txt (dominant + average colors), metrics.json (RMSE/MAE/SSIM/PHASH)
 * and an aggregate summary.json.
 *
 * Usage:  node tools/parity-audit.mjs [--only <case-substring>] [--metrics-only]
 *   --metrics-only  skip diagnostic imagery (diff/zoom/palette/phash); compute
 *                   only the gated metrics (rmse/mae/ssim) + summary.json. ~4×
 *                   faster — the numbers are identical, only human-read artifacts
 *                   are dropped. Use for bless/check; use full audit to drill in.
 * Env:    KG_CATALOG_ROOT  catalog snapshot root override (default: newest
 *         usable build/snapshots/catalog-full-<UTC> — see ios-ref.mjs)
 */

import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PARITY } from './parity-manifest.mjs';
import { runParityAudit } from '../../design-system/parity/parity-core.mjs';

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const onlyIdx = process.argv.indexOf('--only');

await runParityAudit({
  parity: PARITY,
  shotsDir: join(WEB_DIR, 'tools', 'shots'),
  outDir: join(WEB_DIR, 'tools', 'audit'),
  repoRoot: resolve(WEB_DIR, '..'),
  shotLabel: 'web',
  only: onlyIdx >= 0 ? process.argv[onlyIdx + 1] : null,
  metricsOnly: process.argv.includes('--metrics-only'),
});
