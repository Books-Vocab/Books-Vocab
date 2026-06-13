import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { BookCard } from './BookCard'
import type { BookFixture } from './fixtures'

/**
 * BookCard 結構契約 — 互動 DOM 合法性。
 *
 * 殼層路徑（onOpen + onMore 皆掛載）下，封面是 <button>（單擊開書），overflow
 * 「更多動作」鈕亦是 <button>。HTML 規範禁止 <button> 巢狀於 <button>：瀏覽器會
 * 隱式關閉外層 button 修正 DOM，導致 React hydration error 與封面點擊事件語意損壞
 * （實測：滑鼠點封面無法可靠觸發 onOpen）。本測試把「overflow 鈕不得是 cover 鈕
 * 後代」釘成回歸契約，純 SSR 字串掃描（無需 jsdom）。
 */

const book: BookFixture = {
  title: 'Atomic Habits',
  author: 'James Clear',
  dateLabel: '0秒後',
  format: 'epub',
  progression: 0,
  needsICloudDownload: false,
}

/** 掃描 html，回傳 `marker` 是否出現在某個 cover-button 的 <button>…</button> 內。 */
function markerNestedInCoverButton(html: string, marker: string): boolean {
  const coverOpen = html.indexOf('book-card-cover-button')
  if (coverOpen === -1) return false
  // 從 cover-button 的 <button 起點開始追蹤 button 深度。
  const start = html.lastIndexOf('<button', coverOpen)
  let depth = 0
  const tagRe = /<button\b|<\/button>/g
  tagRe.lastIndex = start
  let m: RegExpExecArray | null
  while ((m = tagRe.exec(html)) !== null) {
    depth += m[0] === '</button>' ? -1 : 1
    if (depth === 0) {
      // cover button 已閉合 → 之後出現的 marker 不算巢狀。
      const markerIdx = html.indexOf(marker, start)
      return markerIdx !== -1 && markerIdx < m.index
    }
  }
  return false
}

describe('BookCard 互動結構', () => {
  it('overflow 鈕不得巢狀於 cover 鈕內（避免 button-in-button 非法 HTML）', () => {
    const html = renderToStaticMarkup(
      <BookCard book={book} onOpen={() => {}} onMore={() => {}} />,
    )
    expect(html).toContain('book-card-cover-button')
    expect(html).toContain('book-card-overflow')
    expect(markerNestedInCoverButton(html, 'book-card-overflow')).toBe(false)
  })
})
