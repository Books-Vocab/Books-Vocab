/**
 * Chrome surface screenshotter — renders each UI *case* of the extension into a
 * PNG, so they can be diffed against the iOS reference shots (see compare.mjs).
 *
 * It reuses the smoke-test transport (real system Chrome, `--headless=new`,
 * CDP over `--remote-debugging-pipe`, `Extensions.loadUnpacked` — zero install)
 * but instead of asserting load-correctness it DRIVES each surface into a target
 * state and captures it:
 *
 *   - the device metrics are overridden to 393×852 @3x — the iPhone logical
 *     viewport at @3x — so every shot lands at 1179×2556, pixel-identical in
 *     dimensions to the iOS reference PNGs (clean side-by-side, no rescale).
 *   - the vocab list / detail / settings are populated from an in-page MOCK so
 *     the content + detail + settings states render WITHOUT a backend. The mock
 *     is fed through the app's own normalize → enrich → render path (no
 *     hand-authored markup that could drift from the real card template).
 *
 * Output: tools/shots/<case>.png  (git-ignored — they are regenerable artifacts)
 *
 * Usage:  node tools/shots.mjs [--verbose] [--only <case-substring>]
 * Env:    CHROME_BIN  override the Chrome/Chromium binary path
 */

import { spawn } from 'node:child_process';
import { mkdtemp, rm, mkdir, writeFile, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const EXT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = join(EXT_DIR, 'tools', 'shots');
const VERBOSE = process.argv.includes('--verbose');
const onlyIdx = process.argv.indexOf('--only');
const ONLY = onlyIdx >= 0 ? process.argv[onlyIdx + 1] : null;
const log = (...a) => VERBOSE && console.error('[shots]', ...a);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const withTimeout = (p, ms, label) =>
  Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout: ' + label)), ms))]);

// -------------------------------------------------------------------------
// Mock vocab — raw payload shape (pre-normalizeVocabItem). Mirrors the fields
// the iOS catalog references show: a varied review-state list (Vocabulary List
// View) and a rich detail document with example / 搭配 / 變化形 / 知識連結
// (Word Detail Presenter).
// Timestamps are relative to now so the review chips + row progress vary.
// -------------------------------------------------------------------------
const HOUR = 3600e3;
const now = Date.now();
const iso = (deltaH) => new Date(now + deltaH * HOUR).toISOString();
const MOCK_VOCAB = [
  {
    id: 'c1', content: 'lascivious', pos: 'adj.', difficulty_tier: 'C1',
    meaning: '好色的；淫蕩的',
    note: '帶有明顯性意味的；表現出強烈情慾的。多用於描述眼神、言語或舉止。',
    context_sentence: 'He cast a lascivious glance across the crowded room.',
    examples: [{ sentence: 'Her *lascivious* remarks made everyone uncomfortable.' }],
    collocations: [{ word: 'lascivious glance' }, { word: 'lascivious smile' }],
    inflections: ['lasciviously', 'lasciviousness'],
    linksByKind: {
      contrast: [{ label: '對比', reason: '同樣形容情慾，但 lewd 更粗俗直接', cardId: 'c2' }],
      related: [{ label: '相關', reason: '常一同出現的慾望語境詞', cardId: 'c3' }],
    },
    reviewCount: 3, reviewIntervalHours: 48, nextReviewAt: iso(-6), updatedAt: iso(-2),
  },
  { id: 'c2', content: 'lewd', pos: 'adj.', meaning: '猥褻的；下流的',
    context_sentence: 'lewd jokes', reviewCount: 1, reviewIntervalHours: 12,
    nextReviewAt: iso(8), updatedAt: iso(-30), difficulty_tier: 'B2' },
  { id: 'c3', content: 'hors d’oeuvres', pos: 'n.', meaning: '開胃小菜；前菜',
    reviewCount: 0, nextReviewAt: null, updatedAt: iso(-1), difficulty_tier: 'C1' },
  { id: 'c4', content: 'forestall', pos: 'v.', meaning: '預先阻止；先發制人',
    reviewCount: 8, reviewIntervalHours: 168, nextReviewAt: iso(120), updatedAt: iso(-200),
    difficulty_tier: 'C2' },
  { id: 'c5', content: 'daft', pos: 'adj.', meaning: '愚蠢的；傻氣的',
    reviewCount: 2, reviewIntervalHours: 24, nextReviewAt: iso(-2), updatedAt: iso(-50),
    difficulty_tier: 'B1' },
  { id: 'c6', content: 'obliviousness', pos: 'n.', meaning: '渾然不覺；茫然無知',
    reviewCount: 5, reviewIntervalHours: 72, nextReviewAt: iso(48), updatedAt: iso(-90),
    difficulty_tier: 'C1' },
];
// (options account/Pro state is driven by calling renderLoggedIn() /
// renderProStatus({...}) directly in the case expr, so no mock config payload
// is needed here.)

// -------------------------------------------------------------------------
// Case list. Each drives a page into one state via an injected expression that
// calls the app's own global render functions (app.js is a classic <script>, so
// its top-level functions + `let vocabData` live in the page's global scope and
// are reachable from Runtime.evaluate).
// -------------------------------------------------------------------------
const SP = 'sidepanel/index.html';
const seedList = (theme) =>
  `applyTheme(document.documentElement, '${theme}');` +
  `vocabData = ${JSON.stringify(MOCK_VOCAB)}.map(o => enrichWithReviewData(KGPure.normalizeVocabItem(o)));`;
const failedOutboxExpr =
  `pendingSyncItems=[decoratePendingItem(KGPure.normalizeVocabItem({` +
  `id:'local-failed-1',content:'chiaroscuro',pos:'n.',meaning:'明暗對照；明暗法',` +
  `context_sentence:'The painting used chiaroscuro to give the scene depth.'` +
  `}),{syncState:'failed'})];`;

const CASES = [
  { name: 'sidepanel-content-light', page: SP, expr: seedList('light') + `setState('content'); applyView();` },
  {
    name: 'content-popup-notebook-light',
    page: 'tools/content-popup-harness.html',
    kind: 'contentPopup',
  },
  {
    name: 'sidepanel-outbox-failed-light',
    page: SP,
    expr: seedList('light') + failedOutboxExpr + `setState('content'); applyView();`,
  },
  {
    name: 'sidepanel-notebook-sheet-light',
    page: SP,
    expr: seedList('light') + `setState('content'); applyView(); openNotebookSheet('create'); notebookNameInput.value='閱讀筆記'; notebookDraftColor='#C5B2D0'; notebookDraftPattern='grid'; renderNotebookAppearanceControls();`,
  },
  { name: 'sidepanel-content-dark', page: SP, expr: seedList('dark') + `setState('content'); applyView();` },
  { name: 'sidepanel-content-sepia', page: SP, expr: seedList('sepia') + `setState('content'); applyView();` },
  { name: 'sidepanel-detail-light', page: SP, expr: seedList('light') + `setState('content'); applyView(); openDetail(vocabData[0]);` },
  { name: 'sidepanel-empty-light', page: SP, expr: `applyTheme(document.documentElement,'light'); vocabData=[]; setState('empty');` },
  {
    name: 'sidepanel-error-light', page: SP,
    expr: `applyTheme(document.documentElement,'light'); showErrorFromResponse({error:true,code:'network_error',message:'無法連線到伺服器，請稍後再試。'});`,
  },
  {
    name: 'options-settings-light', page: 'options/options.html',
    expr: `applyTheme(document.documentElement,'light'); renderLoggedIn(); renderProStatus({is_active:true, plan_name:'年費方案'});`,
  },
];

// -------------------------------------------------------------------------
// CDP over the --remote-debugging-pipe transport (fd3 write, fd4 read), NUL
// framed. Same transport smoke.mjs uses; kept self-contained so the two tools
// don't couple.
// -------------------------------------------------------------------------
class CDP {
  constructor(proc) {
    this.wr = proc.stdio[3];
    this.rd = proc.stdio[4];
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
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
}

async function waitReady(cdp, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { await withTimeout(cdp.send('Browser.getVersion'), 800, 'getVersion'); return; }
    catch { await sleep(120); }
  }
  throw new Error('Chrome CDP pipe never became ready');
}

function findChrome() {
  const candidates = [
    process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  throw new Error('Chrome binary not found — set CHROME_BIN');
}

// Render one case into a PNG. Returns { name, ok, tokenLoaded, error }.
async function shoot(cdp, extId, c) {
  const url = `chrome-extension://${extId}/${c.page}`;
  const { targetId } = await cdp.send('Target.createTarget', { url });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });

  const errors = [];
  const off = cdp.on((m) => {
    if (m.sessionId !== sessionId) return;
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errors.push(d.exception?.description || d.text || 'uncaught');
    }
  });

  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Page.enable', {}, sessionId);
  // iPhone logical viewport @3x → 1179×2556, matching the iOS reference PNGs.
  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: 393, height: 852, deviceScaleFactor: 3, mobile: false }, sessionId);

  // Wait for the page's own initial render to settle before we override it.
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    const r = await cdp.send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true }, sessionId);
    if (r.result.value === 'complete') break;
    await sleep(120);
  }
  await sleep(400);

  if (c.kind === 'contentPopup') {
    await driveContentPopupCase(cdp, sessionId, extId);
  }

  // Drive the surface into its target state, then read back the proof token.
  const driveExpr = c.kind === 'contentPopup'
    ? `(() => {
      const host = document.getElementById('kg-popup-host');
      return {
        tokenLoaded: !!host,
        theme: 'light',
        bg: '#f5f4f2',
        diag: {
          host: !!host,
          opened: !!window.__kgShotPopupOpened,
          body: document.body.innerText.slice(0, 120),
        },
      };
    })()`
    : `(() => { ${c.expr};
      const bg = getComputedStyle(document.documentElement).getPropertyValue('--page-bg').trim();
      const theme = document.documentElement.getAttribute('data-theme');
      return { tokenLoaded: bg.length > 0, theme, bg }; })()`;
  const drive = await cdp.send('Runtime.evaluate', {
    expression: driveExpr,
    returnByValue: true,
  }, sessionId);
  const verdict = drive.result.value || {};
  if (c.kind === 'contentPopup' && !verdict.tokenLoaded) {
    errors.push(`content popup missing ${JSON.stringify(verdict.diag || {})}`);
  }
  await sleep(500); // fonts + any transition settle

  const shot = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, sessionId);
  await writeFile(join(OUT_DIR, `${c.name}.png`), Buffer.from(shot.data, 'base64'));

  off();
  await cdp.send('Target.closeTarget', { targetId });
  return { name: c.name, tokenLoaded: !!verdict.tokenLoaded, theme: verdict.theme, errors };
}

async function driveContentPopupCase(cdp, sessionId, extId) {
  const contentSource = await readFile(join(EXT_DIR, 'content', 'content.js'), 'utf8');
  const bootstrap = await cdp.send('Runtime.evaluate', {
    expression: `(() => new Promise((resolve, reject) => {
      const store = { kg_theme: 'light', kg_enabled: true, active_notebook_id: 'nb-reading' };
      const realAttachShadow = Element.prototype.attachShadow;
      Element.prototype.attachShadow = function(init) {
        const opts = init && typeof init === 'object' ? { ...init, mode: 'open' } : init;
        return realAttachShadow.call(this, opts);
      };
      chrome.storage.local.get = (key, cb) => {
        let result = {};
        if (Array.isArray(key)) result = Object.fromEntries(key.map((k) => [k, store[k]]));
        else if (typeof key === 'string') result = { [key]: store[key] };
        else if (key && typeof key === 'object') result = Object.fromEntries(Object.keys(key).map((k) => [k, store[k] ?? key[k]]));
        else result = { ...store };
        if (typeof cb === 'function') cb(result);
        return Promise.resolve(result);
      };
      chrome.storage.local.set = (values, cb) => {
        Object.assign(store, values || {});
        if (typeof cb === 'function') cb();
        return Promise.resolve();
      };
      chrome.storage.onChanged = { addListener() {} };
      chrome.runtime.sendMessage = (msg, cb) => {
        const type = msg && msg.type;
        if (type === 'addVocab') window.__kgShotLastAddNotebookId = msg.notebookId;
        const response =
          type === 'translate'
            ? { t: '明暗對照；明暗法', p: '/kiˌɑːrəˈskjʊroʊ/', r: 'n.' }
            : type === 'listNotebooks'
              ? [
                  { id: 'default', name: '我的單字本', is_default: true },
                  { id: 'nb-reading', name: '閱讀筆記', color: '#C5B2D0' },
                  { id: 'nb-exam', name: '考試詞彙', color: '#A9C7B8' },
                ]
              : type === 'addVocab'
                ? { ok: true, optimistic: true, queued: 1 }
                : { ok: true };
        queueMicrotask(() => {
          chrome.runtime.lastError = null;
          if (typeof cb === 'function') cb(response);
        });
      };
      try {
        (0, eval)(${JSON.stringify(contentSource + '\n//# sourceURL=kg-content-popup-shot.js')});
        resolve(true);
      } catch (err) {
        reject(err);
      }
    }))()`,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  if (bootstrap.exceptionDetails) throw new Error(bootstrap.exceptionDetails.text || 'content popup bootstrap failed');
  if (!bootstrap.result || bootstrap.result.value !== true) {
    throw new Error(`content popup bootstrap failed ${JSON.stringify(bootstrap.result || {})}`);
  }

  const opened = await cdp.send('Runtime.evaluate', {
    expression: `(() => new Promise((resolve) => {
      const target = document.getElementById('selectionTarget').firstChild;
      const text = target.textContent;
      const start = text.indexOf('chiaroscuro');
      const range = document.createRange();
      range.setStart(target, start);
      range.setEnd(target, start + 'chiaroscuro'.length);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.getElementById('selectionTarget').dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: 156, clientY: 146 }));
      const deadline = Date.now() + 4000;
      const tick = () => {
        const host = document.getElementById('kg-popup-host');
        if (host) {
          window.__kgShotPopupOpened = true;
          return resolve(true);
        }
        if (Date.now() > deadline) return resolve(false);
        setTimeout(tick, 40);
      };
      tick();
    }))()`,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  if (!opened.result.value) throw new Error('content popup did not open');
  const asserted = await cdp.send('Runtime.evaluate', {
    expression: `(() => new Promise((resolve) => {
      const deadline = Date.now() + 4000;
      const tick = () => {
        const host = document.getElementById('kg-popup-host');
        const root = host && host.shadowRoot;
        const select = root && root.querySelector('[data-role="notebook-select"]');
        const add = root && root.querySelector('[data-action="add"]');
        if (select && add && select.options.length >= 3) {
          const initial = select.value;
          select.value = 'nb-exam';
          select.dispatchEvent(new Event('change', { bubbles: true }));
          add.click();
          setTimeout(() => resolve({
            ok: initial === 'nb-reading' && window.__kgShotLastAddNotebookId === 'nb-exam',
            initial,
            sent: window.__kgShotLastAddNotebookId || null,
            optionCount: select.options.length,
          }), 80);
          return;
        }
        if (Date.now() > deadline) return resolve({ ok: false, initial: null, sent: null, optionCount: select ? select.options.length : 0 });
        setTimeout(tick, 40);
      };
      tick();
    }))()`,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  const assertion = asserted.result && asserted.result.value;
  if (!assertion || assertion.ok !== true) {
    throw new Error(`content popup notebook assertion failed ${JSON.stringify(assertion || {})}`);
  }
  const reopened = await cdp.send('Runtime.evaluate', {
    expression: `(() => new Promise((resolve) => {
      const oldHost = document.getElementById('kg-popup-host');
      if (oldHost) oldHost.remove();
      window.__kgShotPopupOpened = false;
      chrome.storage.local.set({ active_notebook_id: 'nb-reading' });
      const target = document.getElementById('selectionTarget').firstChild;
      const text = target.textContent;
      const start = text.indexOf('chiaroscuro');
      const range = document.createRange();
      range.setStart(target, start);
      range.setEnd(target, start + 'chiaroscuro'.length);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.getElementById('selectionTarget').dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: 156, clientY: 146 }));
      const deadline = Date.now() + 4000;
      const tick = () => {
        const host = document.getElementById('kg-popup-host');
        const select = host && host.shadowRoot && host.shadowRoot.querySelector('[data-role="notebook-select"]');
        if (select && select.value === 'nb-reading') {
          window.__kgShotPopupOpened = true;
          return resolve(true);
        }
        if (Date.now() > deadline) return resolve(false);
        setTimeout(tick, 40);
      };
      tick();
    }))()`,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  if (!reopened.result.value) throw new Error('content popup did not reopen after assertion');
  await sleep(700);
}

async function main() {
  const chrome = findChrome();
  await mkdir(OUT_DIR, { recursive: true });
  const userDataDir = await mkdtemp(join(tmpdir(), 'kg-shots-'));
  const proc = spawn(chrome, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-features=Translate,OptimizationHints',
    '--enable-unsafe-extension-debugging', `--user-data-dir=${userDataDir}`,
    '--remote-debugging-pipe', '--force-color-profile=srgb', 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  let stderr = '';
  proc.stderr.on('data', (d) => { stderr += d.toString(); });

  let failed = false;
  try {
    const cdp = new CDP(proc);
    await waitReady(cdp);
    const r = await withTimeout(cdp.send('Extensions.loadUnpacked', { path: EXT_DIR }), 8000, 'loadUnpacked');
    const extId = r.id;
    log('extension id:', extId);
    await sleep(400);

    const cases = ONLY ? CASES.filter((c) => c.name.includes(ONLY)) : CASES;
    if (cases.length === 0) throw new Error(`no case matches --only ${ONLY}`);
    for (const c of cases) {
      const res = await shoot(cdp, extId, c);
      const bad = !res.tokenLoaded || res.errors.length;
      if (bad) failed = true;
      const flag = res.errors.length ? ` ✗ ${res.errors[0]}` : !res.tokenLoaded ? ' ✗ NO TOKEN (false green guard)' : '';
      console.error(`${bad ? '✗' : '✓'} ${res.name}  (theme=${res.theme})${flag}`);
    }
  } catch (e) {
    failed = true;
    console.error('shots harness error:', e.message);
    if (VERBOSE && stderr) console.error('[chrome stderr]\n' + stderr.split('\n').slice(-20).join('\n'));
  } finally {
    proc.kill('SIGKILL');
    await rm(userDataDir, { recursive: true, force: true }).catch(() => {});
  }

  if (failed) { console.error('\nSHOTS FAILED'); process.exit(1); }
  console.error(`\n✅ shots written to ${join('chrome-extension', 'tools', 'shots')}/`);
}

main().catch((e) => { console.error('shots error:', e.message); process.exit(2); });
