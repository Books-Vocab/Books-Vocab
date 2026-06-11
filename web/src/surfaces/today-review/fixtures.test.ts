import { describe, expect, it } from 'vitest'
import { TODAY_REVIEW_FIXTURES } from './fixtures'

// 鏡像 ios/.../TodayReviewFixtures.swift 的 seed：每個 scenario 都是 3/12 進度
// （忘記 1 / 記得 2）。recognition card = meticulous、production card = ubiquitous；
// reveal 階段（front/back）決定卡是否摺頁展開答案。文字必須逐字一致，否則 parity
// diff 會在文字層失真。
describe('TODAY_REVIEW_FIXTURES', () => {
  it('all scenarios share the 3/12 session counts (forgot 1 / remembered 2)', () => {
    for (const id of ['front', 'back', 'production-front', 'production-back'] as const) {
      const f = TODAY_REVIEW_FIXTURES[id]
      expect(f.progressText).toBe('3 / 12')
      expect([f.forgotCount, f.rememberedCount]).toEqual([1, 2])
    }
  })

  it('recognition scenarios carry the meticulous card; reveal stage differs', () => {
    expect(TODAY_REVIEW_FIXTURES.front.reveal).toBe('front')
    expect(TODAY_REVIEW_FIXTURES.back.reveal).toBe('back')
    for (const id of ['front', 'back'] as const) {
      const c = TODAY_REVIEW_FIXTURES[id].card
      expect(c.mode).toBe('recognition')
      expect(c.word).toBe('meticulous')
      expect(c.translation).toBe('一絲不苟的；非常仔細的')
      expect(c.difficultyTier).toBe('advanced')
      expect(c.links).toEqual([{ label: '相關', words: ['precise', 'thorough'], overflowCount: 1 }])
    }
  })

  it('production scenarios carry the ubiquitous card with a cloze front example', () => {
    expect(TODAY_REVIEW_FIXTURES['production-front'].reveal).toBe('front')
    expect(TODAY_REVIEW_FIXTURES['production-back'].reveal).toBe('back')
    for (const id of ['production-front', 'production-back'] as const) {
      const c = TODAY_REVIEW_FIXTURES[id].card
      expect(c.mode).toBe('production')
      expect(c.word).toBe('ubiquitous')
      expect(c.translation).toBe('無所不在的；普遍存在的')
      expect(c.difficultyTier).toBe('intermediate')
      expect(c.links).toEqual([{ label: '相關', words: ['pervasive', 'omnipresent'], overflowCount: 0 }])
    }
    // cloze front 必含遮蔽 blank 片段
    expect(TODAY_REVIEW_FIXTURES['production-front'].card.exampleFront.some((s) => s.blank)).toBe(true)
  })

  it('answer-side back examples carry exactly one highlighted mark segment', () => {
    for (const id of ['front', 'back', 'production-front', 'production-back'] as const) {
      const marks = TODAY_REVIEW_FIXTURES[id].card.exampleBack.filter((s) => s.mark)
      expect(marks).toHaveLength(1)
    }
  })
})
