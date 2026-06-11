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
import { createServer } from 'node:net';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';
import { PARITY } from './parity-manifest.mjs';

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = join(WEB_DIR, 'tools', 'shots');
const NO_BUILD = process.argv.includes('--no-build');
// Optional `--only <substr>` filter: capture only cases whose name contains the
// substring. Lets you iterate on one surface without shooting the whole set.
const ONLY = (() => {
  const i = process.argv.indexOf('--only');
  return i >= 0 ? process.argv[i + 1] : null;
})();

/** Ask the OS for a free TCP port, then immediately release it. */
function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close((err) => (err ? reject(err) : resolve(port)));
    });
    srv.on('error', reject);
  });
}

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

function spawnServer(port) {
  // spawn the vite binary directly — an npx/npm wrapper doesn't reliably
  // forward SIGTERM, leaving a zombie server holding the strict port.
  return spawn(join(WEB_DIR, 'node_modules', '.bin', 'vite'),
    ['preview', '--port', String(port), '--strictPort'], {
      cwd: WEB_DIR,
      stdio: 'ignore',
    });
}

async function main() {
  if (!NO_BUILD) build();
  mkdirSync(SHOTS, { recursive: true });

  const cases = ONLY ? PARITY.filter((p) => p.case.includes(ONLY)) : PARITY;
  if (cases.length === 0) throw new Error(`--only "${ONLY}" matched no cases`);

  // Probe a free port so parallel worktree runs never collide.
  // SHOTS_PORT env var allows manual override (e.g. for debugging).
  const port = process.env.SHOTS_PORT
    ? Number(process.env.SHOTS_PORT)
    : await getFreePort();
  // vite preview binds the IPv6 loopback; `localhost` resolves to it, 127.0.0.1 does not.
  const BASE = `http://localhost:${port}`;

  // `vite preview` occasionally dies mid-run on large dist sets (observed:
  // ERR_CONNECTION_REFUSED after ~12 shots). Re-spawn on demand so a crash
  // costs one retry, not the whole run.
  let server = spawnServer(port);
  await waitForServer(BASE);

  async function ensureServer() {
    try {
      const res = await fetch(BASE);
      if (res.ok) return;
    } catch {
      // fall through to relaunch
    }
    try { server.kill(); } catch { /* already gone */ }
    server = spawnServer(port);
    await waitForServer(BASE);
  }

  try {
    const browser = await chromium.launch();
    try {
      for (const p of cases) {
        // params 逐鍵序列化（surface 可省略 = bookshelf 向後相容預設）
        const qs = new URLSearchParams(p.params).toString();
        const url = `${BASE}/?${qs}`;
        let lastErr;
        for (let attempt = 0; attempt < 3; attempt++) {
          const page = await browser.newPage({
            viewport: { width: 393, height: 852 },
            deviceScaleFactor: 3,
          });
          try {
            await page.goto(url, { waitUntil: 'networkidle' });
            // woff2 faces must be live before capture, or text falls back mid-shot.
            await page.evaluate(() => document.fonts.ready);
            await page.locator('[data-harness="phone-frame"]').screenshot({
              path: join(SHOTS, `${p.case}.png`),
            });
            await page.close();
            lastErr = null;
            break;
          } catch (err) {
            lastErr = err;
            await page.close().catch(() => {});
            await ensureServer();
          }
        }
        if (lastErr) throw lastErr;
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
