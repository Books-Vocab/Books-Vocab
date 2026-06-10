/**
 * ios-ref.mjs — resolve iOS reference PNGs from the Catalog snapshot system.
 *
 * Replaces the hand-shot ~/Desktop reference folder: the Catalog
 * (`./ops/ios_ops.sh catalog snapshots`) renders every declared surface at
 * 1179×2556 (same dims as our Chrome shots) into
 * build/snapshots/catalog-full-<UTC>/, with one PNG per scenario per
 * appearance. Parity refs address those PNGs by stable taxonomy
 * ({surface, scenario, appearance}) instead of by IMG_*.PNG filename, so the
 * reference set regenerates from source instead of going stale on a Desktop.
 *
 * Root selection: `catalog-full-*` dirs only (side artifacts like
 * gallery-admin-preview carry a usable manifest but not the full surface
 * set), usable (totalImages > 0), newest name wins — the timestamped naming
 * makes lexicographic order chronological. Override with KG_CATALOG_ROOT.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Catalog directory slugs — mirrors playbook-ui Snapshot's filename
 * normalization: `.`/`:`/`/`, whitespace, and control characters all become
 * `_` (observed: "Bare card (no links / progress)" →
 * "Bare_card_(no_links___progress).png"); everything else is kept.
 */
export function slugify(name) {
  return name.replace(/[.:/\s\p{Cc}]/gu, '_');
}

/**
 * Pick the catalog snapshot root: env override, else newest usable
 * build/snapshots/<name>/ (review_manifest.json with totalImages > 0).
 * Returns null when nothing usable exists.
 */
export function resolveCatalogRoot({ env = process.env, repoRoot } = {}) {
  if (env.KG_CATALOG_ROOT) return env.KG_CATALOG_ROOT;
  const snapshots = join(repoRoot, 'build', 'snapshots');
  if (!existsSync(snapshots)) return null;
  const usable = [];
  for (const entry of readdirSync(snapshots, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    // Only full catalog runs qualify — build/snapshots also hosts side
    // artifacts (e.g. gallery-admin-preview) that carry a usable manifest
    // but not the full surface set.
    if (!entry.name.startsWith('catalog-full-')) continue;
    const manifestPath = join(snapshots, entry.name, 'review_manifest.json');
    if (!existsSync(manifestPath)) continue;
    try {
      const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
      if ((manifest.totalImages ?? 0) > 0) usable.push(entry.name);
    } catch {
      // unreadable manifest = not a usable root
    }
  }
  if (usable.length === 0) return null;
  usable.sort();
  return join(snapshots, usable[usable.length - 1]);
}

function deviceDirs(root) {
  // The catalog is single-device by design (one iPhone, portrait, light+dark).
  // If a second device ever lands, the sorted-first pick below must grow an
  // explicit device selector instead.
  const dirs = readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
  const light = dirs.filter((name) => !name.endsWith(' (dark)')).sort()[0] ?? null;
  if (!light) return { light: null, dark: null };
  const dark = dirs.includes(`${light} (dark)`) ? `${light} (dark)` : null;
  return { light, dark };
}

/**
 * Resolve {surface, scenario, appearance} to an absolute PNG path inside the
 * catalog root, or null when the device dir / surface / scenario is missing.
 */
export function resolveRef(root, { surface, scenario, appearance = 'light' }) {
  if (!root || !existsSync(root)) return null;
  const { light, dark } = deviceDirs(root);
  const device = appearance === 'dark' ? dark : light;
  if (!device) return null;
  const png = join(root, device, slugify(surface), `${slugify(scenario)}.png`);
  return existsSync(png) ? png : null;
}
