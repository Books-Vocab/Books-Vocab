import { describe, expect, it } from 'vitest'
import { makeNotebookCard } from './store'

// store 的 hook 部分由 interaction.mjs（playwright）做端到端互動驗證；此處只單測
// 不依賴 React 的純函式 makeNotebookCard（新建空卡的形狀契約）。
describe('makeNotebookCard', () => {
  it('builds a freshly-added empty notebook card (default cover, 0 詞, non-active)', () => {
    const card = makeNotebookCard('旅行筆記')
    expect(card).toEqual({
      name: '旅行筆記',
      color: '#AFC2D3',
      cardCount: 0,
      actionableCount: 0,
      reviewProgress: 0,
      isActive: false,
    })
  })
})
