/**
 * Chrome render smoke test (Layer 2 of ops/chrome_verify.sh).
 *
 * Loads the unpacked extension into the user's *existing* Chrome via
 * `--headless=new` (zero install — no Playwright/puppeteer), drives it over the
 * DevTools Protocol, opens each extension page, and asserts the initial
 * rendered state. Catches the whole class of bug that static lint and
 * node:test cannot: a CSS cascade that leaves a `hidden` element visible (the
 * opaque full-cover word-detail panel that froze the side panel), or a
 * top-level throw that white-screens a surface on load.
 *
 * Transport note: Chrome ≥126 disables `--load-extension` from the command line
 * in headless, and the programmatic `Extensions.loadUnpacked` CDP command is
 * only exposed over a `--remote-debugging-pipe` connection (NOT a TCP port). So
 * we speak CDP over the fd3/fd4 pipe rather than a WebSocket.
 *
 * Hard failures (exit 1):
 *   - any element carrying the `hidden` attribute whose computed display ≠ none
 *   - a page where the KG stylesheet never applied (wrong page / load failure)
 *   - any uncaught exception thrown while a page loads
 *   - a page that never reaches readyState 'complete'
 *
 * Network/console errors (e.g. the API being unreachable in this sandbox) are
 * reported but do NOT fail the run — this is a *startup* smoke test.
 *
 * Usage:  node tools/smoke.mjs [--verbose]
 * Env:    CHROME_BIN  override the Chrome/Chromium binary path
 */

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const EXT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VERBOSE = process.argv.includes('--verbose');
const log = (...a) => VERBOSE && console.error('[smoke]', ...a);

// Extension pages to render, resolved against chrome-extension://<id>/.
const PAGES = ['sidepanel/index.html', 'options/options.html'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const withTimeout = (p, ms, label) =>
  Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout: ' + label)), ms))]);

function findChrome() {
  const candidates = [
    process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  throw new Error('Chrome binary not found — set CHROME_BIN');
}

// Deterministic unpacked-extension id (fallback only): first 32 hex nibbles of
// SHA-256(absolute path), each mapped 0-f → a-p. Normally we use the id that
// Extensions.loadUnpacked returns.
function computeExtensionId(absPath) {
  const hex = createHash('sha256').update(absPath).digest('hex');
  let id = '';
  for (let i = 0; i < 32; i++) id += String.fromCharCode(97 + parseInt(hex[i], 16));
  return id;
}

// Evaluated inside each page once it has settled. The core assertion: every
// [hidden] element must compute to display:none (else a class beat the
// attribute — this bug). `tokenLoaded` proves the KG stylesheet really applied,
// so a wrong-page/chrome-error never passes as a false green.
const ASSERT_JS = `(() => {
  const bad = [];
  for (const el of document.querySelectorAll('[hidden]')) {
    const cs = getComputedStyle(el);
    if (cs.display !== 'none') {
      bad.push({
        id: el.id || null,
        cls: (typeof el.className === 'string' ? el.className : null),
        tag: el.tagName,
        display: cs.display,
        position: cs.position,
      });
    }
  }
  const sd = document.getElementById('stateDetail');
  const sdCs = sd ? getComputedStyle(sd) : null;
  const pageBg = getComputedStyle(document.documentElement).getPropertyValue('--page-bg').trim();
  return {
    hiddenButVisible: bad,
    readyState: document.readyState,
    bodyTextLen: (document.body && document.body.innerText || '').trim().length,
    tokenLoaded: pageBg.length > 0,
    _diag: {
      pageBg,
      detailExists: !!sd,
      detailDisplay: sdCs ? sdCs.display : null,
      detailPosition: sdCs ? sdCs.position : null,
      sheets: [...document.styleSheets].map((s) => (s.href || 'inline').split('/').pop()),
      hiddenCount: document.querySelectorAll('[hidden]').length,
    },
  };
})()`;

// -------------------------------------------------------------------------
// CDP over the --remote-debugging-pipe transport (fd3 write, fd4 read).
// Messages are NUL-delimited JSON. Supports flatten sessions via sessionId.
// -------------------------------------------------------------------------
class CDP {
  constructor(proc) {
    this.wr = proc.stdio[3]; // we write → Chrome reads on fd3
    this.rd = proc.stdio[4]; // Chrome writes on fd4 → we read
    this.seq = 0;
    this.pending = new Map();
    this.listeners = new Set();
    this._buf = '';
    this.rd.on('data', (chunk) => this._onData(chunk));
  }
  _onData(chunk) {
    this._buf += chunk.toString('utf8');
    let i;
    while ((i = this._buf.indexOf('\0')) >= 0) {
      const raw = this._buf.slice(0, i);
      this._buf = this._buf.slice(i + 1);
      if (raw) this._dispatch(raw);
    }
  }
  _dispatch(raw) {
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }
    if (msg.id !== undefined) {
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(new Error(`${msg.error.message} (${p.method})`));
      else p.resolve(msg.result);
    } else {
      for (const fn of this.listeners) fn(msg);
    }
  }
  send(method, params = {}, sessionId) {
    const id = ++this.seq;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    this.wr.write(JSON.stringify(msg) + '\0');
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject, method }));
  }
  on(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}

async function waitReady(cdp, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await withTimeout(cdp.send('Browser.getVersion'), 800, 'getVersion');
      return;
    } catch {
      await sleep(120);
    }
  }
  throw new Error('Chrome CDP pipe never became ready');
}

async function checkPage(cdp, extId, relPath) {
  const url = `chrome-extension://${extId}/${relPath}`;
  const errors = [];
  const consoleErrors = [];

  const { targetId } = await cdp.send('Target.createTarget', { url });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });

  const off = cdp.on((m) => {
    if (m.sessionId !== sessionId) return;
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errors.push(d.exception?.description || d.text || 'uncaught exception');
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? a.type).join(' '));
    }
  });

  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Page.enable', {}, sessionId);

  let ready = false;
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    const r = await cdp.send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true }, sessionId);
    if (r.result.value === 'complete') { ready = true; break; }
    await sleep(150);
  }
  await sleep(600); // let app.js run its initial render after DOMContentLoaded

  const evalRes = await cdp.send(
    'Runtime.evaluate',
    { expression: ASSERT_JS, returnByValue: true },
    sessionId
  );
  const verdict = evalRes.result.value || {};

  off();
  await cdp.send('Target.closeTarget', { targetId });
  return { relPath, url, ready, verdict, errors, consoleErrors };
}

async function main() {
  const chrome = findChrome();
  log('chrome:', chrome);
  const userDataDir = await mkdtemp(join(tmpdir(), 'kg-smoke-'));
  const args = [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-features=Translate,OptimizationHints',
    '--enable-unsafe-extension-debugging', // unlocks Extensions.loadUnpacked
    `--user-data-dir=${userDataDir}`,
    '--remote-debugging-pipe',
    'about:blank',
  ];
  const proc = spawn(chrome, args, { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  let stderr = '';
  proc.stderr.on('data', (d) => { stderr += d.toString(); });

  let failed = false;
  try {
    const cdp = new CDP(proc);
    await waitReady(cdp);

    let extId;
    try {
      const r = await withTimeout(cdp.send('Extensions.loadUnpacked', { path: EXT_DIR }), 8000, 'loadUnpacked');
      extId = r.id;
      log('loaded via Extensions.loadUnpacked:', extId);
    } catch (e) {
      log('Extensions.loadUnpacked failed:', e.message, '— falling back to path-based id');
      extId = computeExtensionId(EXT_DIR);
    }
    await sleep(400);

    for (const relPath of PAGES) {
      const r = await checkPage(cdp, extId, relPath);
      const problems = [];
      if (!r.ready) problems.push('page never reached readyState=complete');
      if (!r.verdict.tokenLoaded) {
        problems.push('KG stylesheet not applied — wrong page or extension failed to load (no --page-bg token)');
      }
      if (r.errors.length) problems.push(...r.errors.map((e) => 'uncaught: ' + e));
      for (const b of r.verdict.hiddenButVisible || []) {
        problems.push(`[hidden] element visible: #${b.id || b.cls || b.tag} → display:${b.display} position:${b.position}`);
      }

      if (problems.length) {
        failed = true;
        console.error(`✗ ${r.relPath}`);
        for (const p of problems) console.error(`    ✗ ${p}`);
      } else {
        console.error(`✓ ${r.relPath}  (readyState=${r.verdict.readyState}, ${r.verdict.bodyTextLen} chars visible)`);
      }
      if (VERBOSE) console.error('    diag:', JSON.stringify(r.verdict._diag));
      for (const c of r.consoleErrors) console.error(`    · console.error (non-fatal): ${c}`);
    }
  } catch (e) {
    failed = true;
    console.error('smoke harness error:', e.message);
    if (VERBOSE && stderr) console.error('[chrome stderr]\n' + stderr.split('\n').slice(-20).join('\n'));
  } finally {
    proc.kill('SIGKILL');
    await rm(userDataDir, { recursive: true, force: true }).catch(() => {});
  }

  if (failed) {
    console.error('\nSMOKE FAILED — a surface renders incorrectly on load.');
    process.exit(1);
  }
  console.error('\nSMOKE PASSED — all surfaces render a correct initial state.');
}

main().catch((e) => {
  console.error('smoke error:', e.message);
  process.exit(2);
});
