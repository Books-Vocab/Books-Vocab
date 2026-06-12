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
import { VocabSceneShellScreen } from '../surfaces/vocab-scene-shell/VocabSceneShellScreen'
import { VocabHighlightPickerScreen } from '../surfaces/vocab-highlight-picker/VocabHighlightPickerScreen'
import { CollocationExplainScreen } from '../surfaces/collocation-explain/CollocationExplainScreen'
import { LinkReasonSheetScreen } from '../surfaces/link-reason-sheet/LinkReasonSheetScreen'
import { NotebookEditSheetScreen } from '../surfaces/notebook-edit/NotebookEditSheetScreen'
import { WordEditScreen } from '../surfaces/word-edit/WordEditScreen'
import { VocabCalendarScreen } from '../surfaces/vocab-calendar/VocabCalendarScreen'
import { VocabForecastScreen } from '../surfaces/vocab-forecast/VocabForecastScreen'
import { VocabHeatmapScreen } from '../surfaces/vocab-heatmap/VocabHeatmapScreen'
import { ReviewBannerScreen } from '../surfaces/review-banner/ReviewBannerScreen'
import { VocabAddLinkScreen } from '../surfaces/vocab-add-link/VocabAddLinkScreen'
import { VocabLinkedCardScreen } from '../surfaces/vocab-linked-card/VocabLinkedCardScreen'
import { KgEmptyStateScreen } from '../surfaces/kg-empty-state/KgEmptyStateScreen'
import { SyncScreen } from '../surfaces/sync/SyncScreen'
import { NotebooksCardScreen } from '../surfaces/notebooks-card/NotebooksCardScreen'
import { KGVocabRowScreen } from '../surfaces/kg-vocab-row/KGVocabRowScreen'
import { BookCardScreen } from '../surfaces/book-card/BookCardScreen'
import { SubscriptionGateCardScreen } from '../surfaces/subscription-gate-card/SubscriptionGateCardScreen'
import { ReviewFoldChevronScreen } from '../surfaces/review-fold-chevron/ReviewFoldChevronScreen'
import { ReviewFoldPaperScreen } from '../surfaces/review-fold-paper/ReviewFoldPaperScreen'
import { ReviewFoldSegmentScreen } from '../surfaces/review-fold-segment/ReviewFoldSegmentScreen'
import { PodcastContinueCardScreen } from '../surfaces/podcast-continue-card/PodcastContinueCardScreen'
import { PodcastEpisodeRowScreen } from '../surfaces/podcast-episode-row/PodcastEpisodeRowScreen'
import { PodcastSeriesCardScreen } from '../surfaces/podcast-series-card/PodcastSeriesCardScreen'
import { NotebookCoverScreen } from '../surfaces/notebook-cover/NotebookCoverScreen'
import { NotebooksStackScreen } from '../surfaces/notebooks-stack/NotebooksStackScreen'
import { WordDetailCardScreen } from '../surfaces/word-detail-card/WordDetailCardScreen'
import { SettingsPreferencesScreen } from '../surfaces/settings-preferences/SettingsPreferencesScreen'
import { SettingsReviewScreen } from '../surfaces/settings-review/SettingsReviewScreen'
import { SettingsSubscriptionScreen } from '../surfaces/settings-subscription/SettingsSubscriptionScreen'
import { PodcastBubbleCellScreen } from '../surfaces/podcast-bubble-cell/PodcastBubbleCellScreen'
import { PodcastHeroScreen } from '../surfaces/podcast-hero/PodcastHeroScreen'
import { PodcastRailCardScreen } from '../surfaces/podcast-rail-card/PodcastRailCardScreen'
import { AccountAuthSummaryScreen } from '../surfaces/account-auth-summary/AccountAuthSummaryScreen'
import { AccountSectionScreen } from '../surfaces/account-section/AccountSectionScreen'
import { LoginSheetScreen } from '../surfaces/login-sheet/LoginSheetScreen'
import { WelcomeScreen } from '../surfaces/welcome/WelcomeScreen'
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
    case 'vocab-scene-shell':
      return <VocabSceneShellScreen scenario={config.scenario} />
    case 'vocab-highlight-picker':
      return <VocabHighlightPickerScreen scenario={config.scenario} />
    case 'collocation-explain':
      return <CollocationExplainScreen scenario={config.scenario} />
    case 'link-reason-sheet':
      return <LinkReasonSheetScreen scenario={config.scenario} />
    case 'notebook-edit':
      return <NotebookEditSheetScreen scenario={config.scenario} />
    case 'word-edit':
      return <WordEditScreen scenario={config.scenario} />
    case 'vocab-calendar':
      return <VocabCalendarScreen scenario={config.scenario} />
    case 'vocab-forecast':
      return <VocabForecastScreen scenario={config.scenario} />
    case 'vocab-heatmap':
      return <VocabHeatmapScreen scenario={config.scenario} />
    case 'review-banner':
      return <ReviewBannerScreen scenario={config.scenario} />
    case 'vocab-add-link':
      return <VocabAddLinkScreen scenario={config.scenario} />
    case 'vocab-linked-card':
      return <VocabLinkedCardScreen scenario={config.scenario} />
    case 'kg-empty-state':
      return <KgEmptyStateScreen scenario={config.scenario} />
    case 'sync':
      return <SyncScreen scenario={config.scenario} />
    case 'notebooks-card':
      return <NotebooksCardScreen scenario={config.scenario} />
    case 'kg-vocab-row':
      return <KGVocabRowScreen scenario={config.scenario} />
    case 'book-card':
      return <BookCardScreen scenario={config.scenario} />
    case 'subscription-gate-card':
      return <SubscriptionGateCardScreen scenario={config.scenario} />
    case 'review-fold-chevron':
      return <ReviewFoldChevronScreen scenario={config.scenario} />
    case 'review-fold-paper':
      return <ReviewFoldPaperScreen scenario={config.scenario} />
    case 'review-fold-segment':
      return <ReviewFoldSegmentScreen scenario={config.scenario} />
    case 'podcast-continue-card':
      return <PodcastContinueCardScreen scenario={config.scenario} />
    case 'podcast-episode-row':
      return <PodcastEpisodeRowScreen scenario={config.scenario} />
    case 'podcast-series-card':
      return <PodcastSeriesCardScreen scenario={config.scenario} />
    case 'notebook-cover':
      return <NotebookCoverScreen scenario={config.scenario} />
    case 'notebooks-stack':
      return <NotebooksStackScreen scenario={config.scenario} />
    case 'word-detail-card':
      return <WordDetailCardScreen scenario={config.scenario} />
    case 'settings-preferences':
      return <SettingsPreferencesScreen scenario={config.scenario} />
    case 'settings-review':
      return <SettingsReviewScreen scenario={config.scenario} />
    case 'settings-subscription':
      return <SettingsSubscriptionScreen scenario={config.scenario} />
    case 'podcast-bubble-cell':
      return <PodcastBubbleCellScreen scenario={config.scenario} />
    case 'podcast-hero':
      return <PodcastHeroScreen scenario={config.scenario} />
    case 'podcast-rail-card':
      return <PodcastRailCardScreen scenario={config.scenario} />
    case 'account-auth-summary':
      return <AccountAuthSummaryScreen scenario={config.scenario} />
    case 'account-section':
      return <AccountSectionScreen scenario={config.scenario} />
    case 'login-sheet':
      return <LoginSheetScreen scenario={config.scenario} />
    case 'welcome':
      return <WelcomeScreen scenario={config.scenario} />
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
