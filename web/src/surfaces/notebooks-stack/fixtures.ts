import type { ScenarioId } from '../../harness/scenarios'

/**
 * Notebooks · Stack surface fixtures — 鏡射 iOS NotebookListScenarios.swift
 * (`NotebookCardData`，NotebookCard style:.grid)。catalog 不掛 SwiftData，餵合成資料。
 *
 * 兩種 scene layout（皆 `.fill` 全裝置幀 1179×2556）：
 * - 'single'：singleSheet — ScrollView{ VStack{ NotebookCard.frame(maxWidth:200) } }
 *   水平 inset pageHorizontalInset=s5(20)、top pageTopInset=16；page-bg band 僅內容寬，
 *   周圍透明（catalog corner srgba 0,0,0,0）。
 * - 'grid'：gridSheet — LazyVGrid(.adaptive minimum 160, spacing s6=24)，兩卡並排，
 *   page-bg 全幅鋪滿（catalog corner = page-bg #f7f6f3 不透明）。
 *
 * color = NotebookPalette legacy migration **後**的最終 hex（render-time 套用，
 * pixel 實測 cover = migrated 值）：
 *   #D4A843(我的單字本) → #DEC69C / #4A90D9(TOEIC) → #AFC2D3 / #5B8C5A(Self) → #B1C5AE。
 * darken(rule/dot/dark) 由渲染端依此 final hex 算。
 */

export interface NotebooksStackItem {
  name: string
  /** cover hex（NotebookPalette legacy-migration 後最終值；darken 由渲染端算） */
  color: string
  /** coverPattern — 'dots' 渲染白點(opacity 0.12, 16pt grid, r=2.5pt)；其餘略（極淡/不在本 surface） */
  pattern: 'dots' | null
  cardCount: number
  dueCount: number
  unlearnedCount: number
  reviewedCount: number
  isActive: boolean
}

export interface NotebooksStackFixture {
  layout: 'single' | 'grid'
  cards: NotebooksStackItem[]
}

// iOS mediumActive — 我的單字本 / #D4A843→#DEC69C / dots / 100 詞 / due12 unlearned8 reviewed80 / active
const mediumActive: NotebooksStackItem = {
  name: '我的單字本',
  color: '#DEC69C',
  pattern: 'dots',
  cardCount: 100,
  dueCount: 12,
  unlearnedCount: 8,
  reviewedCount: 80,
  isActive: true,
}

// iOS medium — TOEIC / #4A90D9→#AFC2D3 / dots / 100 詞 / due12 unlearned8 reviewed80 / inactive
const medium: NotebooksStackItem = {
  name: 'TOEIC',
  color: '#AFC2D3',
  pattern: 'dots',
  cardCount: 100,
  dueCount: 12,
  unlearnedCount: 8,
  reviewedCount: 80,
  isActive: false,
}

// iOS fresh — Self / #5B8C5A→#B1C5AE / no pattern / 0 詞（空 notebook，placeholder）/ inactive
const fresh: NotebooksStackItem = {
  name: 'Self',
  color: '#B1C5AE',
  pattern: null,
  cardCount: 0,
  dueCount: 0,
  unlearnedCount: 0,
  reviewedCount: 0,
  isActive: false,
}

export const NOTEBOOKS_STACK_FIXTURES: Record<ScenarioId<'notebooks-stack'>, NotebooksStackFixture> = {
  // singleSheet(card: mediumActive).preferredColorScheme(.light)
  'state-active': { layout: 'single', cards: [mediumActive] },
  // singleSheet(card: medium).preferredColorScheme(.light)
  'state-inactive': { layout: 'single', cards: [medium] },
  // gridSheet(cards: [mediumActive, medium]) — 2-up，page-bg 全幅不透明
  'd1-cover-basic': { layout: 'grid', cards: [mediumActive, medium] },
  // singleSheet(card: medium) — depth=3 層由字數決定，但 body 為扁平 cover（堆卡僅 coverArea，未用於 body）
  'depth-100': { layout: 'single', cards: [medium] },
  // singleSheet(card: fresh) — cardCount=0 → 隱藏 N 詞、metadata 顯「尚未加入單字」
  'd1-empty': { layout: 'single', cards: [fresh] },
}
