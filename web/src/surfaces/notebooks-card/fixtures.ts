import type { ScenarioId } from '../../harness/scenarios'

/**
 * Notebooks · Card surface fixtures — 鏡射 iOS NotebooksScenarios.swift
 * (`NotebookCardData`)。直接餵合成資料（iOS catalog 不掛 SwiftData）。
 *
 * 兩種 scene layout：
 * - 'hero'：cardSheet(style:.hero)，單卡跨整列寬（VStack，pageHorizontalInset=s5）。
 * - 'grid'：gridSheet，LazyVGrid(.adaptive minimum 160, spacing s6=24)，兩卡並排。
 *
 * 注意：iOS NotebookCard.body 不依 style 分支（hero/grid 共用同一 HStack book-row，
 * 72pt 高、cover 40%）；唯一差異是外層 scene 容器寬度與排列（VStack vs LazyVGrid）。
 */

export interface NotebooksCardItem {
  name: string
  /** cover hex（NotebookPalette raw color，darken 由渲染端算） */
  color: string
  cardCount: number
  dueCount: number
  unlearnedCount: number
  reviewedCount: number
  isActive: boolean
}

export interface NotebooksCardFixture {
  layout: 'hero' | 'grid'
  cards: NotebooksCardItem[]
}

// iOS heavyCard — 我的單字本 / #5077A0 / 626 詞 / due538 unlearned0 reviewed88 / active
const heavyCard: NotebooksCardItem = {
  name: '我的單字本',
  color: '#5077A0',
  cardCount: 626,
  dueCount: 538,
  unlearnedCount: 0,
  reviewedCount: 88,
  isActive: true,
}

// iOS lightCard — GRE 字根 / #7A8C6A / 42 詞 / due3 unlearned15 reviewed24 / inactive
const lightCard: NotebooksCardItem = {
  name: 'GRE 字根',
  color: '#7A8C6A',
  cardCount: 42,
  dueCount: 3,
  unlearnedCount: 15,
  reviewedCount: 24,
  isActive: false,
}

// iOS freshCard — Self / #B5826A / 0 詞（空 notebook，placeholder 文字）/ inactive
const freshCard: NotebooksCardItem = {
  name: 'Self',
  color: '#B5826A',
  cardCount: 0,
  dueCount: 0,
  unlearnedCount: 0,
  reviewedCount: 0,
  isActive: false,
}

// iOS longNameCard — 長名截斷 / #8B7AA8 / 7000 詞 / due1234 unlearned567 reviewed5199 / active
const longNameCard: NotebooksCardItem = {
  name: '我的學測必背 7000 單字本 (含倒車雷達進階口語延伸)',
  color: '#8B7AA8',
  cardCount: 7000,
  dueCount: 1234,
  unlearnedCount: 567,
  reviewedCount: 5199,
  isActive: true,
}

export const NOTEBOOKS_CARD_FIXTURES: Record<ScenarioId<'notebooks-card'>, NotebooksCardFixture> = {
  'grid-two': { layout: 'grid', cards: [heavyCard, lightCard] },
  'hero-fresh': { layout: 'hero', cards: [freshCard] },
  'hero-long-name': { layout: 'hero', cards: [longNameCard] },
  'hero-heavy': { layout: 'hero', cards: [heavyCard] },
}
