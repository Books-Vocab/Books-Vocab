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

async function main() {
  if (!NO_BUILD) build();
  mkdirSync(SHOTS, { recursive: true });

  // Probe a free port so parallel worktree runs never collide.
  // SHOTS_PORT env var allows manual override (e.g. for debugging).
  const port = process.env.SHOTS_PORT
    ? Number(process.env.SHOTS_PORT)
    : await getFreePort();

  // spawn the vite binary directly — an npx/npm wrapper doesn't reliably
  // forward SIGTERM, leaving a zombie server holding the strict port.
  const server = spawn(join(WEB_DIR, 'node_modules', '.bin', 'vite'),
    ['preview', '--port', String(port), '--strictPort'], {
      cwd: WEB_DIR,
      stdio: 'ignore',
    });
  try {
    // vite preview binds the IPv6 loopback; `localhost` resolves to it, 127.0.0.1 does not.
    const base = `http://localhost:${port}`;
    await waitForServer(base);

    const browser = await chromium.launch();
    try {
      for (const p of PARITY) {
        // Use a fresh BrowserContext per case so Playwright tears down all TCP
        // sockets to the vite preview server on context.close().  Reusing a
        // single context (or just calling page.close()) leaves keep-alive
        // connections open in the server's socket pool; after ~9 cases the pool
        // fills and new connections get ECONNREFUSED.
        const ctx = await browser.newContext({
          viewport: { width: 393, height: 852 },
          deviceScaleFactor: 3,
        });
        try {
          const page = await ctx.newPage();
          // params 逐鍵序列化（surface 可省略 = bookshelf 向後相容預設）
          const qs = new URLSearchParams(p.params).toString();
          const url = `${base}/?${qs}`;
          // 'load' is sufficient and avoids the long networkidle polling window
          // that compounds with accumulated keep-alive sockets.
          await page.goto(url, { waitUntil: 'load' });
          // woff2 faces must be live before capture, or text falls back mid-shot.
          await page.evaluate(() => document.fonts.ready);
          await page.locator('[data-harness="phone-frame"]').screenshot({
            path: join(SHOTS, `${p.case}.png`),
          });
        } finally {
          // context.close() drains all sockets for this context immediately,
          // keeping the server connection count bounded across all cases.
          await ctx.close();
        }
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
