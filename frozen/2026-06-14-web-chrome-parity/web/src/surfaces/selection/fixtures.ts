import type { ScenarioId } from '../../harness/scenarios'

/**
 * Selection surfaces fixtures — 鏡像兩個 iOS Catalog 元件 surface：
 *
 *  1. Selection Toolbar（SelectionToolbarScenarios.swift）— vocab 多選底欄。
 *     selectionCount 純驅動狀態：0 → archive/delete 皆灰（quaternaryText、
 *     disabled）；>0 → archive=quaternaryText、delete=destructive 紅。
 *
 *  2. Reader Selection Tile（ReaderSelectionTileScenarios.swift，PR #929）—
 *     chrome tile。isSelected 二元：selected = mutedFill + cardBorder +
 *     primaryText；unselected = pageBackground + divider×0.6 邊框 + secondaryText。
 *
 * 兩 surface 皆 light appearance（catalog 在 light 渲染）；toolbar 全寬底欄填
 * 滿 frame（card pinned bottom），tile 為短元件帶（normalize 後縱向拉伸）。
 */

/* ============================================================
   Selection Toolbar
   ============================================================ */

export interface SelectionToolbarFixture {
  /** state.selectionCount — 0 時兩鈕皆灰 disabled，>0 啟用（archive 灰 / delete 紅）。 */
  selectionCount: number
}

export const SELECTION_TOOLBAR_FIXTURES: Record<ScenarioId<'selection-toolbar'>, SelectionToolbarFixture> = {
  // Multiple selected — count 12：archive=quaternaryText、delete=destructive。
  'selection-multiple': { selectionCount: 12 },
  // Single selected — count 1：同 enabled 視覺（tone 不隨 count 變，只看 >0）。
  'selection-single': { selectionCount: 1 },
  // No selection (disabled) — count 0：兩鈕皆 quaternaryText 灰、disabled。
  'selection-none': { selectionCount: 0 },
}

/* ============================================================
   Reader Selection Tile
   ============================================================ */

export interface SelectionTileFixture {
  /** 並排對比（pair）顯示兩 tile；單態（selected/unselected）只顯示一 tile。 */
  tiles: { isSelected: boolean; label: string }[]
}

export const SELECTION_TILE_FIXTURES: Record<ScenarioId<'selection-tile'>, SelectionTileFixture> = {
  // Selected vs Unselected — 並排對比（已選 mutedFill / 未選 pageBackground）。
  'selection-pair': {
    tiles: [
      { isSelected: true, label: '已選' },
      { isSelected: false, label: '未選' },
    ],
  },
  // Selected — 單 tile（mutedFill + primaryText）。
  'selection-selected': { tiles: [{ isSelected: true, label: '已選' }] },
  // Unselected — 單 tile（pageBackground + secondaryText）。
  'selection-unselected': { tiles: [{ isSelected: false, label: '未選' }] },
}
