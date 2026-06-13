import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'
import { NotebookScreen } from '../surfaces/notebook/NotebookScreen'
import { PodcastScreen } from '../surfaces/podcast/PodcastScreen'
import { ReaderScreen } from '../surfaces/reader/ReaderScreen'
import { SettingsScreen } from '../surfaces/settings/SettingsScreen'
import { TodayReviewScreen } from '../surfaces/today-review/TodayReviewScreen'
import { VocabularyScreen } from '../surfaces/vocabulary/VocabularyScreen'
import { OverviewScreen } from '../surfaces/overview/OverviewScreen'
// 深層導航目標 surface（shell-only 可達；parity capture 不經 renderScreen）。
import { SyncScreen } from '../surfaces/sync/SyncScreen'
import { SettingsReviewScreen } from '../surfaces/settings-review/SettingsReviewScreen'
import { SettingsSubscriptionScreen } from '../surfaces/settings-subscription/SettingsSubscriptionScreen'
import { SettingsAccountDetailScreen } from '../surfaces/settings-account-detail/SettingsAccountDetailScreen'
import { TranslationLanguageSettingsScreen } from '../surfaces/translation-language-settings/TranslationLanguageSettingsScreen'
import { KnowledgeGraphViewScreen } from '../surfaces/knowledge-graph-view/KnowledgeGraphViewScreen'
import { VocabKnowledgeGraphScreen } from '../surfaces/vocab-knowledge-graph/VocabKnowledgeGraphScreen'
import { WordDetailSheetScreen } from '../surfaces/word-detail-sheet/WordDetailSheetScreen'
import { VocabAddLinkScreen } from '../surfaces/vocab-add-link/VocabAddLinkScreen'
import { NotebookEditSheetScreen } from '../surfaces/notebook-edit/NotebookEditSheetScreen'
import { PodcastEpisodeListScreen } from '../surfaces/podcast-episode-list/PodcastEpisodeListScreen'
import { PodcastHomeScreen } from '../surfaces/podcast-home/PodcastHomeScreen'
import type { Screen } from './nav'

/**
 * 共享 screen registry — Screen → surface 元件的純映射（單一真相）。
 *
 * 由殼層（mobile AppShell、桌面 ResponsiveShell）共用一張 surface 路由表：兩個殼
 * 的「畫面 → 渲染哪個 surface 元件」邏輯不得各自 fork，否則導航圖會雙面 drift。
 * 本模組純函式、無 React state、無 DOM 假設，只把 nav.ts 的 `Screen`（discriminated
 * union：surface + 該 surface 合法 scenario）映成對應 surface 元件。
 *
 * Live Reader（epub.js 真渲染）刻意不在此處：那是 AppShell 依「書庫 tab depth>1」
 * 動態 lazy-mount 的殼層行為（自帶 chrome / 返回鈕），非單純 Screen→surface 映射。
 *
 * 誠實邊界：parity capture 走 PhoneFrame 的 SurfaceView（shell===false），完全不經
 * 本 registry；故此處新增/調整 case 對 parity DOM 與截圖零影響。
 *
 * 注：surface 在 shell 內讀「攜帶的實體 id」走 ShellNavContext.params（見
 * ShellNavProvider 注入），prop 優先於 window.location.search，後者為 deep-link
 * fallback。surface 公開 prop 簽章不變（仍只吃 scenario），故 parity 路徑零改動。
 */
export function renderScreen(screen: Screen) {
  // discriminated union：switch 後 scenario 自動窄化為該 surface 合法 id。
  switch (screen.surface) {
    case 'bookshelf':
      return <BookshelfScreen scenario={screen.scenario} />
    case 'notebook':
      return <NotebookScreen scenario={screen.scenario} />
    case 'settings':
      return <SettingsScreen scenario={screen.scenario} />
    case 'reader':
      return <ReaderScreen scenario={screen.scenario} />
    case 'vocabulary':
      return <VocabularyScreen scenario={screen.scenario} />
    case 'today-review':
      return <TodayReviewScreen scenario={screen.scenario} />
    case 'podcast':
      return <PodcastScreen scenario={screen.scenario} />
    case 'podcast-home':
      return <PodcastHomeScreen scenario={screen.scenario} />
    case 'overview':
      return <OverviewScreen scenario={screen.scenario} />
    // ── 深層導航目標（shell-only push 進來；各 surface 自帶 ?shell=1 live 分支）──
    case 'sync':
      return <SyncScreen scenario={screen.scenario} />
    case 'settings-review':
      return <SettingsReviewScreen scenario={screen.scenario} />
    case 'settings-subscription':
      return <SettingsSubscriptionScreen scenario={screen.scenario} />
    case 'settings-account-detail':
      return <SettingsAccountDetailScreen scenario={screen.scenario} />
    case 'translation-language-settings':
      return <TranslationLanguageSettingsScreen scenario={screen.scenario} />
    case 'knowledge-graph-view':
      return <KnowledgeGraphViewScreen scenario={screen.scenario} />
    case 'vocab-knowledge-graph':
      return <VocabKnowledgeGraphScreen scenario={screen.scenario} />
    case 'word-detail-sheet':
      return <WordDetailSheetScreen scenario={screen.scenario} />
    case 'vocab-add-link':
      return <VocabAddLinkScreen scenario={screen.scenario} />
    case 'notebook-edit':
      return <NotebookEditSheetScreen scenario={screen.scenario} />
    case 'podcast-episode-list':
      return <PodcastEpisodeListScreen scenario={screen.scenario} />
    // 其餘 surface（元件級 scene / 尚無殼層入口）不會進 nav stack → 不渲染。
    default:
      return null
  }
}
