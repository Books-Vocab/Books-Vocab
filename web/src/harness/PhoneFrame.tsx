import { useState } from 'react'
import type { Appearance, HarnessConfig } from './scenarios'
import { AppearanceContext } from './appearance'
import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'
import { SettingsScreen } from '../surfaces/settings/SettingsScreen'
import { NotebookScreen } from '../surfaces/notebook/NotebookScreen'
import { ReaderScreen } from '../surfaces/reader/ReaderScreen'
import { SelectionToolbarScreen } from '../surfaces/selection/SelectionToolbarScreen'
import { SelectionTileScreen } from '../surfaces/selection/SelectionTileScreen'
import { VocabSortPillScreen } from '../surfaces/vocab-shell/VocabSortPillScreen'
import { VocabAccessoryIconButtonScreen } from '../surfaces/vocab-accessory-icon-button/VocabAccessoryIconButtonScreen'
import { VocabSliderRowScreen } from '../surfaces/vocab-slider-row/VocabSliderRowScreen'
import { VocabToneChipScreen } from '../surfaces/vocab-tone-chip/VocabToneChipScreen'
import { VocabChromeIconButtonScreen } from '../surfaces/vocab-chrome-icon-button/VocabChromeIconButtonScreen'
import { VocabInlineActionButtonScreen } from '../surfaces/vocab-inline-action-button/VocabInlineActionButtonScreen'
import { VocabSearchFieldScreen } from '../surfaces/vocab-search-field/VocabSearchFieldScreen'
import { VocabSectionHeaderScreen } from '../surfaces/vocab-section-header/VocabSectionHeaderScreen'
import { VocabReviewProgressBarScreen } from '../surfaces/vocab-review-progress-bar/VocabReviewProgressBarScreen'
import { VocabReviewCTAPillScreen } from '../surfaces/vocab-review-cta-pill/VocabReviewCTAPillScreen'
import { VocabTabSelectorScreen } from '../surfaces/vocab-tab-selector/VocabTabSelectorScreen'
import { VocabToolbarGlyphScreen } from '../surfaces/vocab-toolbar-glyph/VocabToolbarGlyphScreen'
import { VocabEmptyStateScreen } from '../surfaces/vocab-empty-state/VocabEmptyStateScreen'
import { AppShell } from '../shell/AppShell'
import { VocabularyScreen } from '../surfaces/vocabulary/VocabularyScreen'
import { TodayReviewScreen } from '../surfaces/today-review/TodayReviewScreen'
import { PodcastScreen } from '../surfaces/podcast/PodcastScreen'
import { OverviewScreen } from '../surfaces/overview/OverviewScreen'

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
    case 'vocab-sort-pill':
      return <VocabSortPillScreen scenario={config.scenario} />
    case 'vocab-accessory-icon-button':
      return <VocabAccessoryIconButtonScreen scenario={config.scenario} />
    case 'vocab-slider-row':
      return <VocabSliderRowScreen scenario={config.scenario} />
    case 'vocab-tone-chip':
      return <VocabToneChipScreen scenario={config.scenario} />
    case 'vocab-chrome-icon-button':
      return <VocabChromeIconButtonScreen scenario={config.scenario} />
    case 'vocab-inline-action-button':
      return <VocabInlineActionButtonScreen scenario={config.scenario} />
    case 'vocab-search-field':
      return <VocabSearchFieldScreen scenario={config.scenario} />
    case 'vocab-section-header':
      return <VocabSectionHeaderScreen scenario={config.scenario} />
    case 'vocab-review-progress-bar':
      return <VocabReviewProgressBarScreen scenario={config.scenario} />
    case 'vocab-review-cta-pill':
      return <VocabReviewCTAPillScreen scenario={config.scenario} />
    case 'vocab-tab-selector':
      return <VocabTabSelectorScreen scenario={config.scenario} />
    case 'vocab-toolbar-glyph':
      return <VocabToolbarGlyphScreen scenario={config.scenario} />
    case 'vocab-empty-state':
      return <VocabEmptyStateScreen scenario={config.scenario} />
    case 'vocabulary':
      return <VocabularyScreen scenario={config.scenario} />
    case 'today-review':
      return <TodayReviewScreen scenario={config.scenario} />
    case 'podcast':
      return <PodcastScreen scenario={config.scenario} />
    case 'overview':
      return <OverviewScreen scenario={config.scenario} />
  }
}

export function PhoneFrame({
  config,
  shell = false,
  crop = false,
}: {
  config: HarnessConfig
  shell?: boolean
  crop?: boolean
}) {
  // 互動層：data-theme 由本地 state 驅動，**初值 = config.appearance**，故 parity
  // capture 的首次渲染與靜態版逐位元相同；只有 Settings 外觀 picker 觸發後才變。
  const [appearance, setAppearance] = useState<Appearance>(config.appearance)

  // shell=false（預設、parity capture rig 唯一路徑）：原樣渲染單一 surface，
  // data-* 屬性與 DOM 結構完全不變。shell=true（?shell=1 opt-in）：surface
  // 裝進底部 tab bar 殼，僅多掛 data-shell 標記供殼層樣式作用。
  //
  // crop=true（?crop=component opt-in）：元件級 parity case。掛 data-crop="component"
  // 讓 surface CSS 卸掉 in-app safe-area / 全幅留白，把元件還原至 iOS catalog
  // 緊裁切 scene 的 intrinsic bounds（如 SelectionToolbar 收掉 44.7pt home-indicator
  // 安全區 → 元件高 = 64pt = 192px@dpr3）。shots.mjs 再以 manifest 的 `crop` 選擇器
  // 截元件 DOM 自身。預設不啟用，既有 capture 行為與 DOM 完全不變。
  return (
    <AppearanceContext.Provider value={{ appearance, setAppearance }}>
      <div
        className="phone-frame"
        data-theme={appearance}
        data-surface={config.surface}
        data-scenario={config.scenario}
        data-harness="phone-frame"
        data-shell={shell ? '1' : undefined}
        data-crop={crop ? 'component' : undefined}
      >
        {shell ? <AppShell config={config} /> : <SurfaceView config={config} />}
      </div>
    </AppearanceContext.Provider>
  )
}
