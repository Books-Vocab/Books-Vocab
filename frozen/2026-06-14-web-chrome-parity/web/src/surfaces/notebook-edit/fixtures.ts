import type { ScenarioId } from '../../harness/scenarios'
import type { CoverPattern } from '../notebook-cover/fixtures'

/**
 * NotebookEditSheet fixtures — 鏡像 iOS `NotebookEditSheetScenarios` 的 5 個 Mode。
 *
 * 色盤逐項對齊 NotebookPalette.colors（12 Morandi 色，name+hex verbatim）；
 * pattern 逐項對齊 NotebookCoverPattern.allCases（dots/lines/grid/waves/circles/noise）。
 * cover 預覽色 = NotebookPalette.color(for:selectedColor)：scenario 的 color 皆為現行 hex
 * （非 legacy key）→ 直接 identity；color=nil → defaultHex #AFC2D3。
 */

/** NotebookPalette.colors — (name, hex)，順序即 grid 排列序（NotebookPalette.swift:22-29）。 */
export const NOTEBOOK_PALETTE: { name: string; hex: string }[] = [
  { name: '森林', hex: '#B1C5AE' },
  { name: '海洋', hex: '#AFC2D3' },
  { name: '琥珀', hex: '#DEC69C' },
  { name: '紫藤', hex: '#C5B2D0' },
  { name: '珊瑚', hex: '#DCABA4' },
  { name: '石墨', hex: '#AFB2B7' },
  { name: '薄荷', hex: '#B7D2C9' },
  { name: '靛藍', hex: '#ADABCB' },
  { name: '玫瑰', hex: '#DEBAC2' },
  { name: '焦糖', hex: '#D2B69D' },
  { name: '天空', hex: '#C5DAE2' },
  { name: '薰衣草', hex: '#C3BCCF' },
]

/** NotebookPalette.defaultHex（color=nil 時的 cover 底色）。 */
export const NOTEBOOK_DEFAULT_HEX = '#AFC2D3'

/** NotebookCoverPattern.allCases — (rawValue, label)，順序即 picker 排列序。 */
export const NOTEBOOK_PATTERNS: { id: CoverPattern; label: string }[] = [
  { id: 'dots', label: '圓點' },
  { id: 'lines', label: '條紋' },
  { id: 'grid', label: '格線' },
  { id: 'waves', label: '波浪' },
  { id: 'circles', label: '同心圓' },
  { id: 'noise', label: '噪點' },
]

export interface NotebookEditFixture {
  /** navigationTitle — create=新增單字本 / edit=編輯單字本。 */
  isCreating: boolean
  /** TextField 內容（空 → 顯示 placeholder 單字本名稱）。 */
  name: string
  /** 選定色 hex（null = 無選定 = create）。 */
  selectedColor: string | null
  /** 選定 pattern（null = 無 tile selected）。 */
  selectedPattern: CoverPattern | null
}

export const NOTEBOOK_EDIT_FIXTURES: Record<
  ScenarioId<'notebook-edit'>,
  NotebookEditFixture
> = {
  'create-blank': { isCreating: true, name: '', selectedColor: null, selectedPattern: null },
  'color-pattern': { isCreating: false, name: 'GRE 高頻字', selectedColor: '#AFC2D3', selectedPattern: 'dots' },
  'color-only': { isCreating: false, name: '雅思核心詞彙', selectedColor: '#DCABA4', selectedPattern: null },
  'long-name': {
    isCreating: false,
    name: '莎士比亞十四行詩裡那些古英文罕用字與華麗修辭專用詞庫',
    selectedColor: '#C5B2D0',
    selectedPattern: null,
  },
  'empty-name': { isCreating: false, name: '', selectedColor: '#B1C5AE', selectedPattern: null },
}
