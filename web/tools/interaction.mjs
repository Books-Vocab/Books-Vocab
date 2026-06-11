/**
 * interaction.mjs — 最薄互動驗證（playwright headless Chromium）。
 *
 * parity 靜態渲染由 shots.mjs/compare.mjs 守 RMSE=0；本檔守「互動後 DOM 確有變化」：
 *   Vocabulary：搜尋過濾結果數、chip 過濾、row 點擊展開 detail。
 *   Today Review：點卡翻面（front↔back）、答對/答錯推進進度、走完佇列完成態。
 *
 * Usage:  node tools/interaction.mjs [--no-build]
 * 退出碼非 0 = 任一斷言失敗。
 */

import { execFileSync, spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const NO_BUILD = process.argv.includes('--no-build');

function getFreePort() {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close((err) => (err ? rej(err) : res(port)));
    });
    srv.on('error', rej);
  });
}

async function waitForServer(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`preview server did not come up at ${url}`);
}

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log(`✓ ${name}`);
  } else {
    console.error(`✗ ${name}`);
    failures++;
  }
}

async function main() {
  if (!NO_BUILD) {
    console.error('building web/ …');
    execFileSync('npm', ['run', 'build'], { cwd: WEB_DIR, stdio: ['ignore', 'ignore', 'inherit'] });
  }

  const port = process.env.SHOTS_PORT ? Number(process.env.SHOTS_PORT) : await getFreePort();
  const BASE = `http://localhost:${port}`;
  const server = spawn(join(WEB_DIR, 'node_modules', '.bin', 'vite'),
    ['preview', '--port', String(port), '--strictPort'], { cwd: WEB_DIR, stdio: 'ignore' });
  await waitForServer(BASE);

  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();

    // ── Vocabulary ────────────────────────────────────────────────
    await page.goto(`${BASE}/?surface=vocabulary&scenario=populated&appearance=light`, { waitUntil: 'load' });

    const rowCount = () => page.locator('.vc-row').count();
    check('vocab initial shows 4 rows', (await rowCount()) === 4);

    // 搜尋過濾：輸入 "eph" → 只剩 ephemeral。
    await page.fill('.vc-search-input', 'eph');
    check('vocab search "eph" filters to 1 row', (await rowCount()) === 1);
    check('vocab search keeps ephemeral', (await page.locator('.vc-row-word').first().textContent()) === 'ephemeral');

    // 清空 → 復原 4 row。
    await page.fill('.vc-search-input', '');
    check('vocab clear search restores 4 rows', (await rowCount()) === 4);

    // chip 過濾：點「待複習」(due) → seed 無 due → no-match 空狀態。
    await page.locator('.vc-stat').nth(1).click();
    check('vocab due chip → 0 rows', (await rowCount()) === 0);
    check('vocab due chip → no-match empty card', (await page.locator('.vc-empty').count()) === 1);
    // 再點同 chip 取消 → 復原。
    await page.locator('.vc-stat').nth(1).click();
    check('vocab toggle due chip off restores 4 rows', (await rowCount()) === 4);

    // row 展開：點第一列 → 出現 detail panel。
    check('vocab no detail panel before click', (await page.locator('.vc-row-detail-panel').count()) === 0);
    await page.locator('.vc-row').first().click();
    check('vocab row click reveals detail panel', (await page.locator('.vc-row-detail-panel').count()) === 1);
    // 再點收合。
    await page.locator('.vc-row').first().click();
    check('vocab row click again collapses detail', (await page.locator('.vc-row-detail-panel').count()) === 0);

    // ── Today Review ──────────────────────────────────────────────
    await page.goto(`${BASE}/?surface=today-review&scenario=front&appearance=light`, { waitUntil: 'load' });

    const isFolded = () => page.locator('.tr-card-folded').count();
    const isSingle = () => page.locator('.tr-card-single').count();
    check('review initial = front (single, not folded)', (await isSingle()) === 1 && (await isFolded()) === 0);
    check('review initial progress 3 / 12', (await page.locator('.tr-progress-pill').textContent()) === '3 / 12');
    check('review no answer body before flip', (await page.locator('.tr-answer-body').count()) === 0);

    // 翻面：點卡 → folded（答案揭示）。
    await page.locator('.tr-card').click();
    check('review flip → folded answer revealed', (await isFolded()) === 1 && (await page.locator('.tr-answer-body').count()) === 1);
    // 再點翻回 front。
    await page.locator('.tr-card').click();
    check('review flip back → front single', (await isSingle()) === 1 && (await page.locator('.tr-answer-body').count()) === 0);

    // 評分推進：點「記得」→ 進度 4 / 12、記得計數 +1（3）。
    await page.locator('.tr-feedback-remembered').click();
    check('review grade advances progress to 4 / 12', (await page.locator('.tr-progress-pill').textContent()) === '4 / 12');
    check('review remembered count → 3', (await page.locator('.tr-feedback-remembered .tr-feedback-count').textContent()) === '·3');

    // 連續評分至走完佇列。已評 1 次（index 2→3），再評 9 次：
    // index 3→4→…→11（第 8 次到 index 11=12/12），第 9 次 nextIndex 12≥12 → done。
    for (let i = 0; i < 9; i++) await page.locator('.tr-feedback-forgot').click();
    check('review session completion state appears', (await page.locator('.tr-complete').count()) === 1);
    check('review completion progress 12 / 12', (await page.locator('.tr-progress-pill').textContent()) === '12 / 12');

    await ctx.close();
  } finally {
    await browser.close();
    server.kill();
  }

  if (failures > 0) {
    console.error(`\n${failures} interaction assertion(s) FAILED`);
    process.exit(1);
  }
  console.log('\nAll interaction assertions passed.');
}

await main();
