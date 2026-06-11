/**
 * shots.mjs — capture every web parity case in headless Chromium.
 *
 * Builds web/ (skippable with --no-build when dist/ is fresh), serves dist/
 * via `vite preview`, then screenshots the 393×852 phone frame at
 * deviceScaleFactor 3 → 1179×2556, the same dims as iOS Catalog snapshot
 * PNGs. Case list + harness URL params come from parity-manifest.mjs.
 *
 * Usage:  node tools/shots.mjs [--no-build]
 * Output: web/tools/shots/<case>.png  (git-ignored, regenerable)
 */

import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';
import { PARITY } from './parity-manifest.mjs';

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = join(WEB_DIR, 'tools', 'shots');
const PORT = 4179;
const NO_BUILD = process.argv.includes('--no-build');

function build() {
  console.error('building web/ …');
  execFileSync('npm', ['run', 'build'], { cwd: WEB_DIR, stdio: ['ignore', 'ignore', 'inherit'] });
}

async function waitForServer(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`preview server did not come up at ${url}`);
}

async function main() {
  if (!NO_BUILD) build();
  mkdirSync(SHOTS, { recursive: true });

  // spawn the vite binary directly — an npx/npm wrapper doesn't reliably
  // forward SIGTERM, leaving a zombie server holding the strict port.
  const server = spawn(join(WEB_DIR, 'node_modules', '.bin', 'vite'),
    ['preview', '--port', String(PORT), '--strictPort'], {
      cwd: WEB_DIR,
      stdio: 'ignore',
    });
  try {
    // vite preview binds the IPv6 loopback; `localhost` resolves to it, 127.0.0.1 does not.
    const base = `http://localhost:${PORT}`;
    await waitForServer(base);

    const browser = await chromium.launch();
    try {
      for (const p of PARITY) {
        const page = await browser.newPage({
          viewport: { width: 393, height: 852 },
          deviceScaleFactor: 3,
        });
        const url = `${base}/?scenario=${p.params.scenario}&appearance=${p.params.appearance}`;
        await page.goto(url, { waitUntil: 'networkidle' });
        // woff2 faces must be live before capture, or text falls back mid-shot.
        await page.evaluate(() => document.fonts.ready);
        await page.locator('[data-harness="phone-frame"]').screenshot({
          path: join(SHOTS, `${p.case}.png`),
        });
        await page.close();
        console.error(`✓ ${p.case}`);
      }
    } finally {
      await browser.close();
    }
  } finally {
    server.kill();
  }
  console.error(`\nShots: ${SHOTS}/<case>.png`);
}

await main();
