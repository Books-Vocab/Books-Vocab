/**
 * interactive-check.mjs — 最薄互動驗證（非 parity gate）。
 *
 * 啟動 `vite preview`，用 Playwright 真實驅動 Settings / Podcast 兩 surface 的
 * 互動，斷言 DOM / audio 狀態確實隨手勢改變。parity 像素中立由 shots.mjs +
 * magick compare 另行守門；本檔只驗「互動是否活」。
 *
 * Usage: node tools/interactive-check.mjs   （需先 npm run build，dist/ 要新）
 * 退出碼 0 = 全綠；非 0 = 有斷言失敗。
 */
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function getFreePort() {
  return new Promise((res, rej) => {
    const s = createServer()
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address()
      s.close((e) => (e ? rej(e) : res(port)))
    })
    s.on('error', rej)
  })
}
async function waitForServer(url, ms = 15000) {
  const dl = Date.now() + ms
  while (Date.now() < dl) {
    try {
      if ((await fetch(url)).ok) return
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 150))
  }
  throw new Error(`preview not up at ${url}`)
}

let passed = 0
let failed = 0
function check(name, cond) {
  if (cond) {
    passed++
    console.log(`✓ ${name}`)
  } else {
    failed++
    console.error(`✗ ${name}`)
  }
}

async function main() {
  const port = await getFreePort()
  const BASE = `http://localhost:${port}`
  // npm run preview：npm 把 hoisted node_modules/.bin 加進 PATH，monorepo 下仍可解析 vite。
  const server = spawn('npm', ['run', 'preview', '--', '--port', String(port), '--strictPort'], {
    cwd: WEB_DIR,
    stdio: 'ignore',
  })
  await waitForServer(BASE)

  const browser = await chromium.launch()
  try {
    const ctx = await browser.newContext({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 2 })
    const page = await ctx.newPage()

    // ---------------- Settings ----------------
    await page.goto(`${BASE}/?surface=settings&scenario=subscribed-active&appearance=light`, { waitUntil: 'load' })
    await page.evaluate(() => document.fonts.ready)

    // 自動同步 toggle：初始 on → 點擊 → off
    const toggle = page.locator('.settings-toggle')
    check('settings toggle starts on (aria-checked=true)', (await toggle.getAttribute('aria-checked')) === 'true')
    await toggle.click()
    check('settings toggle flips to off after click', (await toggle.getAttribute('aria-checked')) === 'false')
    await toggle.click()
    check('settings toggle flips back to on', (await toggle.getAttribute('aria-checked')) === 'true')

    // 外觀即時切換：開「外觀」sheet → 選「深色」→ phone-frame data-theme=dark
    check('frame theme starts light', (await page.locator('[data-harness="phone-frame"]').getAttribute('data-theme')) === 'light')
    await page.locator('.settings-row-button', { hasText: '外觀' }).click()
    await page.locator('.settings-sheet-option', { hasText: '深色' }).click()
    check('frame theme switches to dark', (await page.locator('[data-harness="phone-frame"]').getAttribute('data-theme')) === 'dark')
    check('外觀 row value reflects 深色', (await page.locator('.settings-row-button', { hasText: '外觀' }).locator('.settings-row-value').textContent()) === '深色')

    // 登出 → 帳號區切到 logged-out（出現 Google 登入鈕、autoSync 列消失）
    await page.locator('.settings-signout').click()
    check('sign out shows login card', (await page.locator('.settings-login-card').count()) === 1)
    check('sign out hides autoSync toggle', (await page.locator('.settings-toggle').count()) === 0)
    // 重新登入
    await page.locator('.settings-login-button').first().click()
    check('sign in restores logged-in card', (await page.locator('.settings-login-card').count()) === 0)

    // ---------------- Podcast ----------------
    await page.goto(`${BASE}/?surface=podcast&scenario=preview-player&appearance=light`, { waitUntil: 'load' })
    await page.evaluate(() => document.fonts.ready)
    // 等 audio metadata
    await page.waitForFunction(() => {
      const a = document.querySelector('[data-pc-audio]')
      return a && a.readyState >= 1
    }, { timeout: 5000 }).catch(() => {})

    const elapsedBefore = await page.locator('[data-pc-elapsed]').textContent()
    // 初始字幕 active 句 = 第 3 句（fixture 靜態）
    const activeIdxBefore = await page.evaluate(() => {
      const bubbles = [...document.querySelectorAll('.pc-bubble')]
      return bubbles.findIndex((b) => b.classList.contains('pc-bubble-active'))
    })
    check('podcast initial active bubble = 3rd (fixture static)', activeIdxBefore === 2)

    // 按 play → audio 播放、currentTime 前進
    await page.locator('[data-pc-play]').click()
    await page.waitForFunction(() => {
      const a = document.querySelector('[data-pc-audio]')
      return a && !a.paused && a.currentTime > 0.4
    }, { timeout: 5000 })
    const ct = await page.evaluate(() => document.querySelector('[data-pc-audio]').currentTime)
    check('podcast audio currentTime advances after play', ct > 0.4)
    check('podcast play disc shows playing state', (await page.locator('[data-pc-play]').getAttribute('data-playing')) === 'true')

    // 讓它跑到後段，斷言 active 句已從第 3 句改變（highlight 跟隨）
    await page.evaluate(() => {
      const a = document.querySelector('[data-pc-audio]')
      a.currentTime = 0.2 // 跳回開頭 → active 應為第 1 句
    })
    await page.waitForTimeout(300)
    const activeIdxEarly = await page.evaluate(() => {
      const bubbles = [...document.querySelectorAll('.pc-bubble')]
      return bubbles.findIndex((b) => b.classList.contains('pc-bubble-active'))
    })
    check('podcast subtitle highlight follows playhead (seek to start → 1st sentence)', activeIdxEarly === 0)

    // 時鐘已連動（與初始 fixture 文字不同）
    const elapsedAfter = await page.locator('[data-pc-elapsed]').textContent()
    check('podcast clock updates from fixture static', elapsedAfter !== elapsedBefore)

    // seek bar 真連動：點進度條中段 → currentTime ≈ 6s
    await page.locator('[data-pc-audio]').evaluate((a) => a.pause())
    const seek = page.locator('[data-pc-seek]')
    const box = await seek.boundingBox()
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height / 2)
    const ctMid = await page.evaluate(() => document.querySelector('[data-pc-audio]').currentTime)
    check('podcast seek to middle sets currentTime ≈ 6s', ctMid > 4 && ctMid < 8)

    // speed 控制：×1 → ×1.5 → audio.playbackRate
    const rate = page.locator('[data-pc-rate]')
    check('podcast rate starts ×1', (await rate.textContent()).trim() === '×1')
    await rate.click()
    check('podcast rate cycles to ×1.5', (await rate.textContent()).trim() === '×1.5')
    const pr = await page.evaluate(() => document.querySelector('[data-pc-audio]').playbackRate)
    check('podcast audio.playbackRate = 1.5', Math.abs(pr - 1.5) < 1e-6)

    await ctx.close()
  } finally {
    await browser.close()
    server.kill()
  }

  console.log(`\nInteractive checks: ${passed} passed, ${failed} failed`)
  if (failed > 0) process.exit(1)
}

await main()
