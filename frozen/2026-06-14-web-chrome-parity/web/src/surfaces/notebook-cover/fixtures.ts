import type { ScenarioId } from '../../harness/scenarios'

/**
 * NotebookCover surface fixtures — iOS `NotebookCoverView` / `NotebookCoverPattern`
 * 的 web 鏡像資料（catalog 全合成，對齊 NotebookCoverScenarios.swift）。
 *
 * cover color = NotebookPalette raw hex（fixture data，非 design token，比照
 * notebooks-card 的 inline style 慣例）；pattern = 6 種 Canvas overlay 之一或 nil。
 */

export type CoverPattern = 'dots' | 'lines' | 'grid' | 'waves' | 'circles' | 'noise'

export interface CoverItem {
  color: string
  pattern: CoverPattern | null
  name: string
  showsName: boolean
  /** image-path fallback：路徑不存在 → 降級渲染 pattern（web 永遠 nil 影像，等價 fallback） */
  imageFallback?: boolean
}

// NotebookCoverScenarios palette（Color(hex:)，fixture data colors）
const BLUE = '#4A90D9'
const PURPLE = '#8E6FD6'
const GREEN = '#3FA77A'
const CORAL = '#E0735C'

const SWATCHES = [BLUE, PURPLE, GREEN, CORAL]

// NotebookCoverPattern.allCases 順序 + label
const ALL_PATTERNS: { pattern: CoverPattern; label: string }[] = [
  { pattern: 'dots', label: '圓點' },
  { pattern: 'lines', label: '條紋' },
  { pattern: 'grid', label: '格線' },
  { pattern: 'waves', label: '波浪' },
  { pattern: 'circles', label: '同心圓' },
  { pattern: 'noise', label: '噪點' },
]

function patternGrid(color: string, showsName = true): CoverItem[] {
  return ALL_PATTERNS.map(({ pattern, label }) => ({
    color,
    pattern,
    name: label,
    showsName,
  }))
}

export interface CoverScene {
  /** outer wrapper：'grid' = LazyVGrid(adaptive 110, gap 16)；'rows' = VStack(gap16) of LazyVGrid(adaptive 110, gap12) */
  layout: 'grid' | 'rows'
  items: CoverItem[]
  /** rows layout 時，每個 row 的 item 數（=6 patterns），用以切 row */
  rowSize?: number
}

export const NOTEBOOK_COVER_FIXTURES: Record<ScenarioId<'notebook-cover'>, CoverScene> = {
  // All patterns · blue — patternGrid(blue)
  'all-patterns-blue': {
    layout: 'grid',
    items: patternGrid(BLUE),
  },
  // All patterns · color swatches — VStack(16) of patternRow(color)（每色 6 pattern）
  'color-swatches': {
    layout: 'rows',
    rowSize: ALL_PATTERNS.length,
    items: SWATCHES.flatMap((color) => patternGrid(color)),
  },
  // Solid color · no pattern — 4 swatches，pattern nil，name 純色
  'solid-no-pattern': {
    layout: 'grid',
    items: SWATCHES.map((color) => ({ color, pattern: null, name: '純色', showsName: true })),
  },
  // Long name truncate — 3 covers，長名 lineLimit 2 + tail truncate
  'long-name-truncate': {
    layout: 'grid',
    items: [
      { color: BLUE, pattern: 'dots', name: '我的英文單字本 — 進階學術詞彙與片語收藏夾', showsName: true },
      { color: PURPLE, pattern: 'grid', name: 'Supercalifragilisticexpialidocious Notebook', showsName: true },
      { color: GREEN, pattern: 'waves', name: '短', showsName: true },
    ],
  },
  // showsName = false (overlay use) — patternGrid(purple, showsName:false)
  'shows-name-false': {
    layout: 'grid',
    items: patternGrid(PURPLE, false),
  },
  // Image path fallback (missing → pattern) — 路徑不存在 → 降級 pattern / 純色
  'image-fallback': {
    layout: 'grid',
    items: [
      { color: GREEN, pattern: 'circles', name: 'Fallback', showsName: true, imageFallback: true },
      { color: BLUE, pattern: null, name: '純色 Fallback', showsName: true, imageFallback: true },
    ],
  },
}
