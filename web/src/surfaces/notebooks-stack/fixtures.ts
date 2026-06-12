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

// iOS massiveCount — Massive Vocab / #AFC2D3（「海洋」，非 migration key → identity）/ dots /
// 99999 詞 / due42 reviewed99947 / inactive。D1 邊界：monoLabel 字寬不抖、rule width 25%。
const massiveCount: NotebooksStackItem = {
  name: 'Massive Vocab',
  color: '#AFC2D3',
  pattern: 'dots',
  cardCount: 99999,
  dueCount: 42,
  unlearnedCount: 10,
  reviewedCount: 99947,
  isActive: false,
}

// iOS massiveDue — Heavy Due / #DCABA4（「珊瑚」，migration value 非 key → identity）/ no pattern /
// 9999 詞 / due9999（全到期）/ active。D2 邊界：bottom chip 不擠破 ProgressCapsule。
const massiveDue: NotebooksStackItem = {
  name: 'Heavy Due',
  color: '#DCABA4',
  pattern: null,
  cardCount: 9999,
  dueCount: 9999,
  unlearnedCount: 0,
  reviewedCount: 0,
  isActive: true,
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
  // ── batch expansion（dots/null pattern only，light，全幀；複用既有元件） ──
  // singleSheet(card: fresh) — Depth 0 字（1 層；同 d1-empty 渲染，distinct catalog scene）
  'depth-0': { layout: 'single', cards: [fresh] },
  // singleSheet(card: massiveCount) — D1 99999 詞 monoLabel 邊界
  'd1-large-card-count': { layout: 'single', cards: [massiveCount] },
  // gridSheet(cards: [massiveDue, medium]) — D1 9999 到期 chip 不擠破
  'd1-large-due-count': { layout: 'grid', cards: [massiveDue, medium] },
  // gridSheet(cards: [medium, fresh]) — D2 grid 高度穩定（due=0/>0 同高）
  'd2-grid-height': { layout: 'grid', cards: [medium, fresh] },
  // gridSheet(cards: [mediumActive, medium]) — Editorial 不同 seed（同 d1-cover-basic 渲染，distinct scene）
  'editorial-different-seeds': { layout: 'grid', cards: [mediumActive, medium] },
  // singleSheet(card: mediumActive) — Editorial spine rotation（同 state-active 渲染，distinct scene）
  'editorial-spine-rotation': { layout: 'single', cards: [mediumActive] },
  // gridSheet(cards: [mediumActive, fresh]) — Stress happy 2-up
  'stress-happy-2up': { layout: 'grid', cards: [mediumActive, fresh] },
}
