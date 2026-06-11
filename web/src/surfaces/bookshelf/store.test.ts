import { describe, expect, it } from 'vitest'
import { bookshelfFixture } from './fixtures'

// store 的 hook（匯入 / 改名 / 刪除 / 刪光落 empty）由 interaction.mjs（playwright）
// 做端到端互動驗證。此處鎖 store seed 的真相來源：useBookshelfStore 的初值必須等於
// bookshelfFixture(scenario)，確保 parity 首屏不漂移（empty seed 為 0 本）。
describe('bookshelf store seed contract', () => {
  it('empty scenario seeds zero books (刪光後落入相同 empty 視覺)', () => {
    expect(bookshelfFixture('empty')).toHaveLength(0)
  })

  it('single / populated seeds carry unique titles (in-memory id 不撞)', () => {
    for (const scenario of ['single', 'populated'] as const) {
      const titles = bookshelfFixture(scenario).map((b) => b.title)
      expect(new Set(titles).size).toBe(titles.length)
    }
  })
})
