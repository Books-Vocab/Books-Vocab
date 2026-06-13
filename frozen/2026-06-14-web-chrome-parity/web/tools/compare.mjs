/**
 * Visual-parity compositor — web-app wrapper around the shared parity engine
 * (design-system/parity/parity-core.mjs). Pairs each web shot (from
 * shots.mjs) with the iOS Catalog reference it should mirror, then tiles all
 * pairs into ONE contact sheet (tools/compare/contact.png).
 *
 * Usage:  node tools/compare.mjs
 * Env:    KG_CATALOG_ROOT  catalog snapshot root override (default: newest
 *         usable build/snapshots/catalog-full-<UTC> — see ios-ref.mjs)
 */

import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PARITY } from './parity-manifest.mjs';
import { composeContactSheet } from '../../design-system/parity/parity-core.mjs';

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');

await composeContactSheet({
  parity: PARITY,
  shotsDir: join(WEB_DIR, 'tools', 'shots'),
  outDir: join(WEB_DIR, 'tools', 'compare'),
  repoRoot: resolve(WEB_DIR, '..'),
  shotLabel: 'web',
});
