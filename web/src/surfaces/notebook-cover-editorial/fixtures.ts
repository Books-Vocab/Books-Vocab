import type { ScenarioId } from '../../harness/scenarios'

/**
 * Notebook Cover · Editorial fixtures — iOS `EditorialCoverComposition`
 * （NotebookCard.swift）的 web 鏡像資料，逐字對齊
 * NotebookCardEditorialCoverScenarios.swift。
 *
 * scene = AppThemeContainer{ ZStack[ RoundedRect(coverColor*0.35) → composition ]
 *   .frame(grid 168×224 / hero 320×200).clipShape(RoundedRect(lg=12)).padding(s4=16) }，
 * 畫布透明（component-isolated）。coverColor = Color(red:green:blue:) → round(c*255)
 * 的 fixture data hex；rule/spine = NotebookPalette.darken(coverColor, 0.3/0.4)
 * （HSB brightness×(1-amount)），由 CSS 端 runtime 推導，這裡只存 base hex。
 */

export type EditorialCoverStyle = 'grid' | 'hero'

export interface EditorialCoverItem {
  name: string
  cardCount: number
  /** Color(red:green:blue:) → round(c*255) 的 sRGB hex（fixture data color） */
  coverColor: string
  isActive: boolean
  style: EditorialCoverStyle
}

// Color(red:g:b:) → '#' + round(c*255).toString(16)
// 0.42,0.55,0.78 → 107,140,199 #6B8CC7
const BLUE = '#6B8CC7'
// 0.78,0.62,0.45 → 199,158,115 #C79E73
const TAN = '#C79E73'
// 0.55,0.42,0.62 → 140,107,158 #8C6B9E
const PLUM = '#8C6B9E'
// 0.36,0.66,0.58 → 92,168,148 #5CA894
const TEAL = '#5CA894'
// 0.82,0.45,0.45 → 209,115,115 #D17373
const ROSE = '#D17373'

export const NOTEBOOK_COVER_EDITORIAL_FIXTURES: Record<
  ScenarioId<'notebook-cover-editorial'>,
  EditorialCoverItem
> = {
  'grid-default': {
    name: '晨間散文',
    cardCount: 48,
    coverColor: BLUE,
    isActive: false,
    style: 'grid',
  },
  'grid-active': {
    name: '晨間散文',
    cardCount: 48,
    coverColor: BLUE,
    isActive: true,
    style: 'grid',
  },
  'grid-empty': {
    name: '新筆記本',
    cardCount: 0,
    coverColor: TAN,
    isActive: false,
    style: 'grid',
  },
  'grid-long-name': {
    name: '十九世紀英國浪漫主義詩歌精選與註解合集',
    cardCount: 1280,
    coverColor: PLUM,
    isActive: true,
    style: 'grid',
  },
  'hero-default': {
    name: '夜讀筆記',
    cardCount: 312,
    coverColor: TEAL,
    isActive: false,
    style: 'hero',
  },
  'hero-active': {
    name: '夜讀筆記',
    cardCount: 312,
    coverColor: ROSE,
    isActive: true,
    style: 'hero',
  },
}
