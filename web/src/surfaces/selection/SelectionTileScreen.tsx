import type { ScenarioId } from '../../harness/scenarios'
import { SELECTION_TILE_FIXTURES } from './fixtures'
import './selection.css'

/**
 * Reader Selection Tile surface — iOS ReaderSelectionTile（VocabChromeSurface）
 * 的 web 重寫。chrome tile：圓角 control(6px) + 1px stroke。
 *  - selected: mutedFill + cardBorder + primaryText。
 *  - unselected: pageBackground + divider×0.6 邊框 + secondaryText。
 *
 * iOS catalog 把此元件以 intrinsic 高度（~226px native）擷取，parity normalize
 * 時縱向拉伸到全 frame。故 web 也把 tile 帶縱向填滿 frame（measured：normalize
 * 後 tile 約佔 y215–633pt、寬 ~57pt、間距 12pt(s3)、整體水平置中）。
 */
export function SelectionTileScreen({ scenario }: { scenario: ScenarioId<'selection-tile'> }) {
  const fixture = SELECTION_TILE_FIXTURES[scenario]
  return (
    <div className="selection-tile-surface">
      <div className="selection-tile-row">
        {fixture.tiles.map((tile, index) => (
          <div
            key={index}
            className="selection-tile"
            data-selected={tile.isSelected ? '' : undefined}
          >
            <span className="selection-tile-label">{tile.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
