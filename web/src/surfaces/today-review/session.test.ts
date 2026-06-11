import { describe, expect, it } from 'vitest'
import { SESSION_START_INDEX, SESSION_TOTAL, TODAY_REVIEW_FIXTURES, sessionQueue } from './fixtures'

// session 佇列衍生不變式。flip/grade 的 stateful DOM 行為由 tools/interaction.mjs
// （playwright）驗證。
describe('today-review session queue', () => {
  it('progress seed「3 / 12」對應 index 2 / total 12', () => {
    expect(SESSION_START_INDEX).toBe(2)
    expect(SESSION_TOTAL).toBe(12)
    expect(TODAY_REVIEW_FIXTURES.front.progressText).toBe(`${SESSION_START_INDEX + 1} / ${SESSION_TOTAL}`)
  })

  it('佇列首張 === scenario fixture 的 card（parity 初始顯示卡不變）', () => {
    for (const id of ['front', 'back', 'production-front', 'production-back'] as const) {
      expect(sessionQueue(id)[0]).toBe(TODAY_REVIEW_FIXTURES[id].card)
    }
  })

  it('佇列長度涵蓋當前卡至最後一張（index 2…11 → 10 張）', () => {
    expect(sessionQueue('front')).toHaveLength(SESSION_TOTAL - SESSION_START_INDEX)
  })
})
