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

    // ── Notebook ──────────────────────────────────────────────────
    await page.goto(`${BASE}/?surface=notebook&scenario=populated&appearance=light`, { waitUntil: 'load' });

    const nbCardCount = () => page.locator('.nb-card').count();
    check('notebook initial shows 3 cards', (await nbCardCount()) === 3);
    check('notebook no sheet/menu before interaction',
      (await page.locator('.nb-sheet-scrim').count()) === 0 && (await page.locator('.nb-menu-scrim').count()) === 0);

    // 新增 notebook：plus pill → sheet → 輸入 → 建立 → 列表 +1（新卡出現）。
    await page.locator('.nb-pill-button').click();
    check('notebook add pill opens sheet', (await page.locator('.nb-sheet-scrim').count()) === 1);
    await page.fill('.nb-sheet-input', '旅行筆記');
    await page.locator('.nb-sheet-submit').click();
    check('notebook add appends card → 4', (await nbCardCount()) === 4);
    check('notebook add sheet closed after submit', (await page.locator('.nb-sheet-scrim').count()) === 0);
    check('notebook new card name visible',
      (await page.locator('.nb-card[data-name="旅行筆記"]').count()) === 1);

    // more 選單：點某卡 overlay → 選單浮現。
    await page.locator('.nb-card[data-name="經典文學"] .nb-card-more').click();
    check('notebook more menu appears', (await page.locator('.nb-menu-scrim').count()) === 1);
    // 編輯 → 改名 sheet → 真輸入 → 儲存 → 卡名更新（舊名消失、新名出現）。
    await page.locator('.nb-menu-item').first().click();
    check('notebook edit opens rename sheet', (await page.locator('.nb-sheet-scrim').count()) === 1);
    await page.fill('.nb-sheet-input', '世界文學');
    await page.locator('.nb-sheet-submit').click();
    check('notebook rename updates card name',
      (await page.locator('.nb-card[data-name="世界文學"]').count()) === 1 &&
      (await page.locator('.nb-card[data-name="經典文學"]').count()) === 0);

    // 刪除：開「科普閱讀」more → 刪除 → 列表 -1，且 filter pill 仍在（>=2 本）。
    await page.locator('.nb-card[data-name="科普閱讀"] .nb-card-more').click();
    await page.locator('.nb-menu-item-destructive').click();
    check('notebook delete removes card → 3', (await nbCardCount()) === 3);
    check('notebook 科普閱讀 gone', (await page.locator('.nb-card[data-name="科普閱讀"]').count()) === 0);

    // populated（3 本）→ filter + plus 兩個 tool pill；single（1 本）→ 只剩 plus。
    // filter pill 由 store.showFilter（cards.length >= 2）即時推導。
    check('notebook populated has filter + plus tool pills', (await page.locator('.nb-pill-tool').count()) === 2);
    await page.goto(`${BASE}/?surface=notebook&scenario=single&appearance=light`, { waitUntil: 'load' });
    check('notebook single one card', (await nbCardCount()) === 1);
    check('notebook single → only plus pill (no filter)', (await page.locator('.nb-pill-tool').count()) === 1);

    // ── Bookshelf ─────────────────────────────────────────────────
    await page.goto(`${BASE}/?surface=bookshelf&scenario=populated&appearance=light`, { waitUntil: 'load' });

    const bookCount = () => page.locator('.book-card').count();
    check('bookshelf initial shows 5 books', (await bookCount()) === 5);
    check('bookshelf no sheet/menu before interaction',
      (await page.locator('.bs-sheet-scrim').count()) === 0 && (await page.locator('.bs-menu-scrim').count()) === 0);

    // 匯入入口：affordance → 匯入 sheet stub（檔案 picker 視覺）。
    await page.locator('.bookshelf-import-affordance').click();
    check('bookshelf import affordance opens sheet', (await page.locator('.bs-sheet-scrim').count()) === 1);
    check('bookshelf import sheet shows picker stub', (await page.locator('.bs-import-picker').count()) === 1);
    await page.locator('.bs-sheet-close').click();
    check('bookshelf import sheet closes', (await page.locator('.bs-sheet-scrim').count()) === 0);

    // 書卡 more → 改名 → 真輸入 → 儲存 → 標題更新。
    await page.locator('.book-card-more[data-title="Deep Work"]').click();
    check('bookshelf more menu appears', (await page.locator('.bs-menu-scrim').count()) === 1);
    await page.locator('.bs-menu-item').first().click();
    check('bookshelf rename opens sheet', (await page.locator('.bs-sheet-scrim').count()) === 1);
    await page.fill('.bs-sheet-input', 'Deep Focus');
    await page.locator('.bs-sheet-submit').click();
    check('bookshelf rename updates title',
      (await page.locator('.book-card-more[data-title="Deep Focus"]').count()) === 1 &&
      (await page.locator('.book-card-more[data-title="Deep Work"]').count()) === 0);

    // 刪除：逐一刪到空 → empty scenario 視覺出現。
    const titles = ['Atomic Habits', 'Deep Focus', 'Flow', 'Meditations', 'On Writing Well'];
    for (const t of titles) {
      await page.locator(`.book-card-more[data-title="${t}"]`).click();
      await page.locator('.bs-menu-item-destructive').click();
    }
    check('bookshelf delete-all empties grid', (await bookCount()) === 0);
    check('bookshelf empty state visible after delete-all',
      (await page.locator('.bookshelf-empty').count()) === 1 &&
      (await page.locator('.bookshelf-empty-import').count()) === 1);
    // empty state 匯入鈕也能開 sheet。
    await page.locator('.bookshelf-empty-import').click();
    check('bookshelf empty import button opens sheet', (await page.locator('.bs-sheet-scrim').count()) === 1);

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
