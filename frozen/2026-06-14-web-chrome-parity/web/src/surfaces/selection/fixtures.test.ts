import { describe, expect, it } from 'vitest'
import { SELECTION_TOOLBAR_FIXTURES, SELECTION_TILE_FIXTURES } from './fixtures'

// 鏡像 ios/BooksAndVocab/Debug/Scenarios/SelectionToolbarScenarios.swift +
// ReaderSelectionTileScenarios.swift 的 seed。toolbar 由 selectionCount 驅動
// （0 disabled / >0 enabled），tile 由 isSelected 二元驅動。
describe('SELECTION_TOOLBAR_FIXTURES', () => {
  it('covers exactly the 3 SelectionToolbarScenarios states', () => {
    expect(Object.keys(SELECTION_TOOLBAR_FIXTURES).sort()).toEqual([
      'selection-multiple',
      'selection-none',
      'selection-single',
    ])
  })

  it('selection-none is the disabled (count 0) state', () => {
    expect(SELECTION_TOOLBAR_FIXTURES['selection-none'].selectionCount).toBe(0)
  })

  it('single + multiple are enabled (count > 0)', () => {
    expect(SELECTION_TOOLBAR_FIXTURES['selection-single'].selectionCount).toBe(1)
    expect(SELECTION_TOOLBAR_FIXTURES['selection-multiple'].selectionCount).toBe(12)
  })
})

describe('SELECTION_TILE_FIXTURES', () => {
  it('covers exactly the 3 ReaderSelectionTileScenarios states', () => {
    expect(Object.keys(SELECTION_TILE_FIXTURES).sort()).toEqual([
      'selection-pair',
      'selection-selected',
      'selection-unselected',
    ])
  })

  it('pair shows selected + unselected side by side（已選 / 未選）', () => {
    const tiles = SELECTION_TILE_FIXTURES['selection-pair'].tiles
    expect(tiles).toHaveLength(2)
    expect(tiles[0]).toEqual({ isSelected: true, label: '已選' })
    expect(tiles[1]).toEqual({ isSelected: false, label: '未選' })
  })

  it('single states render one tile of the matching selection', () => {
    const selected = SELECTION_TILE_FIXTURES['selection-selected'].tiles
    expect(selected).toHaveLength(1)
    expect(selected[0].isSelected).toBe(true)

    const unselected = SELECTION_TILE_FIXTURES['selection-unselected'].tiles
    expect(unselected).toHaveLength(1)
    expect(unselected[0].isSelected).toBe(false)
  })
})
