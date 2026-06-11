import type { ScenarioId } from '../../harness/scenarios'

/**
 * Notebook surface fixtures — mirrors iOS Catalog "Notebook List View"
 * (NotebookListViewScenarios.swift seed). 每本 notebook 都用 default 封面色
 * #AFC2D3（海洋，NotebookPalette.defaultHex）、無 coverPattern；所有 entry
 * 都是 freshly-added 未學卡 → cardCount == unlearnedCount == actionableCount，
 * reviewedCount == 0（進度條空）。active = 我的單字本（activeNotebookId="default"）。
 */

export interface NotebookFixtureCard {
  /** 封面 serif italic 書名。 */
  name: string
  /** 封面底色 hex（NotebookPalette.color(for:)；catalog seed 全用 default）。 */
  color: string
  /** N 詞 = cardCount。 */
  cardCount: number
  /** 封面/右欄黃點數字 = dueCount + unlearnedCount（NotebookCardData.actionableCount）。 */
  actionableCount: number
  /** 0–1 已複習比例（catalog seed 全 0 → track-only）。 */
  reviewProgress: number
  /** active notebook：封面名稱前 5pt 圓點。 */
  isActive: boolean
}

export interface NotebookFixture {
  /** 今日複習 CTA pill 顯示的總數（filtered due+unlearned 合計）。 */
  reviewTotal: number
  /** notebooks.count >= 2 時才顯示篩選 pill（iOS NotebookReviewActionBar gate）。 */
  showFilter: boolean
  cards: NotebookFixtureCard[]
}

/** NotebookPalette.defaultHex（海洋）— catalog seed 的 notebook color 皆為 nil → default。 */
const DEFAULT_COVER = '#AFC2D3'

const MY_NOTEBOOK: NotebookFixtureCard = {
  name: '我的單字本',
  color: DEFAULT_COVER,
  cardCount: 3,
  actionableCount: 3,
  reviewProgress: 0,
  isActive: true,
}

const CLASSICS: NotebookFixtureCard = {
  name: '經典文學',
  color: DEFAULT_COVER,
  cardCount: 2,
  actionableCount: 2,
  reviewProgress: 0,
  isActive: false,
}

const SCIENCE: NotebookFixtureCard = {
  name: '科普閱讀',
  color: DEFAULT_COVER,
  cardCount: 1,
  actionableCount: 1,
  reviewProgress: 0,
  isActive: false,
}

export const NOTEBOOK_FIXTURES: Record<ScenarioId<'notebook'>, NotebookFixture> = {
  // 3 notebooks → filter pill 顯示；CTA 6 = 3+2+1。
  populated: {
    reviewTotal: 6,
    showFilter: true,
    cards: [MY_NOTEBOOK, CLASSICS, SCIENCE],
  },
  // 1 notebook → 無 filter pill（notebookCount < 2）；CTA 3。
  single: {
    reviewTotal: 3,
    showFilter: false,
    cards: [MY_NOTEBOOK],
  },
}
