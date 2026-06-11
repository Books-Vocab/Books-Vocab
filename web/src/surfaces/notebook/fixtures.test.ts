import { describe, expect, it } from 'vitest'
import { NOTEBOOK_FIXTURES } from './fixtures'

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/NotebookListViewScenarios.swift 的 seed：
// notebook 數量、名稱、active 標記、N 詞 / actionable 數字必須逐字一致，否則
// parity diff 會在文字層失真。filter pill 顯示與否由 notebookCount >= 2 決定
// （iOS NotebookReviewActionBar gate）。
describe('NOTEBOOK_FIXTURES', () => {
  it('single scenario mirrors the Catalog seed (1 notebook, no filter pill)', () => {
    const f = NOTEBOOK_FIXTURES.single
    expect(f.showFilter).toBe(false)
    expect(f.reviewTotal).toBe(3)
    expect(f.cards.map((c) => [c.name, c.cardCount, c.actionableCount, c.isActive])).toEqual([
      ['我的單字本', 3, 3, true],
    ])
  })

  it('populated scenario lists three notebooks, active 我的單字本 first, filter pill shown', () => {
    const f = NOTEBOOK_FIXTURES.populated
    expect(f.showFilter).toBe(true)
    // CTA 總數 = 各 notebook actionable 合計（3+2+1）
    expect(f.reviewTotal).toBe(6)
    expect(f.cards.map((c) => [c.name, c.cardCount, c.actionableCount, c.isActive])).toEqual([
      ['我的單字本', 3, 3, true],
      ['經典文學', 2, 2, false],
      ['科普閱讀', 1, 1, false],
    ])
    expect(f.cards.reduce((sum, c) => sum + c.actionableCount, 0)).toBe(f.reviewTotal)
  })

  it('all cards use the default cover color and an empty progress bar (catalog seed)', () => {
    for (const scenario of ['single', 'populated'] as const) {
      for (const card of NOTEBOOK_FIXTURES[scenario].cards) {
        expect(card.color).toBe('#AFC2D3')
        expect(card.reviewProgress).toBe(0)
      }
    }
  })
})
