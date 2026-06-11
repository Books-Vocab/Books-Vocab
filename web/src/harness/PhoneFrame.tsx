import type { HarnessConfig } from './scenarios'
import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'
import { SettingsScreen } from '../surfaces/settings/SettingsScreen'
import { NotebookScreen } from '../surfaces/notebook/NotebookScreen'
import { ReaderScreen } from '../surfaces/reader/ReaderScreen'
import { SelectionToolbarScreen } from '../surfaces/selection/SelectionToolbarScreen'
import { SelectionTileScreen } from '../surfaces/selection/SelectionTileScreen'
import { AppShell } from '../shell/AppShell'
import { VocabularyScreen } from '../surfaces/vocabulary/VocabularyScreen'
import { TodayReviewScreen } from '../surfaces/today-review/TodayReviewScreen'
import { PodcastScreen } from '../surfaces/podcast/PodcastScreen'

/**
 * 393×852pt stage — iPhone 15 Pro portrait, the same logical size the iOS
 * Catalog renders surfaces at. Playwright captures this element at
 * deviceScaleFactor 3 → 1179×2556, pixel-aligned with Catalog snapshot PNGs.
 *
 * Surface routing lives here: each rewritten surface mounts inside the frame
 * keyed by the harness config（switch 的 exhaustiveness 由 HarnessConfig
 * discriminated union 保證——新 surface 不接路由就編不過）。
 */
function SurfaceView({ config }: { config: HarnessConfig }) {
  switch (config.surface) {
    case 'bookshelf':
      return <BookshelfScreen scenario={config.scenario} />
    case 'settings':
      return <SettingsScreen scenario={config.scenario} />
    case 'notebook':
      return <NotebookScreen scenario={config.scenario} />
    case 'reader':
      return <ReaderScreen scenario={config.scenario} />
    case 'selection-toolbar':
      return <SelectionToolbarScreen scenario={config.scenario} />
    case 'selection-tile':
      return <SelectionTileScreen scenario={config.scenario} />
    case 'vocabulary':
      return <VocabularyScreen scenario={config.scenario} />
    case 'today-review':
      return <TodayReviewScreen scenario={config.scenario} />
    case 'podcast':
      return <PodcastScreen scenario={config.scenario} />
  }
}

export function PhoneFrame({ config, shell = false }: { config: HarnessConfig; shell?: boolean }) {
  // shell=false（預設、parity capture rig 唯一路徑）：原樣渲染單一 surface，
  // data-* 屬性與 DOM 結構完全不變。shell=true（?shell=1 opt-in）：surface
  // 裝進底部 tab bar 殼，僅多掛 data-shell 標記供殼層樣式作用。
  return (
    <div
      className="phone-frame"
      data-theme={config.appearance}
      data-surface={config.surface}
      data-scenario={config.scenario}
      data-harness="phone-frame"
      data-shell={shell ? '1' : undefined}
    >
      {shell ? <AppShell config={config} /> : <SurfaceView config={config} />}
    </div>
  )
}
